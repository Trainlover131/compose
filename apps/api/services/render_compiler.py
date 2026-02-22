"""Render compiler: converts EditPlan -> deterministic FFmpeg commands."""

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from apps.api.config import MUSIC_DIR, MAX_RENDER_TIMEOUT_SEC
from apps.api.models.schemas import EditPlan

logger = logging.getLogger(__name__)

# Maximum chars of FFmpeg stderr to include in error messages
_MAX_STDERR_CHARS = 2000

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
    "eq=brightness='0.015*sin(2*PI*t*3)':eval=frame,"
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
    "eq=contrast=1.20:saturation=0.96:brightness=0.00:gamma_r=1.00:gamma_g=1.00:gamma_b=1.03,"
    "colorbalance=rs=-0.040:gs=0.010:bs=0.045:rm=-0.010:gm=0.000:bm=0.010:rh=0.060:gh=0.020:bh=-0.065,"
    "curves=master='0/0 0.75/0.76 0.90/0.88 1/0.95',"
    "noise=c0s=4:c0f=t+u,"
    "drawgrid=w=0:h=4:t=1:c=black@0.04,"
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
_HEAVY_ZOOMPAN_EXPR = "zoompan=z='min(1.03,1+0.001*on)':d=1:s=1080x1920:fps=30"

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


def build_broll_filtergraph_entries(
    broll_clips: list[dict],
    input_index_start: int,
    last_label: str,
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
            filters.append(f"[{glow}]{_HEAVY_ZOOMPAN_EXPR}[{look_label}]")
        else:
            filters.append(
                f"[{raw_label}]{look_filter}[{look_label}]"
            )
        # Stage 3: composite [b{i}_look] (NOT [b{i}_raw]) onto running chain
        filters.append(
            f"{last_label}[{look_label}]overlay="
            f"enable='between(t,{bc['start']:.3f},{bc['end']:.3f})'[{out_label}]"
        )
        last_label = f"[{out_label}]"

    return filters, last_label, input_index

def _run_ffmpeg(cmd: list[str], step_name: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run an FFmpeg command with proper error capture.

    Raises RuntimeError with the last ~2k chars of stderr on failure.
    """
    logger.info(f"FFmpeg [{step_name}]: {' '.join(cmd[:6])}...")
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        stderr_tail = stderr_text[-_MAX_STDERR_CHARS:] if len(stderr_text) > _MAX_STDERR_CHARS else stderr_text
        logger.error(f"FFmpeg [{step_name}] failed (rc={result.returncode}):\n{stderr_tail}")
        raise RuntimeError(
            f"FFmpeg {step_name} failed: {stderr_tail.strip()[-500:]}"
        )
    return result

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

    # Get style params
    style_presets = {
        "snappy": {"fontsize": 58, "outline": 3, "shadow": 2, "bold": 1},
        "cinematic": {"fontsize": 48, "outline": 2, "shadow": 3, "bold": 0},
        "podcast": {"fontsize": 52, "outline": 2, "shadow": 1, "bold": 0},
        "luxury": {"fontsize": 44, "outline": 1, "shadow": 2, "bold": 0},
        "study": {"fontsize": 50, "outline": 2, "shadow": 1, "bold": 0},
        "default": {"fontsize": 52, "outline": 2, "shadow": 2, "bold": 0},
    }
    style = style_presets.get(caption_cfg.style_id, style_presets["default"])

    ass_content = f"""[Script Info]
Title: Compose Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter,{style['fontsize']},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},2,40,40,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Group words into caption chunks
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

    # Chunk words into groups
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
    if edit_plan.captions.enabled:
        generate_ass_subtitles(transcript, edit_plan, ass_path)
        has_captions = Path(ass_path).exists() and Path(ass_path).stat().st_size > 100

    # If we have ANY visual layers to apply, do one filter_complex pass
    if broll_clips or overlay_items or has_captions:
        layered_path = work / "layered.mp4"

        # Inputs: base video first, then b-roll, then overlay images
        inputs = ["-i", current_video]
        for bc in broll_clips:
            inputs.extend(["-i", bc["path"]])
        for oi in overlay_items:
            inputs.extend(["-i", oi["path"]])

        filters = []
        last_label = "[0:v]"
        input_index = 1  # 0 is base; b-roll start at 1

        # ---- B-ROLL FULLSCREEN CUTAWAYS ----
        broll_filters, last_label, input_index = build_broll_filtergraph_entries(
            broll_clips, input_index, last_label,
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
            filters.append(
                f"[{ov_idx}:v]scale={w_px}:-1,format=rgba,"
                f"setpts=PTS-STARTPTS[{prep}]"
            )

            # Simple on/off enable (fade can be added later)
            filters.append(
                f"{last_label}[{prep}]overlay="
                f"x={x_px}:y={y_px}:"
                f"enable='between(t,{oi['start']:.3f},{oi['end']:.3f})'[{out}]"
            )
            last_label = f"[{out}]"

        # ---- CAPTIONS (ASS burn) ----
        if has_captions:
            cap_out = "vcap"
            filters.append(f"{last_label}ass={ass_path}[{cap_out}]")
            last_label = f"[{cap_out}]"

        map_v = last_label if str(last_label).startswith("[") else f"[{last_label}]"

        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex_threads", "1",
            "-filter_complex", ";".join(filters) if filters else "null",
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
            logger.warning(f"Layer pass failed (non-fatal): {e}")

            # Fallback: at least burn captions if we have them
            if has_captions:
                captioned_path = work / "captioned.mp4"
                try:
                    _run_ffmpeg(
                        [
                            "ffmpeg", "-y",
                            "-i", current_video,
                            "-vf", f"ass={ass_path}",
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
