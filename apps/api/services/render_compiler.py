"""Render compiler: converts EditPlan -> deterministic FFmpeg commands."""

import hashlib
import json
import logging
import os
import random
import re as _re
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Optional

from apps.api.config import MUSIC_DIR, MAX_RENDER_TIMEOUT_SEC
from apps.api.models.schemas import EditPlan

logger = logging.getLogger(__name__)

# Maximum chars of FFmpeg stderr to include in error messages
_MAX_STDERR_CHARS = 2000

def _find_weird_chars(s: str) -> list[tuple[int, str, int, str]]:
    """
    Returns (index, char, ord, unicode_category) for characters that commonly
    break ffmpeg argv parsing and filtergraph parsing:
    - Cc (control) and Cf (format/zero-width)
    - Unicode line separators U+2028/U+2029
    """
    out: list[tuple[int, str, int, str]] = []
    for i, ch in enumerate(s or ""):
        o = ord(ch)
        cat = unicodedata.category(ch)  # e.g. "Cf" (format), "Cc" (control)
        if cat in ("Cf", "Cc") or ch in {"\u2028", "\u2029"} or (cat == "Zs" and ch != " "):
            out.append((i, ch, o, cat))
    return out

# ---------------------------------------------------------------------------
# B-roll look presets (video filters applied to b-roll clips ONLY)
# ---------------------------------------------------------------------------
BROLL_LOOK_PRESET_FF_FILTER = (
    "eq=contrast=1.06:brightness=0.02:saturation=1.12,"
    "unsharp=5:5:0.5:5:5:0.0,"
    "colorbalance=rs=0.04:gs=-0.02:bs=-0.05:rh=0.03:gh=-0.01:bh=-0.04,"
    "noise=c0s=3:c0f=t"
)

BROLL_TV_LOOK_PRESET_FF_FILTER = (
    "eq=contrast=1.12:brightness=-0.01:saturation=0.85,"
    "unsharp=5:5:0.7:5:5:0.0,"
    "colorbalance=rs=0.02:gs=0.02:bs=0.06:rh=-0.02:gh=0.0:bh=0.05,"
    "noise=c0s=8:c0f=t,"
    "vignette=PI/5"
)

# HEAVY FILM preset: strong VHS/film look for b-roll only.
# Components (all built-in ffmpeg filters, no external deps):
#   1) VHS softness:  boxblur=2:1 -> unsharp (mild blur + re-sharpen edges)
#   2) Grain:         noise=c0s=18:c0f=t+u (heavy temporal+uniform grain)
#   3) Flicker:       eq with sin(t) brightness modulation
#   4) Scanlines:     drawgrid with thin dark lines every 4px
#   5) Chroma bleed:  rgbashift horizontal red/blue shift
#   6) Halation/glow: handled via split/overlay in build_broll_filtergraph_entries
#   7) Zoom/pan:      zoompan micro push-in, handled in build_broll_filtergraph_entries
#
# The "base" portion is applied as a single linear chain.  Halation (split ->
# gblur -> blend) and zoompan (timing-sensitive) are injected as separate
# filter lines by build_broll_filtergraph_entries when look == HEAVY.
BROLL_HEAVY_FILM_FF_FILTER = (
    # VHS softness: mild blur then re-sharpen
    "boxblur=2:1,"
    "unsharp=5:5:1.2:5:5:0.0,"
    # Color grading: desaturated, crushed blacks, cool tint
    "eq=contrast=1.18:brightness=-0.03:saturation=0.72,"
    "colorbalance=rs=0.03:gs=0.01:bs=0.08:rh=-0.04:gh=-0.01:bh=0.07,"
    # Grain
    "noise=c0s=18:c0f=t+u,"
    # Flicker: subtle brightness oscillation (~3 Hz, small amplitude)
    "eq=brightness=0.015*sin(2*PI*t*3):eval=frame,"
    # Scanlines: thin dark horizontal lines every 4 pixels
    "drawgrid=w=0:h=4:t=1:c=black@0.07,"
    # Chroma bleed: slight horizontal red/blue channel shift
    "rgbashift=rh=-3:bh=3:rv=0:bv=0,"
    # Vignette
    "vignette=PI/4"
)

# DEFAULT FILM preset: the single default look for ALL b-roll clips when the
# user does not specify an explicit look.  Clean color-grade + subtle texture.
BROLL_DEFAULT_FILM_FF_FILTER = (
    "format=yuv420p,"
    "eq=contrast=1.20:saturation=1.03:brightness=0.00:gamma_r=1.00:gamma_g=1.00:gamma_b=1.03,"
    "colorbalance="
    "rs=-0.055:gs=0.010:bs=0.060:"
    "rm=-0.010:gm=0.000:bm=0.012:"
    "rh=0.085:gh=0.020:bh=-0.085,"
    "curves=master=0/0|0.75/0.76|0.90/0.88|1/0.95,"
    "noise=c0s=6:c0f=t+u,"
    "drawgrid=w=0:h=3:t=1:c=black@0.055,"
    "vignette=PI/6"
)

# Texture-only tail of DEFAULT_FILM (noise + drawgrid + vignette).
# Used when composing a Haiku-generated color-grade in front of texture.
_DEFAULT_FILM_TEXTURE = (
    "noise=c0s=4:c0f=t+u,"
    "drawgrid=w=0:h=4:t=1:c=black@0.04,"
    "vignette=PI/6"
)

# Halation sub-filter: applied via split/overlay for HEAVY look.
# Blurs highlights and blends back at low opacity for a glow effect.
_HEAVY_HALATION_BLUR = "gblur=sigma=25"
_HEAVY_HALATION_BLEND_OPACITY = 0.18

# Zoompan micro-motion: subtle push-in (1.00 -> 1.03 over clip duration).
# d=1 means 1 output frame per input frame -> no fps/duration change.
_HEAVY_ZOOMPAN_EXPR = "zoompan=z=min(1.03\\,1+0.001*on):d=1:s=1080x1920"

# HALFTONE uses frei0r — only defined when the filter is available at runtime.
# If frei0r is absent the scheduler falls back to CLEAN or TV.
BROLL_HALFTONE_LOOK_PRESET_FF_FILTER = (
    "eq=contrast=1.06:brightness=0.02:saturation=1.12,"
    "format=gray,eq=contrast=1.25:brightness=0.00,"
    "frei0r=filter_name=halftone:filter_params=0.55|0.70|0.10,"
    "format=rgba,colorchannelmixer=aa=0.85"
)

# Caps per output video
_BROLL_CAP_CLEAN = 0.50
_BROLL_CAP_TV = 0.20
_BROLL_CAP_HEAVY = 0.20
_BROLL_CAP_HALFTONE = 0.10

# Runtime flags: set on first probe (or False if absent)
_frei0r_available: Optional[bool] = None
_heavy_filters_available: Optional[bool] = None


def _probe_frei0r() -> bool:
    """Return True if the runtime ffmpeg supports frei0r filters."""
    global _frei0r_available
    if _frei0r_available is not None:
        return _frei0r_available
    try:
        result = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True, text=True, timeout=5,
        )
        _frei0r_available = "frei0r" in result.stdout
    except Exception:
        _frei0r_available = False
    return _frei0r_available


def _probe_heavy_filters() -> bool:
    """Return True if ffmpeg supports the filters used by the HEAVY preset.

    Checks for: rgbashift, drawgrid, gblur, zoompan, boxblur.
    Falls back to CLEAN if any are missing.
    """
    global _heavy_filters_available
    if _heavy_filters_available is not None:
        return _heavy_filters_available
    try:
        result = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True, text=True, timeout=5,
        )
        needed = ["rgbashift", "drawgrid", "gblur", "zoompan", "boxblur"]
        _heavy_filters_available = all(f in result.stdout for f in needed)
    except Exception:
        _heavy_filters_available = False
    return _heavy_filters_available


def choose_broll_look(
    clip_key: str,
    clip_index: int,
    prev_look: Optional[str],
    total_clips: int,
    counts: dict[str, int],
) -> str:
    """Return the default b-roll look for every clip.

    When no user-specified look is provided, every b-roll clip receives
    the DEFAULT_FILM look (100% uniform, no per-clip variety).
    """
    return "DEFAULT_FILM"


def _broll_filter_for_look(look: str) -> str:
    """Return the FFmpeg filter string for the given b-roll look.

    Known looks resolve to built-in presets.  Unknown look strings are sent
    to Claude Haiku to produce a color-grade subchain that is composed in
    front of the default film texture (noise + drawgrid + vignette).
    """
    if look == "DEFAULT_FILM":
        return BROLL_DEFAULT_FILM_FF_FILTER
    if look == "CLEAN":
        return BROLL_LOOK_PRESET_FF_FILTER
    if look == "TV":
        return BROLL_TV_LOOK_PRESET_FF_FILTER
    if look == "HALFTONE":
        return BROLL_HALFTONE_LOOK_PRESET_FF_FILTER
    if look == "HEAVY":
        return BROLL_HEAVY_FILM_FF_FILTER
    if look.lower() == "none":
        return ""
    # Unknown / custom: attempt Haiku color-grade, compose with texture
    custom_grade = _generate_haiku_color_grade(look)
    if custom_grade:
        return f"format=yuv420p,{custom_grade},{_DEFAULT_FILM_TEXTURE}"
    return BROLL_DEFAULT_FILM_FF_FILTER


def _generate_haiku_color_grade(user_look: str) -> str | None:
    """Call Claude Haiku to generate a color-grade FFmpeg filter subchain.

    Returns only color-grade filters (eq, colorbalance, curves, etc.).
    Does NOT return texture, timing, fps, or setpts filters.
    Returns None on failure (missing SDK, network error, invalid output).
    """
    try:
        import anthropic  # noqa: F811
    except ImportError:
        logger.warning("anthropic SDK not installed; cannot generate custom grade")
        return None

    prompt = (
        "Generate ONLY an FFmpeg color-grade filter subchain for the following look: "
        f'"{user_look}". '
        "Rules:\n"
        "- Use ONLY color-grade filters: eq, colorbalance, curves, colorchannelmixer, hue, lut3d.\n"
        "- Do NOT include: noise, drawgrid, vignette, setpts, fps, format, scale, or any texture/timing filters.\n"
        "- Output ONLY the comma-separated filter chain, nothing else. No explanation.\n"
        "- Example: eq=contrast=1.10:saturation=0.85:brightness=0.02,colorbalance=rs=0.05:bs=-0.03\n"
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-20250414",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        grade = response.content[0].text.strip()
        # Reject if it contains forbidden filters
        forbidden = ["noise", "drawgrid", "vignette", "setpts", "fps=", "format=", "scale="]
        if any(f in grade for f in forbidden):
            logger.warning("Haiku grade contained forbidden filters; discarding: %s", grade)
            return None
        return grade
    except Exception as e:
        logger.warning("Haiku color grade generation failed: %s", e)
        return None


def compose_broll_look_for_user_request(user_look: str) -> str:
    """Resolve a user-requested b-roll look into an FFmpeg filter chain.

    Known looks ('clean', 'tv', 'heavy', 'halftone', 'none') use built-in
    presets.  Unknown looks or directives ('color:', 'grade:', 'warm',
    'kodak', etc.) are sent to Claude Haiku to generate a color-grade
    subchain composed in front of the default film texture.
    """
    _KNOWN: dict[str, str] = {
        "clean": BROLL_LOOK_PRESET_FF_FILTER,
        "tv": BROLL_TV_LOOK_PRESET_FF_FILTER,
        "heavy": BROLL_HEAVY_FILM_FF_FILTER,
        "halftone": BROLL_HALFTONE_LOOK_PRESET_FF_FILTER,
        "none": "",
    }
    normalized = user_look.strip().lower()
    if normalized in _KNOWN:
        return _KNOWN[normalized]
    # Custom: call Haiku for color grade, compose with default texture
    custom_grade = _generate_haiku_color_grade(user_look)
    if custom_grade:
        return f"format=yuv420p,{custom_grade},{_DEFAULT_FILM_TEXTURE}"
    return BROLL_DEFAULT_FILM_FF_FILTER


# ---------------------------------------------------------------------------
# Motion (safe visual-only animation for b-roll + overlay images)
# ---------------------------------------------------------------------------

_FORBIDDEN_MOTION_TOKENS = [
    "setpts", "fps", "tpad", "trim", "atempo", "asetpts", "adelay", "concat",
    "-vsync", "-r",
]

def _motion_seed(*parts: str) -> int:
    h = hashlib.md5("||".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16)

def _pick(seed: int, options: list[str]) -> str:
    return options[seed % len(options)]

def _pick_dir(seed: int) -> str:
    return _pick(seed, ["left", "right", "up", "down"])

def _clamp01_expr(x_expr: str) -> str:
    # NOTE: commas inside expressions must be escaped in filtergraph strings.
    return f"min(max({x_expr}\\,0)\\,1)"

def _validate_motion_fragment(fragment: str, ctx: str) -> None:
    frag = fragment or ""
    if "'" in frag or '"' in frag:
        raise ValueError(f"Quotes in motion fragment ({ctx}): {fragment}")
    lower = frag.lower()
    for tok in _FORBIDDEN_MOTION_TOKENS:
        if tok in lower:
            raise ValueError(f"Forbidden token in motion fragment ({ctx}): {tok} :: {fragment}")

def _default_motion_for_broll(bc: dict) -> dict:
    # Deterministic per clip path + time window (does not change selection or timing)
    path = str(bc.get("path", ""))
    seed = _motion_seed(path, f"{bc.get('start', 0.0):.3f}", f"{bc.get('end', 0.0):.3f}")
    mtype = _pick(seed, ["fade", "micro_push", "slide"])
    return {
        "type": mtype,
        "in_dur": 0.12,
        "out_dur": 0.12,
        "dir": _pick_dir(seed + 17),
        "strength": "subtle",
        "seed": seed,
    }

def _default_motion_for_overlay(oi: dict) -> dict:
    path = str(oi.get("path", ""))
    seed = _motion_seed(path, f"{oi.get('start', 0.0):.3f}", f"{oi.get('end', 0.0):.3f}")
    mtype = _pick(seed, ["fade", "slide", "pop"])
    return {
        "type": mtype,
        "in_dur": float(oi.get("fade_in", 0.12) or 0.12),
        "out_dur": float(oi.get("fade_out", 0.12) or 0.12),
        "dir": _pick_dir(seed + 23),
        "strength": "subtle",
        "seed": seed,
    }

def compile_motion_for_broll(bc: dict, motion_enabled: bool) -> str:
    """
    Returns a FILTER TAIL (begins with ',' or '') to append AFTER the b-roll look filter.
    Must not change timing/duration; visual-only.
    """
    if not motion_enabled:
        return ""

    motion = bc.get("motion") or _default_motion_for_broll(bc)
    mtype = (motion.get("type") or "none").lower()

    start = float(bc["start"])
    end = float(bc["end"])
    dur = max(0.05, end - start)

    in_dur = float(motion.get("in_dur") or 0.12)
    out_dur = float(motion.get("out_dur") or 0.12)
    in_dur = max(0.06, min(0.25, in_dur))
    out_dur = max(0.06, min(0.25, out_dur))

    # t here is the main timeline time because b-roll PTS is offset with setpts to bc['start']/TB
    u = f"((t-{start:.3f})/{dur:.6f})"

    if mtype == "fade":
        # Subtle triangle brightness ramp: 0 at edges, peak mid-clip.
        # Purely visual; does not affect duration.
        # tri = 1 - abs(2*u - 1)
        tri = f"(1-abs(2*{u}-1))"
        tail = f",eq=brightness=0.010*{tri}:eval=frame"
        _validate_motion_fragment(tail, "broll.fade")
        return tail

    if mtype == "micro_push":
        # Push-in via crop-with-zoom, then scale back (duration unchanged).
        # e(t) from 0 -> 0.02 across clip.
        e = f"(0.020*{u})"
        tail = (
            f",crop=w=iw/(1+{e}):h=ih/(1+{e}):x=(iw-w)/2:y=(ih-h)/2"
            f",scale=1080:1920"
        )
        _validate_motion_fragment(tail, "broll.micro_push")
        return tail

    if mtype == "slide":
        # Slide is implemented as a tiny pan within a tiny zoom (to avoid borders).
        # Keep zoom extremely small so it reads as slide, not zoom.
        dirn = (motion.get("dir") or "left").lower()
        e = f"(0.010)"  # constant micro-zoom
        # pan offset in px (within the zoomed frame); keep tiny to avoid nausea
        pan = f"(14*(2*{u}-1))"  # -14..+14
        if dirn in ("left", "right"):
            sign = "-" if dirn == "left" else ""
            x = f"(iw-w)/2+({sign}{pan})"
            y = f"(ih-h)/2"
        else:
            sign = "-" if dirn == "up" else ""
            x = f"(iw-w)/2"
            y = f"(ih-h)/2+({sign}{pan})"
        tail = (
            f",crop=w=iw/(1+{e}):h=ih/(1+{e}):x={x}:y={y}"
            f",scale=1080:1920"
        )
        _validate_motion_fragment(tail, "broll.slide")
        return tail

    return ""

def compile_motion_for_overlay(
    oi: dict,
    motion_enabled: bool,
    start: float,
    end: float,
    x0: int,
    y0: int,
    w_px: int,
) -> tuple[str, str, str]:
    """
    Returns (prep_tail, x_expr, y_expr)
    - prep_tail: appended to overlay prep stream (starts with ',' or '')
    - x_expr/y_expr: passed to overlay x= / y= (NO enable window changes)
    """
    if not motion_enabled:
        return ("", str(x0), str(y0))

    motion = oi.get("motion") or _default_motion_for_overlay(oi)
    mtype = (motion.get("type") or "none").lower()
    in_dur = float(motion.get("in_dur") or 0.12)
    out_dur = float(motion.get("out_dur") or 0.12)
    in_dur = max(0.06, min(0.25, in_dur))
    out_dur = max(0.06, min(0.25, out_dur))

    dur = max(0.05, end - start)

    prep_tail = ""
    x_expr = str(x0)
    y_expr = str(y0)

    if mtype == "fade":
        # Overlay stream time is reset with setpts=PTS-STARTPTS, so t is 0..dur here.
        prep_tail = (
            f",fade=t=in:st=0:d={in_dur:.3f}:alpha=1"
            f",fade=t=out:st={max(0.0, dur - out_dur):.3f}:d={out_dur:.3f}:alpha=1"
        )

    elif mtype == "slide":
        dirn = (motion.get("dir") or "left").lower()
        # progress p from 0..1 during in_dur in main timeline terms
        p = _clamp01_expr(f"(t-{start:.3f})/{in_dur:.6f}")
        # slide offset is relative to overlay width, subtle
        off = f"({w_px}*0.20)"
        if dirn == "left":
            x_expr = f"{x0}+(-{off})*(1-{p})"
            y_expr = f"{y0}"
        elif dirn == "right":
            x_expr = f"{x0}+({off})*(1-{p})"
            y_expr = f"{y0}"
        elif dirn == "up":
            x_expr = f"{x0}"
            y_expr = f"{y0}+(-{off})*(1-{p})"
        else:
            x_expr = f"{x0}"
            y_expr = f"{y0}+({off})*(1-{p})"
        # also do subtle alpha fade (safe)
        prep_tail = (
            f",fade=t=in:st=0:d={in_dur:.3f}:alpha=1"
            f",fade=t=out:st={max(0.0, dur - out_dur):.3f}:d={out_dur:.3f}:alpha=1"
        )

    elif mtype == "pop":
        # Slight scale-up from 0.94->1.00 over in_dur, plus subtle alpha fade.
        # This uses commas inside expressions -> must be escaped in filtergraph string.
        p = _clamp01_expr(f"t/{in_dur:.6f}")
        s = f"(0.94+0.06*{p})"
        prep_tail = (
            f",scale=iw*{s}:ih*{s}:eval=frame"
            f",fade=t=in:st=0:d={in_dur:.3f}:alpha=1"
            f",fade=t=out:st={max(0.0, dur - out_dur):.3f}:d={out_dur:.3f}:alpha=1"
        )

    _validate_motion_fragment(prep_tail, "overlay.prep")
    # x_expr/y_expr go into overlay=, so validate they don’t contain forbidden tokens too
    _validate_motion_fragment(x_expr, "overlay.x")
    _validate_motion_fragment(y_expr, "overlay.y")

    return (prep_tail, x_expr, y_expr)

def build_broll_filtergraph_entries(
    broll_clips: list[dict],
    input_index_start: int,
    last_label: str,
    motion_enabled: bool,
) -> tuple[list[str], str, int]:
    """Build filter_complex entries for b-roll clips with look presets.

    Returns (filter_lines, final_last_label, next_input_index).

    Each b-roll clip gets three labeled stages in the filtergraph:
      [b{i}_raw]  — trim + scale + position
      [b{i}_look] — look preset applied (CLEAN/TV/HALFTONE/HEAVY)
      overlay composited using [b{i}_look] onto the running chain

    This function is intentionally extractable for unit-testing: the
    returned filter lines are exactly what goes into the final
    filter_complex string.
    """
    filters: list[str] = []
    broll_look_counts: dict[str, int] = {}
    prev_broll_look: str | None = None
    total_broll = len(broll_clips)
    input_index = input_index_start

    for idx, bc in enumerate(broll_clips):
        broll_idx = input_index
        input_index += 1

        raw_label = f"b{idx}_raw"
        look_label = f"b{idx}_look"
        out_label = f"b{idx}_out"
        dur = bc["end"] - bc["start"]

        # Choose deterministic look for this clip
        clip_key = bc.get("path", f"broll_{idx}")
        look = choose_broll_look(
            clip_key, idx, prev_broll_look, total_broll, broll_look_counts,
        )
        broll_look_counts[look] = broll_look_counts.get(look, 0) + 1
        prev_broll_look = look
        look_filter = _broll_filter_for_look(look)

        logger.info(
            "B-roll filtergraph wiring: broll_clip=%d look=%s label_in=[%s] label_out=[%s]",
            idx, look.lower(), raw_label, look_label,
        )

        # Stage 1: trim + scale + position -> [b{i}_raw]
        filters.append(
            f"[{broll_idx}:v]trim=duration={dur:.3f},"
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"setpts=PTS-STARTPTS+{bc['start']:.3f}/TB,"
            f"tpad=stop_mode=clone:stop_duration={dur:.3f}[{raw_label}]"
        )
        # Stage 2: apply look preset -> [b{i}_look]
        if look == "HEAVY":
            # HEAVY gets extra stages: halation (split/blur/blend) + zoompan
            graded = f"b{idx}_graded"
            halo_main = f"b{idx}_hmain"
            halo_src = f"b{idx}_hsrc"
            halo_blur = f"b{idx}_hblur"
            glow = f"b{idx}_glow"
            # 2a: base heavy filter chain
            filters.append(f"[{raw_label}]{look_filter}[{graded}]")
            # 2b: halation — split, blur one copy, screen-blend back
            filters.append(f"[{graded}]split[{halo_main}][{halo_src}]")
            filters.append(f"[{halo_src}]{_HEAVY_HALATION_BLUR}[{halo_blur}]")
            filters.append(
                f"[{halo_main}][{halo_blur}]blend="
                f"all_mode=screen:all_opacity={_HEAVY_HALATION_BLEND_OPACITY}[{glow}]"
            )
            # 2c: zoompan micro push-in (preserves duration: d=1)
            motion_tail = compile_motion_for_broll(bc, motion_enabled=motion_enabled)
            filters.append(
                f"[{glow}]{_HEAVY_ZOOMPAN_EXPR},"
                f"setpts=PTS-STARTPTS+{bc['start']:.3f}/TB"
                f"{motion_tail}[{look_label}]"
            )
        else:
            motion_tail = compile_motion_for_broll(bc, motion_enabled=motion_enabled)
            filters.append(
                f"[{raw_label}]{look_filter}{motion_tail}[{look_label}]"
            )
        # Stage 3: composite [b{i}_look] (NOT [b{i}_raw]) onto running chain
        filters.append(
            f"{last_label}[{look_label}]overlay="
            f"enable=between(t\\,{bc['start']:.3f}\\,{bc['end']:.3f})[{out_label}]"
        )
        last_label = f"[{out_label}]"

    return filters, last_label, input_index

def _run_ffmpeg(cmd: list[str], step_name: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run an FFmpeg command with proper error capture.

    Raises RuntimeError with the last ~2k chars of stderr on failure.
    """
    logger.info(f"FFmpeg [{step_name}]: {' '.join(cmd[:6])}...")

    # 🔎 Forensic: log the EXACT filter_complex argument that will be executed
    if "-filter_complex" in cmd:
        i = cmd.index("-filter_complex") + 1
        if i < len(cmd):
            fc_arg = cmd[i]
            tail = fc_arg[-12:] if fc_arg else ""
            logger.info(
                "EXEC fc_arg tail_repr=%r tail_codepoints=%s",
                tail, [ord(c) for c in tail]
            )

    # 🔎 Forensic: log the EXACT filter_complex_script contents that will be executed
    if "-filter_complex_script" in cmd:
        i = cmd.index("-filter_complex_script") + 1
        if i < len(cmd):
            fc_script_path = cmd[i]
            logger.info("EXEC fc_script_path=%r", fc_script_path)
            try:
                txt = Path(fc_script_path).read_text(encoding="utf-8", errors="strict")
                tail = txt[-12:] if txt else ""
                logger.info(
                    "EXEC fc_script tail_repr=%r tail_codepoints=%s",
                    tail, [ord(c) for c in tail]
                )
            except Exception as e:
                logger.warning("Could not read filter_complex_script for forensics: %s", e)

    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        stderr_tail = stderr_text[-_MAX_STDERR_CHARS:] if len(stderr_text) > _MAX_STDERR_CHARS else stderr_text
        logger.error(f"FFmpeg [{step_name}] failed (rc={result.returncode}):\n{stderr_tail}")
        raise RuntimeError(
            f"FFmpeg {step_name} failed: {stderr_tail.strip()[-500:]}"
        )
    return result

def _sanitize_fc(fc: str) -> str:
    if fc is None:
        return ""

    # Normalize and strip ordinary whitespace
    fc = unicodedata.normalize("NFC", fc)
    fc = fc.strip()

    # Remove balanced wrapping quotes
    if (fc.startswith("'") and fc.endswith("'")) or (fc.startswith('"') and fc.endswith('"')):
        fc = fc[1:-1].strip()

    quote_like = {"'", '"', "’", "‘", "“", "”"}
    invisible = {"\u200b", "\u200c", "\u200d", "\ufeff"}  # zero-width + BOM
    line_seps = {"\u2028", "\u2029"}

    # Strip quote-like/invisible chars from BOTH ends repeatedly
    def strip_ends(s: str) -> str:
        while s and (s[0] in quote_like or s[0] in invisible or s[0] in line_seps):
            s = s[1:]
        while s and (s[-1] in quote_like or s[-1] in invisible or s[-1] in line_seps):
            s = s[:-1]
        return s

    fc = strip_ends(fc).strip()

    # Remove ALL control/format chars anywhere (Cc/Cf) and U+2028/U+2029
    cleaned: list[str] = []
    for ch in fc:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf") or ch in line_seps or (cat == "Zs" and ch != " "):
            continue
        cleaned.append(ch)
    fc = "".join(cleaned)

    # Final strip pass
    fc = strip_ends(fc).strip()
    return fc


def _chunk_words_micro(
    words: list[dict],
    max_words: int = 3,
    pause_threshold: float = 0.35,
    end_pad: float = 0.06,
    weighted_random: bool = False,
) -> list[dict]:
    """Group words into micro-chunks of 1–*max_words* words.

    Pause-aware: starts a new chunk when the gap between consecutive
    words exceeds *pause_threshold* seconds.

    When *weighted_random* is True, each chunk target size is chosen
    randomly with weights P(1)=0.65, P(2)=0.25, P(3)=0.10 instead of
    always filling to *max_words*.

    Returns [{start, end, text, words}, ...] where end is optionally padded
    by *end_pad* seconds (40-80ms) to avoid flicker.
    """
    if not words:
        return []

    chunks: list[dict] = []
    buf: list[dict] = []
    # Pick the target size for the current chunk
    target = random.choices([1, 2, 3], weights=[0.65, 0.25, 0.10], k=1)[0] if weighted_random else max_words

    for w in words:
        # Start a new chunk if pause between previous word and this one
        if buf:
            gap = w["start"] - buf[-1]["end"]
            if gap > pause_threshold or len(buf) >= target:
                chunks.append({
                    "start": buf[0]["start"],
                    "end": buf[-1]["end"] + end_pad,
                    "text": " ".join(b["word"] for b in buf),
                    "words": list(buf),
                })
                buf = []
                # Pick a new random target for the next chunk
                target = random.choices([1, 2, 3], weights=[0.65, 0.25, 0.10], k=1)[0] if weighted_random else max_words
        buf.append(w)

    if buf:
        chunks.append({
            "start": buf[0]["start"],
            "end": buf[-1]["end"] + end_pad,
            "text": " ".join(b["word"] for b in buf),
            "words": list(buf),
        })

    return chunks


# Font fallback order for helvetica_punch style (Helvetica-like, Debian-safe)
_HELVETICA_FONT_FALLBACK = ("Liberation Sans", "Nimbus Sans", "DejaVu Sans")


def _pick_helvetica_font() -> str:
    """Return the first available Helvetica-like font name on this system."""
    import shutil

    if shutil.which("fc-list"):
        import subprocess
        try:
            out = subprocess.check_output(
                ["fc-list", "--format", "%{family}\n"],
                timeout=5, text=True,
            )
            families = {f.strip() for f in out.splitlines()}
            for candidate in _HELVETICA_FONT_FALLBACK:
                if candidate in families:
                    return candidate
        except Exception:
            pass

    # Static fallback — Liberation Sans ships with most Debian/Ubuntu images
    return _HELVETICA_FONT_FALLBACK[0]


# ---------------------------------------------------------------------------
# Font resolution map: intent-based alias -> fontconfig family candidates
#
# Prefer the first available family (fc-list). If user asks for a specific
# font name, try it first; if unavailable, fall back to the closest chain.
# NOTE: keys are normalized to lowercase in the resolver (recommended).
# ---------------------------------------------------------------------------

_SANS_CHAIN = ("Google Sans", "Inter", "Roboto Condensed", "Liberation Sans", "DejaVu Sans", "Noto Sans")
_SERIF_CHAIN = ("Playfair Display", "EB Garamond", "DejaVu Serif", "Noto Serif")
_HANDWRITTEN_CHAIN = ("Shadows Into Light", "Comic Neue", "DejaVu Sans", "Noto Sans")
_SCRIPT_CHAIN = ("Pinyon Script", "Comic Neue Italic", "Comic Neue", "DejaVu Sans")
_MONO_CHAIN = ("JetBrains Mono", "DejaVu Sans Mono", "Noto Mono")
_GOTHIC_CHAIN = ("UnifrakturMaguntia", "DejaVu Serif")
_CONDENSED_CHAIN = ("Roboto Condensed", "Google Sans", "Inter", "Liberation Sans", "DejaVu Sans")

_FONT_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    # ---------------------------
    # Sans / helvetica / clean
    # ---------------------------
    "helvetica": _HELVETICA_FONT_FALLBACK,
    "sans": _SANS_CHAIN,
    "clean": _SANS_CHAIN,
    "modern": _SANS_CHAIN,
    "ui": _SANS_CHAIN,
    "default": _SANS_CHAIN,

    "google sans": ("Google Sans", "GoogleSans", "Inter", "Liberation Sans", "DejaVu Sans"),
    "googlesans": ("Google Sans", "GoogleSans", "Inter", "Liberation Sans", "DejaVu Sans"),

    "inter": ("Inter", "Liberation Sans", "DejaVu Sans"),
    "roboto": ("Roboto", "Roboto Condensed", "Inter", "Liberation Sans", "DejaVu Sans"),
    "roboto condensed": ("Roboto Condensed", "Roboto_Condensed", "Inter", "Liberation Sans", "DejaVu Sans"),
    "condensed": _CONDENSED_CHAIN,
    "narrow": _CONDENSED_CHAIN,

    "liberation sans": ("Liberation Sans",),
    "dejavu sans": ("DejaVu Sans",),
    "noto sans": ("Noto Sans", "DejaVu Sans"),

    # ---------------------------
    # Serif / editorial / fancy
    # ---------------------------
    "serif": _SERIF_CHAIN,
    "classic": _SERIF_CHAIN,
    "editorial": _SERIF_CHAIN,
    "fancy": _SERIF_CHAIN,

    "playfair": ("Playfair Display", "PlayfairDisplay", "EB Garamond", "EBGaramond", "DejaVu Serif"),
    "playfair display": ("Playfair Display", "PlayfairDisplay", "EB Garamond", "EBGaramond", "DejaVu Serif"),
    "playfair display italic": ("Playfair Display", "PlayfairDisplay", "EB Garamond", "EBGaramond", "DejaVu Serif"),

    "garamond": ("EB Garamond", "EBGaramond", "DejaVu Serif", "Noto Serif"),
    "eb garamond": ("EB Garamond", "EBGaramond", "DejaVu Serif", "Noto Serif"),

    "dejavu serif": ("DejaVu Serif",),
    "liberation serif": ("Liberation Serif", "DejaVu Serif"),
    "noto serif": ("Noto Serif", "DejaVu Serif"),

    # ---------------------------
    # Handwritten / script vibes
    # ---------------------------
    "handwritten": _HANDWRITTEN_CHAIN,
    "casual": _HANDWRITTEN_CHAIN,

    "comic": ("Comic Neue", "ComicNeue", "DejaVu Sans"),
    "comic neue": ("Comic Neue", "ComicNeue", "DejaVu Sans"),

    "shadows": ("Shadows Into Light", "ShadowsIntoLight", "Comic Neue", "DejaVu Sans"),
    "shadows into light": ("Shadows Into Light", "ShadowsIntoLight", "Comic Neue", "DejaVu Sans"),

    "script": _SCRIPT_CHAIN,
    "cursive": _SCRIPT_CHAIN,

    "pinyon": ("Pinyon Script", "PinyonScript", "Comic Neue Italic", "Comic Neue", "DejaVu Sans"),
    "pinyon script": ("Pinyon Script", "PinyonScript", "Comic Neue Italic", "Comic Neue", "DejaVu Sans"),

    # ---------------------------
    # Mono / code / terminal
    # ---------------------------
    "mono": _MONO_CHAIN,
    "code": _MONO_CHAIN,
    "terminal": _MONO_CHAIN,

    "jetbrains mono": ("JetBrains Mono", "JetBrainsMono", "DejaVu Sans Mono", "Noto Mono"),
    "jetbrainsmono": ("JetBrains Mono", "JetBrainsMono", "DejaVu Sans Mono", "Noto Mono"),

    "dejavu sans mono": ("DejaVu Sans Mono",),
    "noto mono": ("Noto Mono", "DejaVu Sans Mono"),

    # ---------------------------
    # Gothic / blackletter
    # ---------------------------
    "gothic": _GOTHIC_CHAIN,
    "blackletter": _GOTHIC_CHAIN,
    "unifraktur": ("UnifrakturMaguntia", "DejaVu Serif"),
    "unifrakturmaguntia": ("UnifrakturMaguntia", "DejaVu Serif"),

    # ---------------------------
    # Emoji
    # ---------------------------
    "emoji": ("Noto Color Emoji",),
    "noto color emoji": ("Noto Color Emoji",),
}

def _resolve_font(name: str | None) -> str | None:
    """Resolve a user-friendly font name to an installed fontconfig family.

    Returns ``None`` when *name* is ``None`` (caller uses preset default).
    Never crashes — always falls back to a safe font.
    """
    if not name:
        return None

    key = name.strip().lower()

    # Check alias map first
    candidates = _FONT_ALIAS_MAP.get(key)
    if candidates is None:
        # Try exact name, then fall through to alias values
        candidates = (name.strip(),) + _HELVETICA_FONT_FALLBACK

    # Probe via fc-list if available
    import shutil
    if shutil.which("fc-list"):
        try:
            out = subprocess.check_output(
                ["fc-list", "--format", "%{family}\n"],
                timeout=5, text=True,
            )
            families = {f.strip() for f in out.splitlines()}
            for c in candidates:
                if c in families:
                    return c
        except Exception:
            pass

    # Return the first candidate as best-effort
    return candidates[0]


_HEX_COLOR_RE = _re.compile(r"^#[0-9A-Fa-f]{6}$")

# Named color map — lowercased keys
_NAMED_COLORS: dict[str, str] = {
    "red": "#FF0000",
    "orange": "#FF8800",
    "blue": "#0066FF",
    "green": "#00CC00",
    "yellow": "#FFCC00",
    "white": "#FFFFFF",
    "black": "#000000",
    "pink": "#FF69B4",
    "cyan": "#00FFFF",
    "purple": "#9900FF",
}


def _normalize_color(color: str | None) -> str | None:
    """Normalise a color value to ``#RRGGBB``.

    Accepts ``#RRGGBB`` hex or a named color (case-insensitive).
    Returns ``None`` on unrecognised input so callers can fall back.
    """
    if not color:
        return None
    color = color.strip()
    if _HEX_COLOR_RE.match(color):
        return color
    named = _NAMED_COLORS.get(color.lower())
    return named  # None if not found


def _hex_to_ass_color(hex_color: str | None, default: str = "&H00FFFFFF") -> str:
    """Convert ``#RRGGBB`` (or named color) to ASS ``&H00BBGGRR``.

    Returns *default* on bad / unrecognised input.
    """
    normalized = _normalize_color(hex_color)
    if normalized is None:
        return default
    r, g, b = normalized[1:3], normalized[3:5], normalized[5:7]
    return f"&H00{b.upper()}{g.upper()}{r.upper()}"


def _clamp(val: int | float | None, lo: int | float, hi: int | float, default: int | float) -> int | float:
    """Clamp *val* to [lo, hi], returning *default* when val is None."""
    if val is None:
        return default
    return max(lo, min(hi, val))


def _apply_caption_style(style: dict, caption_style) -> dict:
    """Apply ``CaptionStyle`` overrides onto a mutable *style* preset dict.

    Only fields that are not ``None`` in *caption_style* override the preset.
    Returns the same dict (mutated in place).
    """
    if caption_style is None:
        return style

    # Font
    resolved_primary = _resolve_font(caption_style.font_primary)
    if resolved_primary:
        style["fontname"] = resolved_primary

    # Size
    if caption_style.size is not None:
        style["fontsize"] = int(_clamp(caption_style.size, 24, 96, style["fontsize"]))

    # Bold / italic
    if caption_style.bold is not None:
        style["bold"] = 1 if caption_style.bold else 0
    if caption_style.italic is not None:
        style["italic"] = 1 if caption_style.italic else 0

    # Colors (stored for ASS header generation)
    if caption_style.color is not None:
        style["_primary_colour"] = _hex_to_ass_color(caption_style.color)
    if caption_style.outline_color is not None:
        style["_outline_colour"] = _hex_to_ass_color(caption_style.outline_color, "&H00000000")

    # Outline / shadow
    if caption_style.outline_width is not None:
        style["outline"] = int(_clamp(caption_style.outline_width, 0, 10, style["outline"]))
    if caption_style.shadow_depth is not None:
        style["shadow"] = int(_clamp(caption_style.shadow_depth, 0, 10, style["shadow"]))

    # Tracking (letter spacing)
    if caption_style.tracking is not None:
        style["spacing"] = int(_clamp(caption_style.tracking, -8, 8, style["spacing"]))

    # Position
    if caption_style.y is not None:
        style["_y_override"] = int(_clamp(caption_style.y, 600, 1700, 960))
    if caption_style.align is not None:
        align = int(caption_style.align)
        style["_align_override"] = align if 1 <= align <= 9 else 5

    return style


def generate_ass_subtitles(
    transcript: dict,
    edit_plan: EditPlan,
    output_path: str,
) -> str:
    """Generate ASS subtitle file from transcript aligned to the edit plan timeline."""
    caption_cfg = edit_plan.captions
    if not caption_cfg.enabled:
        return ""

    # Map original timestamps to final timeline timestamps
    timeline_map = _build_timeline_map(edit_plan)

    # --- style presets ---------------------------------------------------
    style_presets = {
        "snappy": {"fontname": _pick_helvetica_font(), "fontsize": 58, "outline": 0, "shadow": 0, "bold": 1, "margin_v": 346, "spacing": -4},
        "cinematic": {"fontname": "Inter", "fontsize": 48, "outline": 2, "shadow": 3, "bold": 0, "margin_v": 180, "spacing": 0},
        "podcast": {"fontname": "Inter", "fontsize": 52, "outline": 2, "shadow": 1, "bold": 0, "margin_v": 180, "spacing": 0},
        "luxury": {"fontname": "Inter", "fontsize": 44, "outline": 1, "shadow": 2, "bold": 0, "margin_v": 180, "spacing": 0},
        "study": {"fontname": "Inter", "fontsize": 50, "outline": 2, "shadow": 1, "bold": 0, "margin_v": 180, "spacing": 0},
        "default": {"fontname": "Inter", "fontsize": 52, "outline": 2, "shadow": 2, "bold": 0, "margin_v": 180, "spacing": 0},
        "helvetica_punch": {
            "fontname": _pick_helvetica_font(),
            "fontsize": 64,
            "outline": 0,
            "shadow": 0,
            "bold": 1,
            "margin_v": 500,   # ~18% of 1920 → lower-middle center
            "spacing": -3,
        },
    }
    # helvetica_punch is THE default caption style — use it for "default" and
    # any unrecognised style_id so captions always get the Liberation-Sans /
    # micro-chunk / fixed-position look unless the user explicitly picks
    # a different named style (cinematic, podcast, luxury, study).
    _effective_style_id = caption_cfg.style_id
    if _effective_style_id == "default":
        _effective_style_id = "helvetica_punch"
    style = style_presets.get(_effective_style_id, style_presets["helvetica_punch"])
    is_fixed_pos_style = _effective_style_id in ("helvetica_punch", "snappy")

    # --- apply user-driven style overrides (helvetica_punch / snappy only) -
    caption_style = caption_cfg.style
    if is_fixed_pos_style and caption_style is not None:
        _apply_caption_style(style, caption_style)

    # Resolve colours for ASS header
    # Part 5 color logic:
    #   - karaoke + color => PrimaryColour=white (unless base color set), SecondaryColour=karaoke.color
    #   - color only (no karaoke) => PrimaryColour=that color, SecondaryColour matches
    #   - no color => white, no karaoke
    karaoke_enabled = (
        caption_style is not None
        and caption_style.karaoke is not None
        and caption_style.karaoke.enabled is True
    ) if caption_style else False

    primary_colour = style.get("_primary_colour", "&H00FFFFFF")
    if karaoke_enabled and caption_style and caption_style.karaoke:
        # Karaoke ON: SecondaryColour = highlight color; PrimaryColour stays
        # as-is (white unless user explicitly set base color via style.color)
        secondary_colour = _hex_to_ass_color(
            caption_style.karaoke.color, "&H000000FF",
        )
    else:
        # No karaoke: SecondaryColour matches PrimaryColour (no highlighting)
        secondary_colour = primary_colour
    outline_colour = style.get("_outline_colour", "&H00000000")
    italic = style.get("italic", 0)

    ass_content = f"""[Script Info]
Title: Compose Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['fontname']},{style['fontsize']},{primary_colour},{secondary_colour},{outline_colour},&H80000000,{style['bold']},{italic},0,0,100,100,{style['spacing']},0,1,{style['outline']},{style['shadow']},2,40,40,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Collect all word-level timestamps
    all_words = []
    for seg in transcript.get("segments", []):
        for word in seg.get("words", []):
            all_words.append(word)

    if not all_words:
        # Fallback: use segment-level timing
        for seg in transcript.get("segments", []):
            mapped_start = _map_time(seg["start"], timeline_map)
            mapped_end = _map_time(seg["end"], timeline_map)
            if mapped_start is not None and mapped_end is not None:
                start_str = _format_ass_time(mapped_start)
                end_str = _format_ass_time(mapped_end)
                text = seg["text"].replace("\n", "\\N")
                ass_content += f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}\n"
        Path(output_path).write_text(ass_content)
        return output_path

    # --- micro-chunk path for helvetica_punch & snappy --------------------
    _Y_DEFAULT = 1180  # lower-middle center (original helvetica_punch position)
    _Y_FIXED = style.get("_y_override", _Y_DEFAULT)
    _ALIGN = style.get("_align_override", 5)

    # --- invert / negative caption flags ------------------------------------
    invert_enabled = (
        caption_style is not None
        and caption_style.invert is True
    )
    invert_scope = "all"  # default
    if invert_enabled and caption_style and caption_style.invert_scope in ("all", "emphasis"):
        invert_scope = caption_style.invert_scope

    if is_fixed_pos_style:
        micro = _chunk_words_micro(all_words, max_words=3, weighted_random=True)

        # --- emphasis font heuristic (Part 4) --------------------------------
        emphasis_font: str | None = None
        emphasis_threshold: float = 0.4  # default pause gap in seconds
        emphasis_enabled = False
        if caption_style is not None:
            # Auto-enable emphasis when font_emphasis is set, even if
            # pause_emphasis was not explicitly configured by the planner.
            # But respect an explicit pause_emphasis.enabled=False opt-out.
            has_explicit_pe = (
                caption_style.pause_emphasis is not None
                and caption_style.pause_emphasis.enabled is True
            )
            pe_explicitly_disabled = (
                caption_style.pause_emphasis is not None
                and caption_style.pause_emphasis.enabled is False
            )
            has_emphasis_font = bool(caption_style.font_emphasis)
            if has_explicit_pe or (has_emphasis_font and not pe_explicitly_disabled):
                emphasis_enabled = True
                if caption_style.pause_emphasis is not None and caption_style.pause_emphasis.threshold_sec is not None:
                    emphasis_threshold = max(0.1, min(2.0, caption_style.pause_emphasis.threshold_sec))
                emphasis_font = _resolve_font(
                    caption_style.font_emphasis if caption_style.font_emphasis else None,
                )
                if emphasis_font is None:
                    emphasis_font = style["fontname"]  # same as primary
        primary_font = style["fontname"]
        base_fontsize = style["fontsize"]
        emphasis_applied = 0  # count of chunks where emphasis was applied

        # --- emphasis size multiplier (3C) ------------------------------------
        EMPHASIS_SIZE_MULT_DEFAULT = 1.12
        _SERIF_SCRIPT_HINTS = {
            "playfair display", "playfairdisplay", "eb garamond", "ebgaramond",
            "dejavu serif", "noto serif", "liberation serif",
            "pinyon script", "pinyonscript",
        }
        emph_size_mult = 1.0  # no bump unless serif/script
        if emphasis_enabled and emphasis_font:
            if caption_style and caption_style.emphasis_size_multiplier is not None:
                emph_size_mult = max(1.0, min(1.35, caption_style.emphasis_size_multiplier))
            elif emphasis_font.lower() in _SERIF_SCRIPT_HINTS:
                emph_size_mult = EMPHASIS_SIZE_MULT_DEFAULT
        emph_fontsize = round(base_fontsize * emph_size_mult)

        # Collect invert dialogue lines alongside main content
        invert_dialogues: list[str] = []

        pos_count = 0
        for ch in micro:
            chunk_words = ch["words"]
            chunk_start = chunk_words[0]["start"]
            chunk_end = chunk_words[-1]["end"]
            mapped_start = _map_time(chunk_start, timeline_map)
            mapped_end = _map_time(chunk_end, timeline_map)
            if mapped_start is None or mapped_end is None:
                continue
            # Small safety pad (max 20ms)
            mapped_end += 0.02
            start_str = _format_ass_time(mapped_start)
            end_str = _format_ass_time(mapped_end)

            plain_text = " ".join(w["word"].strip() for w in chunk_words)
            plain_text = plain_text.replace("\\N", " ").replace("\n", " ")

            # --- emphasis wrapping decision ----------------------------------
            apply_emph = False
            if emphasis_enabled and emphasis_font and len(chunk_words) >= 1:
                # Pause-based: check gap to next chunk's first word
                chunk_idx = micro.index(ch)
                if chunk_idx + 1 < len(micro):
                    next_first = micro[chunk_idx + 1]["words"][0]
                    gap = next_first["start"] - chunk_end
                    if gap >= emphasis_threshold:
                        apply_emph = True
                # Fallback: every 8th chunk (1-indexed, so 8th, 16th, …)
                if not apply_emph and (pos_count + 1) % 8 == 0:
                    apply_emph = True

            # --- build emphasis size tags (only when multiplier > 1) ---------
            _emph_open = f"{{\\fs{emph_fontsize}\\fn{emphasis_font}}}" if emph_size_mult > 1.0 else f"{{\\fn{emphasis_font}}}"
            _emph_close = f"{{\\fs{base_fontsize}\\fn{primary_font}}}" if emph_size_mult > 1.0 else f"{{\\fn{primary_font}}}"

            if karaoke_enabled:
                # Build karaoke-tagged text with per-word timing
                karaoke_parts = []
                for i, w in enumerate(chunk_words):
                    cleaned = w["word"].strip()
                    start_i = w["start"]
                    if i + 1 < len(chunk_words):
                        start_next = chunk_words[i + 1]["start"]
                    else:
                        start_next = chunk_end
                    dur = max(0.01, min(5.0, start_next - start_i))
                    cs = max(1, int(round(dur * 100)))
                    # Emphasis on last word of chunk
                    if apply_emph and i == len(chunk_words) - 1:
                        karaoke_parts.append(
                            f"{{\\kf{cs}}}{_emph_open}{cleaned}{_emph_close}"
                        )
                    else:
                        karaoke_parts.append(f"{{\\kf{cs}}}{cleaned}")
                text = f"{{\\an{_ALIGN}\\pos(540,{_Y_FIXED})}}" + " ".join(karaoke_parts)
            else:
                if apply_emph and len(chunk_words) >= 1:
                    # Wrap last word with emphasis font + size
                    word_parts = [w["word"].strip() for w in chunk_words]
                    last = word_parts[-1]
                    word_parts[-1] = f"{_emph_open}{last}{_emph_close}"
                    emph_text = " ".join(word_parts)
                    emph_text = emph_text.replace("\\N", " ").replace("\n", " ")
                    text = f"{{\\an{_ALIGN}\\pos(540,{_Y_FIXED})}}{emph_text}"
                else:
                    text = f"{{\\an{_ALIGN}\\pos(540,{_Y_FIXED})}}{plain_text}"

            if apply_emph:
                emphasis_applied += 1

            ass_content += f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}\n"

            # --- invert dialogue collection ----------------------------------
            if invert_enabled:
                inv_pos = f"{{\\an{_ALIGN}\\pos(540,{_Y_FIXED})}}"
                if invert_scope == "all":
                    # White-only, no karaoke, no emphasis font, no size changes
                    invert_dialogues.append(
                        f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{inv_pos}{plain_text}\n"
                    )
                elif invert_scope == "emphasis" and apply_emph:
                    # Only the emphasized word(s), white-only
                    last_word = chunk_words[-1]["word"].strip()
                    invert_dialogues.append(
                        f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{inv_pos}{last_word}\n"
                    )

            pos_count += 1

        Path(output_path).write_text(ass_content)

        # --- write captions_invert.ass when invert is enabled ----------------
        if invert_enabled and invert_dialogues:
            inv_ass = f"""[Script Info]
Title: Compose Captions (Invert Mask)
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['fontname']},{style['fontsize']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{style['bold']},0,0,0,100,100,{style['spacing']},0,1,0,0,2,40,40,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
            inv_ass += "".join(invert_dialogues)
            inv_path = output_path.replace("captions.ass", "captions_invert.ass")
            Path(inv_path).write_text(inv_ass)
            logger.info(
                "ASS invert mask: scope=%s lines=%d path=%s",
                invert_scope, len(invert_dialogues), inv_path,
            )

        logger.info(
            "ASS captions: style_id=%s font=%s size=%d tracking=%d y=%d "
            "karaoke=%s emphasis_font=%s emphasis_applied=%d lines=%d",
            caption_cfg.style_id, style["fontname"], style["fontsize"],
            style["spacing"], _Y_FIXED, karaoke_enabled,
            emphasis_font or "none", emphasis_applied, pos_count,
        )
        return output_path

    # --- standard chunking path (unchanged) ------------------------------
    max_words = caption_cfg.max_words_per_line * caption_cfg.max_lines
    chunks = []
    current_chunk = []

    for word in all_words:
        current_chunk.append(word)
        if len(current_chunk) >= max_words:
            chunks.append(current_chunk)
            current_chunk = []
    if current_chunk:
        chunks.append(current_chunk)

    for chunk in chunks:
        orig_start = chunk[0]["start"]
        orig_end = chunk[-1]["end"]
        mapped_start = _map_time(orig_start, timeline_map)
        mapped_end = _map_time(orig_end, timeline_map)

        if mapped_start is None or mapped_end is None:
            continue

        # Build text with line breaks
        words_text = [w["word"] for w in chunk]
        lines = []
        line_words = []
        for wt in words_text:
            line_words.append(wt)
            if len(line_words) >= caption_cfg.max_words_per_line:
                lines.append(" ".join(line_words))
                line_words = []
        if line_words:
            lines.append(" ".join(line_words))

        text = "\\N".join(lines[:caption_cfg.max_lines])
        start_str = _format_ass_time(mapped_start)
        end_str = _format_ass_time(mapped_end)
        ass_content += f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}\n"

    Path(output_path).write_text(ass_content)
    logger.info(f"ASS subtitles generated: {len(chunks)} chunks -> {output_path}")
    return output_path

def _build_timeline_map(edit_plan: EditPlan) -> list[dict]:
    """Build a mapping from original video time to final timeline time."""
    timeline = []
    offset = 0.0
    for cut in edit_plan.main_cuts:
        timeline.append({
            "orig_start": cut.start,
            "orig_end": cut.end,
            "final_start": offset,
            "final_end": offset + (cut.end - cut.start),
        })
        offset += cut.end - cut.start
    return timeline

def _map_time(orig_time: float, timeline_map: list[dict]) -> float | None:
    """Map an original video timestamp to the final timeline."""
    for entry in timeline_map:
        if entry["orig_start"] <= orig_time <= entry["orig_end"]:
            offset_in_cut = orig_time - entry["orig_start"]
            return entry["final_start"] + offset_in_cut
    return None

def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp (H:MM:SS.CC)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def compile_render(
    edit_plan: EditPlan,
    source_video: str,
    transcript: dict,
    output_path: str,
    work_dir: str | None = None,
) -> str:
    """Compile and execute the FFmpeg render pipeline.

    Returns the path to the output video.
    """
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="compose_render_")
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting render: {len(edit_plan.main_cuts)} cuts, output -> {output_path}")

    # Aspect handling:
    # - "fit": preserve aspect ratio and pad (no stretch, no crop) ✅ default
    # - "fill": preserve aspect ratio and crop to fill 9:16 (no stretch, but crops edges)
    fit_mode = "fit"  # later wire this to UI/preset

    if fit_mode == "fill":
        vf_base = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    else:
        vf_base = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"

    # Step 1: Cut and concatenate main segments
    segments_list_path = work / "segments.txt"
    segment_paths = []
    failed_segments = []

    for i, cut in enumerate(edit_plan.main_cuts):
        seg_path = work / f"seg_{i:03d}.mp4"
        duration = cut.end - cut.start

        # Check if this segment needs punch-in
        punch_in = None
        for pi in edit_plan.punch_ins:
            if pi.start >= cut.start and pi.end <= cut.end:
                punch_in = pi
                break

        if punch_in:
            scale = punch_in.scale

            if fit_mode == "fill":
                vf = (
                    "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,"
                    f"zoompan=z={scale}:d=1:s=1080x1920"
                )
            else:
                vf = (
                    "scale=1080:1920:force_original_aspect_ratio=decrease,"
                    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                    f"zoompan=z={scale}:d=1:s=1080x1920"
                )

            cmd = [
                "ffmpeg", "-y",
                "-i", source_video,
                "-ss", str(cut.start), "-t", str(duration),
                "-vf", f"{vf_base},scale=iw*{scale}:ih*{scale},crop=1080:1920",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "2",
                "-c:a", "copy",
                str(seg_path),
            ]
        else:
            # Simple trim - ensure 9:16 output
            cmd = [
                "ffmpeg", "-y",
                "-i", source_video,
                "-ss", str(cut.start), "-t", str(duration),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "2",
                "-c:a", "copy",
                str(seg_path),
            ]

        logger.info(f"Cutting segment {i}: {cut.start:.2f}-{cut.end:.2f}")
        try:
            _run_ffmpeg(cmd, f"segment-{i}", timeout=180)
            if seg_path.exists() and seg_path.stat().st_size > 0:
                segment_paths.append(seg_path)
            else:
                failed_segments.append(i)
                logger.warning(f"Segment {i} produced empty output")
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            failed_segments.append(i)
            logger.warning(f"Segment {i} cut failed (non-fatal, skipping): {e}")

    if not segment_paths:
        raise RuntimeError(
            f"No segments created successfully ({len(failed_segments)} failed). "
            f"The source video may be corrupted or in an unsupported format."
        )

    if failed_segments:
        logger.warning(f"{len(failed_segments)} of {len(edit_plan.main_cuts)} segments failed: {failed_segments}")

    # Step 2: Handle b-roll inserts
    broll_segments = {}
    if edit_plan.broll.enabled and edit_plan.broll.inserts:
        for bi in edit_plan.broll.inserts:
            if bi.asset_path and Path(bi.asset_path).exists():
                broll_segments[bi.start] = {
                    "path": bi.asset_path,
                    "start": bi.start,
                    "end": bi.end,
                }

    # Step 2.5: Collect overlay image assets (AI / pexels) for rendering
    overlay_items = []
    if edit_plan.overlays.enabled and edit_plan.overlays.items:
        for oi in edit_plan.overlays.items:
            asset_path = getattr(oi, "asset_path", None)
            if asset_path and Path(asset_path).exists():
                overlay_items.append({
                    "path": asset_path,
                    "start": float(oi.start),
                    "end": float(oi.end),
                    "x": float(oi.placement.x),
                    "y": float(oi.placement.y),
                    "w": float(oi.placement.w),
                    "fade_in": float(getattr(oi.animation, "fade_in", 0.12)),
                    "fade_out": float(getattr(oi.animation, "fade_out", 0.12)),
                })

    # Sort overlays by time (important for deterministic filter chain)
    overlay_items = sorted(overlay_items, key=lambda o: o["start"])

    logger.info(
        f"Render assets: broll={len(broll_segments)} overlays={len(overlay_items)} "
        f"(enabled={edit_plan.overlays.enabled if hasattr(edit_plan, 'overlays') else False})"
    )
    for i, o in enumerate(overlay_items[:8]):
        logger.info(
            f"Overlay[{i}] start={o['start']:.3f} end={o['end']:.3f} "
            f"w={o['w']:.2f} x={o['x']:.2f} y={o['y']:.2f} path={o['path']} "
            f"exists={Path(o['path']).exists()}"
        )

    # Step 3: Build concat list
    with open(segments_list_path, "w") as f:
        for sp in segment_paths:
            f.write(f"file '{sp}'\n")

    concat_path = work / "concat.mp4"
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(segments_list_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-threads", "2",
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "aac", "-b:a", "160k",
            str(concat_path),
        ],
        "concat",
        timeout=180,
    )

    # Step 4: Overlay b-roll + overlay images + burn captions (single pass when possible)
    current_video = str(concat_path)

    # Collect valid b-roll clips sorted by start time
    broll_clips = sorted(broll_segments.values(), key=lambda b: b["start"]) if broll_segments else []

    has_captions = False
    ass_path = str(work / "captions.ass")
    inv_ass_path = str(work / "captions_invert.ass")
    has_invert_captions = False
    if edit_plan.captions.enabled:
        generate_ass_subtitles(transcript, edit_plan, ass_path)
        has_captions = Path(ass_path).exists() and Path(ass_path).stat().st_size > 100
        has_invert_captions = Path(inv_ass_path).exists() and Path(inv_ass_path).stat().st_size > 100

    # If we have ANY visual layers to apply, do one filter_complex pass
    if broll_clips or overlay_items or has_captions:
        layered_path = work / "layered.mp4"
        motion_enabled = True

        # Total output duration (sum of all main_cuts) — used to bound
        # the black canvas for invert-blend so FFmpeg doesn't hang.
        _total_dur = sum(c.end - c.start for c in edit_plan.main_cuts)

        # Inputs: base video first, then b-roll, then overlay images
        inputs = ["-i", current_video]
        for bc in broll_clips:
            inputs.extend(["-i", bc["path"]])
        for oi in overlay_items:
            inputs.extend(["-i", oi["path"]])

        filters = []

        # ✅ IMPORTANT: normalize base video timeline so t starts at 0
        filters.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label = "[base]"

        input_index = 1  # 0 is base; b-roll start at 1

        # ---- B-ROLL FULLSCREEN CUTAWAYS ----
        broll_filters, last_label, input_index = build_broll_filtergraph_entries(
            broll_clips,
            input_index,
            last_label,
            motion_enabled=motion_enabled,
        )
        filters.extend(broll_filters)

        # ---- OVERLAY IMAGES (corner pops etc) ----
        # Each overlay image is scaled to a fraction of width (w), placed at (x,y)
        # and enabled only between (start,end).
        for j, oi in enumerate(overlay_items):
            ov_idx = input_index
            input_index += 1

            out = f"vo{j}"

            # Convert normalized coords to pixels
            w_px = max(1, int(1080 * oi["w"]))
            x_px = int(1080 * oi["x"])
            y_px = int(1920 * oi["y"])

            dur = max(0.05, oi["end"] - oi["start"])

            # Prepare overlay stream: scale, ensure alpha, reset pts
            prep = f"ov{j}"

            # Motion compilation (prep tail + animated x/y). DOES NOT change enable window.
            prep_tail, x_expr, y_expr = compile_motion_for_overlay(
                oi=oi,
                motion_enabled=motion_enabled,
                start=float(oi["start"]),
                end=float(oi["end"]),
                x0=x_px,
                y0=y_px,
                w_px=w_px,
            )

            filters.append(
                f"[{ov_idx}:v]scale={w_px}:-1,format=rgba,"
                f"setpts=PTS-STARTPTS{prep_tail}[{prep}]"
            )

            filters.append(
                f"{last_label}[{prep}]overlay="
                f"x={x_expr}:y={y_expr}:"
                f"enable=between(t\\,{oi['start']:.3f}\\,{oi['end']:.3f})[{out}]"
            )
            last_label = f"[{out}]"

        # ---- CAPTIONS (ASS burn) ----
        if has_captions:
            _caption_style = edit_plan.captions.style
            _invert_on = (
                has_invert_captions
                and _caption_style is not None
                and _caption_style.invert is True
            )
            _inv_scope = (
                _caption_style.invert_scope
                if _invert_on and _caption_style and _caption_style.invert_scope in ("all", "emphasis")
                else "all"
            )

            if _invert_on:
                # Generate black canvas, burn invert-mask ASS, blend with difference
                filters.append(
                    f"color=black:s=1080x1920:r=30:d={_total_dur:.3f}[_inv_black]"
                )
                filters.append(
                    f"[_inv_black]ass={inv_ass_path}:fontsdir=/usr/share/fonts[_inv_text]"
                )
                inv_blend_out = "_inv_blended"
                filters.append(
                    f"{last_label}[_inv_text]blend=all_mode=difference:shortest=1[{inv_blend_out}]"
                )
                last_label = f"[{inv_blend_out}]"

                if _inv_scope == "emphasis":
                    # Emphasis-only invert: also apply normal captions on top
                    cap_out = "vcap"
                    filters.append(
                        f"{last_label}ass={ass_path}:fontsdir=/usr/share/fonts[{cap_out}]"
                    )
                    last_label = f"[{cap_out}]"
                # scope="all": normal captions NOT applied (difference blend replaces them)
            else:
                cap_out = "vcap"
                filters.append(f"{last_label}ass={ass_path}:fontsdir=/usr/share/fonts[{cap_out}]")
                last_label = f"[{cap_out}]"

        map_v = last_label if str(last_label).startswith("[") else f"[{last_label}]"

        fc = ";".join(filters) if filters else "null"
        fc = _sanitize_fc(fc)

        weird = _find_weird_chars(fc)
        if weird:
            for i, ch, o, cat in weird[:8]:
                ctx = fc[max(0, i - 20): i + 20]
                logger.error("WEIRD_CHAR idx=%d ord=%d cat=%s repr=%r ctx=%r", i, o, cat, ch, ctx)
            raise RuntimeError(f"filter_complex contains {len(weird)} control/format chars; refusing to run")

        logger.info("filter_complex last300=%r", fc[-300:])
        logger.info("filter_complex tail_codepoints=%s", [ord(c) for c in fc[-40:]])
        logger.info("filter_complex len=%d head=%r tail=%r", len(fc), fc[:200], fc[-200:])

        # Write filtergraph for debugging / forensics, then pass via -filter_complex (no script option)
        fc_path = work / "filter_complex.txt"
        fc_path.write_text(fc, encoding="utf-8", errors="strict")

        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex_threads", "1",
            "-filter_complex", fc,
            "-map", map_v, "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-threads", "2",
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "aac", "-b:a", "160k",
            str(layered_path),
        ]

        logger.info(
            f"Layer pass: broll={len(broll_clips)} overlays={len(overlay_items)} captions={has_captions}"
        )
        try:
            _run_ffmpeg(cmd, "layer-broll-overlays-captions", timeout=MAX_RENDER_TIMEOUT_SEC)
            current_video = str(layered_path)
        except RuntimeError as e:
            logger.error(
                "MOTION PASS FAILED (path=motion) — fc len=%d tail_repr=%s",
                len(fc), repr(fc[-600:]),
            )
            logger.error("MOTION PASS FAILED — output will have NO MOTION unless fixed. Error: %s", e)
            logger.warning("Retrying layer pass with ALL motion disabled (keeping b-roll + overlays + same enable windows).")

            # Rebuild filter graph with motion disabled by stripping motion tails:
            # - b-roll: no motion (compile_motion_for_broll returns "")
            # - overlays: no prep_tail, fixed x/y
            filters_retry = []

            # ✅ IMPORTANT: normalize base video timeline (same as motion path)
            filters_retry.append("[0:v]setpts=PTS-STARTPTS[base]")
            last_label_retry = "[base]"
            input_index_retry = 1

            # ---- B-ROLL FULLSCREEN CUTAWAYS (NO MOTION) ----
            for idx, bc in enumerate(broll_clips):
                broll_idx = input_index_retry
                input_index_retry += 1

                raw_label = f"b{idx}_raw"
                look_label = f"b{idx}_look"
                out_label = f"b{idx}_out"
                dur_clip = bc["end"] - bc["start"]

                clip_key = bc.get("path", f"broll_{idx}")
                look = choose_broll_look(clip_key, idx, None, len(broll_clips), {})
                look_filter = _broll_filter_for_look(look)

                filters_retry.append(
                    f"[{broll_idx}:v]trim=duration={dur_clip:.3f},"
                    f"scale=1080:1920:force_original_aspect_ratio=increase,"
                    f"crop=1080:1920,"
                    f"setpts=PTS-STARTPTS+{bc['start']:.3f}/TB,"
                    f"tpad=stop_mode=clone:stop_duration={dur_clip:.3f}[{raw_label}]"
                )

                if look == "HEAVY":
                    graded = f"b{idx}_graded"
                    halo_main = f"b{idx}_hmain"
                    halo_src = f"b{idx}_hsrc"
                    halo_blur = f"b{idx}_hblur"
                    glow = f"b{idx}_glow"
                    filters_retry.append(f"[{raw_label}]{look_filter}[{graded}]")
                    filters_retry.append(f"[{graded}]split[{halo_main}][{halo_src}]")
                    filters_retry.append(f"[{halo_src}]{_HEAVY_HALATION_BLUR}[{halo_blur}]")
                    filters_retry.append(
                        f"[{halo_main}][{halo_blur}]blend="
                        f"all_mode=screen:all_opacity={_HEAVY_HALATION_BLEND_OPACITY}[{glow}]"
                    )
                    heavy_out = f"b{idx}_heavy"
                    filters_retry.append(
                        f"[{glow}]{_HEAVY_ZOOMPAN_EXPR},"
                        f"setpts=PTS-STARTPTS+{bc['start']:.3f}/TB"
                        f"[{heavy_out}]"
                    )
                    filters_retry.append(f"[{heavy_out}]null[{look_label}]")
                else:
                    filters_retry.append(f"[{raw_label}]{look_filter}[{look_label}]")

                filters_retry.append(
                    f"{last_label_retry}[{look_label}]overlay="
                    f"enable=between(t\\,{bc['start']:.3f}\\,{bc['end']:.3f})[{out_label}]"
                )
                last_label_retry = f"[{out_label}]"

            # ---- OVERLAY IMAGES (NO MOTION) ----
            for j, oi in enumerate(overlay_items):
                ov_idx = input_index_retry
                input_index_retry += 1

                out = f"vo{j}"

                w_px = max(1, int(1080 * oi["w"]))
                x_px = int(1080 * oi["x"])
                y_px = int(1920 * oi["y"])

                prep = f"ov{j}"
                filters_retry.append(
                    f"[{ov_idx}:v]scale={w_px}:-1,format=rgba,"
                    f"setpts=PTS-STARTPTS[{prep}]"
                )

                filters_retry.append(
                    f"{last_label_retry}[{prep}]overlay="
                    f"x={x_px}:y={y_px}:"
                    f"enable=between(t\\,{oi['start']:.3f}\\,{oi['end']:.3f})[{out}]"
                )
                last_label_retry = f"[{out}]"

            # Save label before captions for potential no-caption fallback
            last_label_before_captions = last_label_retry

            # ---- CAPTIONS (ASS burn) ----
            if has_captions:
                _caption_style_r = edit_plan.captions.style
                _invert_on_r = (
                    has_invert_captions
                    and _caption_style_r is not None
                    and _caption_style_r.invert is True
                )
                _inv_scope_r = (
                    _caption_style_r.invert_scope
                    if _invert_on_r and _caption_style_r and _caption_style_r.invert_scope in ("all", "emphasis")
                    else "all"
                )
                if _invert_on_r:
                    filters_retry.append(f"color=black:s=1080x1920:r=30:d={_total_dur:.3f}[_inv_black_r]")
                    filters_retry.append(f"[_inv_black_r]ass={inv_ass_path}:fontsdir=/usr/share/fonts[_inv_text_r]")
                    filters_retry.append(f"{last_label_retry}[_inv_text_r]blend=all_mode=difference:shortest=1[_inv_blended_r]")
                    last_label_retry = "[_inv_blended_r]"
                    if _inv_scope_r == "emphasis":
                        cap_out = "vcap"
                        filters_retry.append(f"{last_label_retry}ass={ass_path}:fontsdir=/usr/share/fonts[{cap_out}]")
                        last_label_retry = f"[{cap_out}]"
                else:
                    cap_out = "vcap"
                    filters_retry.append(f"{last_label_retry}ass={ass_path}:fontsdir=/usr/share/fonts[{cap_out}]")
                    last_label_retry = f"[{cap_out}]"

            map_v_retry = last_label_retry if str(last_label_retry).startswith("[") else f"[{last_label_retry}]"

            fc_retry = ";".join(filters_retry) if filters_retry else "null"
            fc_retry = _sanitize_fc(fc_retry)

            # --- hard fail on any control/format chars in retry graph too ---
            weird_retry = _find_weird_chars(fc_retry)
            if weird_retry:
                for i, ch, o, cat in weird_retry[:8]:
                    ctx = fc_retry[max(0, i - 20): i + 20]
                    logger.error("WEIRD_CHAR_RETRY idx=%d ord=%d cat=%s repr=%r ctx=%r", i, o, cat, ch, ctx)
                raise RuntimeError(
                    f"filter_complex_retry contains {len(weird_retry)} control/format chars; refusing to run"
                )

            logger.info("filter_complex_retry last300=%r", fc_retry[-300:])
            logger.info("filter_complex_retry tail_codepoints=%s", [ord(c) for c in fc_retry[-40:]])

            # Write retry filtergraph for debugging / forensics, then pass via -filter_complex
            fc_retry_path = work / "filter_complex_retry.txt"
            fc_retry_path.write_text(fc_retry, encoding="utf-8", errors="strict")

            cmd_retry = ["ffmpeg", "-y"] + inputs + [
                "-filter_complex_threads", "1",
                "-filter_complex", fc_retry,
                "-map", map_v_retry, "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "2",
                "-af", "aresample=async=1:first_pts=0",
                "-c:a", "aac", "-b:a", "160k",
                str(layered_path),
            ]

            try:
                _run_ffmpeg(cmd_retry, "layer-broll-overlays-captions-retry-no-motion", timeout=MAX_RENDER_TIMEOUT_SEC)
                current_video = str(layered_path)
            except RuntimeError as e_retry:
                logger.error(
                    "RETRY-NO-MOTION PASS FAILED (path=retry-no-motion) — "
                    "fc_retry len=%d tail_repr=%s",
                    len(fc_retry), repr(fc_retry[-600:]),
                )
                logger.warning(f"No-motion retry layer pass failed (non-fatal): {e_retry}")

                # ---- NEW FALLBACK: b-roll + overlays WITHOUT captions ----
                # The ASS caption filter may be causing the failure (e.g. font
                # rendering issues).  Try the same filter graph but drop the
                # ass= entry so b-roll and overlays can still render.
                if has_captions and (broll_clips or overlay_items):
                    logger.warning("Retrying with b-roll + overlays ONLY (no captions).")
                    filters_nocap = filters_retry[:-1]  # drop the trailing ass= entry
                    map_v_nocap = (
                        last_label_before_captions
                        if last_label_before_captions.startswith("[")
                        else f"[{last_label_before_captions}]"
                    )

                    fc_nocap = ";".join(filters_nocap) if filters_nocap else "null"
                    fc_nocap = _sanitize_fc(fc_nocap)

                    layered_nocap_path = work / "layered_nocap.mp4"
                    cmd_nocap = ["ffmpeg", "-y"] + inputs + [
                        "-filter_complex_threads", "1",
                        "-filter_complex", fc_nocap,
                        "-map", map_v_nocap, "-map", "0:a?",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                        "-threads", "2",
                        "-af", "aresample=async=1:first_pts=0",
                        "-c:a", "aac", "-b:a", "160k",
                        str(layered_nocap_path),
                    ]

                    try:
                        _run_ffmpeg(cmd_nocap, "layer-broll-overlays-no-captions", timeout=MAX_RENDER_TIMEOUT_SEC)
                        current_video = str(layered_nocap_path)
                        logger.info("B-roll + overlays rendered successfully (without captions).")

                        # Now try to burn captions separately on the layered result
                        captioned_on_layered = work / "captioned_on_layered.mp4"
                        try:
                            _run_ffmpeg(
                                [
                                    "ffmpeg", "-y",
                                    "-i", current_video,
                                    "-vf", f"ass={ass_path}:fontsdir=/usr/share/fonts",
                                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                                    "-threads", "2",
                                    "-af", "aresample=async=1:first_pts=0",
                                    "-c:a", "aac", "-b:a", "160k",
                                    str(captioned_on_layered),
                                ],
                                "burn-captions-on-layered",
                                timeout=MAX_RENDER_TIMEOUT_SEC,
                            )
                            current_video = str(captioned_on_layered)
                        except RuntimeError as e_cap:
                            logger.warning(f"Caption burn on layered video failed (non-fatal, keeping b-roll + overlays): {e_cap}")
                    except RuntimeError as e_nocap:
                        logger.warning(f"B-roll + overlays without captions also failed: {e_nocap}")

                # LAST resort: captions-only (skip if b-roll+overlays already rendered above)
                if has_captions and current_video == str(concat_path):
                    captioned_path = work / "captioned.mp4"
                    try:
                        _run_ffmpeg(
                            [
                                "ffmpeg", "-y",
                                "-i", current_video,
                                "-vf", f"ass={ass_path}:fontsdir=/usr/share/fonts",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                                "-threads", "2",
                                "-af", "aresample=async=1:first_pts=0",
                                "-c:a", "aac", "-b:a", "160k",
                                str(captioned_path),
                            ],
                            "burn-captions-fallback",
                            timeout=MAX_RENDER_TIMEOUT_SEC,
                        )
                        current_video = str(captioned_path)
                    except RuntimeError as e2:
                        logger.warning(f"Caption burn fallback failed (non-fatal): {e2}")
                    
    # Step 5: Mix in music
    if edit_plan.music.enabled:
        music_path = _get_music_track(edit_plan.music.track_id)
        if music_path and Path(music_path).exists():
            music_out = work / "with_music.mp4"
            vol_db = edit_plan.music.target_volume_db

            # Get video duration for music loop/trim
            duration_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", current_video,
            ]
            dur_result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=10)
            video_duration = 60.0
            if dur_result.returncode == 0:
                try:
                    info = json.loads(dur_result.stdout)
                    video_duration = float(info["format"]["duration"])
                except Exception:
                    pass

            vol_linear = 10 ** (vol_db / 20.0)

            try:
                _run_ffmpeg(
                    [
                        "ffmpeg", "-y",
                        "-i", current_video,
                        "-stream_loop", "-1", "-i", music_path,
                        "-t", str(video_duration),
                        "-filter_complex",
                        f"[1:a]volume={vol_linear:.4f},atrim=0:{video_duration:.2f}[music];"
                        f"[0:a][music]amix=inputs=2:duration=shortest:dropout_transition=2[aout]",
                        "-map", "0:v", "-map", "[aout]",
                        "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "160k",
                        str(music_out),
                    ],
                    "mix-music",
                    timeout=MAX_RENDER_TIMEOUT_SEC,
                )
                current_video = str(music_out)
            except RuntimeError as e:
                logger.warning(f"Music mix failed (non-fatal, continuing without music): {e}")

    # Step 6: Final output REMUX (no re-encode; preserves quality + avoids extra load)
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", current_video,
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ],
        "final-remux",
        timeout=MAX_RENDER_TIMEOUT_SEC,
    )

    logger.info(f"Render complete: {output_path}")
    return output_path

def _get_music_track(track_id: str) -> str | None:
    """Get path to a built-in music track."""
    # Try to find in the music directory
    for ext in [".mp3", ".wav", ".ogg", ".m4a"]:
        path = MUSIC_DIR / f"{track_id}{ext}"
        if path.exists() and path.stat().st_size > 100:
            return str(path)

    logger.warning(f"Music track not found: {track_id}")
    return None
