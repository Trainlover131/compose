"""AI Edit Planner using Claude Haiku (with demo fallback).

Two-phase LLM flow:
  Pass 1           — main_cuts / punch_ins / captions / music  (Claude Haiku)
  VisualDirector   — overlays + b-roll in ORIGINAL timeline    (Gemini multimodal)
                     then mapped to FINAL timeline and merged into EditPlan.
"""

import base64
import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import anthropic

from apps.api.config import (
    ANTHROPIC_API_KEY, DEMO_MODE, GEMINI_API_KEY,
    NANOBANANA_API_KEY, LOCAL_STORAGE_PATH,
)
from apps.api.models.presets import get_preset
from apps.api.models.schemas import EditPlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scheduling constants
# ---------------------------------------------------------------------------
MIN_BROLL_START = 3.0  # seconds — orientation buffer at start of final video

# ---------------------------------------------------------------------------
# Overlay cache directory
# ---------------------------------------------------------------------------
_OVERLAY_CACHE_DIR = (
    LOCAL_STORAGE_PATH / "overlay_cache"
    if LOCAL_STORAGE_PATH.exists()
    else Path("/tmp/overlay_cache")
)

# ===================================================================
# System prompt & schema  (Pass 1 only — cuts/punchins/captions/music)
# ===================================================================

PLANNER_SYSTEM_PROMPT = (
    "You are an expert short-form video editor AI. You receive a transcript "
    "with word-level timestamps, audio analysis data (silences, emphasis "
    "moments), a user prompt describing desired edits, and a style preset "
    "configuration.\n\n"
    "Your job is to output a valid JSON EditPlan that follows the schema "
    "exactly. The plan determines how to edit the raw talking-head video "
    "into an engaging short-form clip (9:16, 1080x1920).\n\n"
    "RULES:\n"
    "1. Return ONLY valid JSON. No markdown, no explanation, no code fences.\n"
    "2. main_cuts must be non-overlapping, sorted by start time, and their "
    "total duration >= 15s.\n"
    "3. main_cuts total duration must be <= max_duration_sec from the preset.\n"
    "4. Remove filler words, long silences, and boring parts based on the "
    "user prompt and preset.\n"
    "5. punch_ins should target emphasis moments (loud/important words). "
    "Scale range from preset config.\n"
    "6. Choose a music track_id from the available tracks that matches the "
    "preset mood.\n"
    "7. Caption style should match the preset configuration.\n"
    "8. The rationale should briefly explain the editing strategy.\n"
    "9. Set broll.enabled=false and broll.inserts=[] (b-roll is handled "
    "separately).\n"
    "10. Set overlays.enabled=false and overlays.items=[] (overlays are "
    "handled separately).\n\n"
    "Available music tracks: upbeat-energy, cinematic-ambient, "
    "clean-podcast, luxury-smooth, study-lofi"
)

EDIT_PLAN_SCHEMA = """{
  "version": "1",
  "preset_id": "<string>",
  "output": {
    "aspect_ratio": "9:16",
    "resolution": [1080, 1920],
    "max_duration_sec": <int>
  },
  "main_cuts": [
    { "start": <float>, "end": <float> }
  ],
  "punch_ins": [
    { "start": <float>, "end": <float>, "scale": <float 1.0-1.5> }
  ],
  "broll": {
    "enabled": <bool>,
    "strategy": "cutaway_fullscreen",
    "inserts": [
      {
        "start": <float>, "end": <float>,
        "query": "<search terms>",
        "keywords": ["<keyword>"],
        "source": "pexels",
        "notes": "<optional>"
      }
    ]
  },
  "overlays": {
    "enabled": <bool>,
    "items": [
      {
        "type": "image_overlay or video_overlay",
        "start": <float>, "end": <float>,
        "anchor_phrase": "<the spoken word/phrase>",
        "keyword": "<keyword>",
        "query": "<image generation or search prompt>",
        "source": "ai or pexels",
        "style_hint": "<e.g. logo, hud, cinematic>",
        "placement": { "x": <0..1>, "y": <0..1>, "w": <0..1> },
        "animation": { "fade_in": <float>, "fade_out": <float> },
        "notes": "<optional>"
      }
    ]
  },
  "captions": {
    "enabled": <bool>,
    "style_id": "<string>",
    "max_words_per_line": <int>,
    "max_lines": <int>
  },
  "music": {
    "enabled": <bool>,
    "track_id": "<string>",
    "target_volume_db": <float>
  },
  "rationale": {
    "hook": "<string>",
    "structure": ["<string>"]
  }
}"""


# ===================================================================
# Timeline mapping  (original -> final after cuts)
# ===================================================================

def _build_timeline_map_from_cuts(main_cuts: list) -> list[dict]:
    """Build [{orig_start, orig_end, final_start, final_end}, ...] from cuts."""
    timeline: list[dict] = []
    offset = 0.0
    for cut in main_cuts:
        s = cut.start if hasattr(cut, "start") else cut["start"]
        e = cut.end if hasattr(cut, "end") else cut["end"]
        timeline.append({
            "orig_start": s,
            "orig_end": e,
            "final_start": offset,
            "final_end": offset + (e - s),
        })
        offset += e - s
    return timeline


def _map_time(orig_t: float, timeline_map: list[dict]) -> Optional[float]:
    """Map a single original-timeline timestamp to final timeline.

    Returns None if outside all cuts.
    """
    for entry in timeline_map:
        if entry["orig_start"] <= orig_t <= entry["orig_end"]:
            return entry["final_start"] + (orig_t - entry["orig_start"])
    return None


# ===================================================================
# Non-overlap enforcement
# ===================================================================

def _enforce_nonoverlap(
    items: list[dict],
    shift_s: float = 0.2,
    max_total_shift_s: float = 0.6,
) -> list[dict]:
    """Shift later items forward to remove overlap.

    Safety caps:
      - Max cumulative shift per item = max_total_shift_s.
      - If still overlapping after max shift, reduce the *earlier* item's
        duration so it ends before the next item starts.
    """
    if len(items) < 2:
        return items

    items = sorted(items, key=lambda x: x["start"])

    for i in range(1, len(items)):
        prev = items[i - 1]
        cur = items[i]
        total_shifted = 0.0

        while cur["start"] < prev["end"] and total_shifted < max_total_shift_s:
            cur["start"] = round(cur["start"] + shift_s, 3)
            cur["end"] = round(cur["end"] + shift_s, 3)
            total_shifted += shift_s

        # If still overlapping after max shift, shrink previous item duration
        if cur["start"] < prev["end"]:
            prev["end"] = round(cur["start"] - 0.01, 3)
            if prev["end"] <= prev["start"]:
                prev["end"] = round(prev["start"] + 0.1, 3)

    return items


def _enforce_min_broll_start(
    broll_inserts: list[dict],
    timeline_map: list[dict],
    min_start: float = MIN_BROLL_START,
) -> list[dict]:
    """Drop or shift b-roll inserts that start before *min_start* in the final timeline.

    Preserves original order.  For each insert starting before min_start:
      - Shift forward so start == min_start (preserve duration).
      - After shifting, verify the insert's entire span still fits inside at
        least one cut segment (from timeline_map final_start/final_end).
      - If it doesn't fit, drop the insert.
    """
    if not broll_inserts:
        return broll_inserts

    result: list[dict] = []
    for br in broll_inserts:
        s, e = br["start"], br["end"]
        dur = e - s

        if s < min_start:
            s = min_start
            e = round(s + dur, 3)

            # Check the shifted span fits inside at least one cut segment
            fits = False
            for seg in timeline_map:
                if seg["final_start"] <= s and e <= seg["final_end"] + 0.01:
                    fits = True
                    break
            if not fits:
                logger.info(
                    "Dropped b-roll starting before %.1fs: "
                    "shifted %.3f-%.3f doesn't fit any cut segment",
                    min_start, s, e,
                )
                continue

            br = dict(br, start=round(s, 3), end=round(e, 3))

        result.append(br)

    return result


# ===================================================================
# NanoBanana image generation (best-effort, never breaks pipeline)
# ===================================================================

_NB_KEY = (NANOBANANA_API_KEY or "").strip()

_NB_ENDPOINT_REGULAR = "https://api.nanobananaapi.ai/api/v1/nanobanana/generate"
_NB_ENDPOINT_PRO = "https://api.nanobananaapi.ai/api/v1/nanobanana/generate-pro"


# ===================================================================
# NanoBananaPromptBuilder — compile overlay fields into a generation prompt
# ===================================================================

class NanoBananaPromptBuilder:
    """Compile VisualDirector overlay fields into a NanoBanana image prompt.

    Not template-based: Gemini's creative fields (intent, style_notes,
    must_include, must_avoid) are appended verbatim.  Only universal
    invariants (transparency, crisp edges, text legibility) are injected.
    """

    @staticmethod
    def build(overlay: dict) -> str:
        """Build the final NanoBanana prompt string from an overlay dict."""
        parts: list[str] = []

        ri = overlay.get("render_intent", {})
        wants_transparency = ri.get("wants_transparency", True)
        has_text = ri.get("has_text", False)
        text_value = overlay.get("text")

        # Universal invariants
        if wants_transparency:
            parts.append(
                "Transparent background PNG. "
                "Crisp vector-clean edges, tight bounding box around subject, "
                "centered composition."
            )
        else:
            parts.append(
                "Crisp vector-clean edges, tight bounding box around subject, "
                "centered composition."
            )

        parts.append("No photorealism unless explicitly requested.")

        # Text invariants
        if has_text or text_value:
            parts.append(
                "TEXT REQUIREMENTS: Bold filled glyphs and shapes — "
                "NOT outline-only. High legibility at small size. "
                "Avoid thin outline typography."
            )
            if text_value:
                parts.append(f'Text to render: "{text_value}"')

        # Gemini creative fields (verbatim)
        intent = overlay.get("intent", "")
        if intent:
            parts.append(f"Intent: {intent}")

        style_notes = overlay.get("style_notes")
        if style_notes:
            parts.append(f"Style: {style_notes}")

        must_include = overlay.get("must_include", [])
        if must_include:
            parts.append(f"Must include: {', '.join(must_include)}")

        must_avoid = overlay.get("must_avoid", [])
        if must_avoid:
            parts.append(f"Must avoid: {', '.join(must_avoid)}")

        # Base image prompt from Gemini
        image_prompt = overlay.get("query", "") or overlay.get("image_prompt", "")
        if image_prompt:
            parts.append(image_prompt)

        return " | ".join(parts)

    @staticmethod
    def select_endpoint(overlay: dict) -> str:
        """Select NanoBanana Pro or Regular endpoint based on render_intent.

        Pro is used when:
          - render_intent.requires_high_fidelity_text == true, OR
          - render_intent.has_text == true
        Otherwise Regular.
        """
        ri = overlay.get("render_intent", {})
        if ri.get("requires_high_fidelity_text") or ri.get("has_text"):
            return _NB_ENDPOINT_PRO
        return _NB_ENDPOINT_REGULAR

    @staticmethod
    def cache_key(overlay: dict) -> str:
        """Deterministic cache key from the compiled prompt + placement."""
        prompt = NanoBananaPromptBuilder.build(overlay)
        pw = 0.0
        pl = overlay.get("placement", {})
        if isinstance(pl, dict):
            pw = pl.get("w", 0.0)
        elif hasattr(pl, "w"):
            pw = pl.w
        raw = f"{prompt}|{pw:.2f}|9:16"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _nanobanana_cache_key(query: str, style_hint: str, placement_w: float) -> str:
    raw = f"{query}|{style_hint}|{placement_w:.2f}|9:16"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _extract_result_url(payload: dict) -> Optional[str]:
    """Best-effort extraction of an image URL from NanoBanana response."""
    if not isinstance(payload, dict):
        return None

    for k in ("resultImageUrl", "resultImageURL", "url",
              "resultUrl", "resultURL", "result_image_url"):
        v = payload.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v

    resp = payload.get("response")
    if isinstance(resp, dict):
        u = _extract_result_url(resp)
        if u:
            return u

    for k in ("resultImageUrls", "resultURLs", "urls", "images", "results"):
        v = payload.get(k)
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, str) and first.startswith("http"):
                return first
            if isinstance(first, dict):
                u = (first.get("url") or first.get("imageUrl")
                     or first.get("imageURL") or first.get("resultImageUrl"))
                if isinstance(u, str) and u.startswith("http"):
                    return u

    for k in ("data", "result", "output"):
        v = payload.get(k)
        if isinstance(v, dict):
            u = _extract_result_url(v)
            if u:
                return u
        elif isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, dict):
                u = _extract_result_url(first)
                if u:
                    return u
            if isinstance(first, str) and first.startswith("http"):
                return first

    return None


def _nanobanana_poll_result_url(
    task_id: str, timeout_s: float = 120.0,
) -> Optional[str]:
    """Poll NanoBanana record-info until complete. Return image URL or None."""
    if not _NB_KEY or not task_id:
        return None

    deadline = time.time() + timeout_s
    last_err: Optional[str] = None
    sleep_s = 1.0

    while time.time() < deadline:
        try:
            url = (
                "https://api.nanobananaapi.ai/api/v1/nanobanana/"
                f"record-info?taskId={task_id}"
            )
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {_NB_KEY}",
                    "Accept": "application/json",
                    "User-Agent": "compose-worker/1.0",
                },
                method="GET",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            payload = data.get("data", data) if isinstance(data, dict) else {}
            if not isinstance(payload, dict):
                payload = {}

            success_flag = payload.get("successFlag")
            result_url = _extract_result_url(payload)

            logger.info(
                "NanoBanana poll taskId=%s successFlag=%s "
                "hasResultUrl=%s sleep=%.1fs",
                task_id, success_flag, bool(result_url), sleep_s,
            )

            if success_flag == 1 and not result_url:
                logger.warning(
                    "NanoBanana successFlag=1 but no result URL. "
                    "payload_keys=%s payload=%s",
                    list(payload.keys()),
                    json.dumps(payload, ensure_ascii=False)[:1200],
                )

            if (success_flag == 1 and isinstance(result_url, str)
                    and result_url.startswith("http")):
                return result_url

            if success_flag in (-1, 2):
                last_err = f"task failed (successFlag={success_flag})"
                break

            time.sleep(sleep_s)
            sleep_s = min(5.0, sleep_s * 1.25)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:800]
            last_err = f"HTTPError {e.code} body={body}"
            logger.warning("NanoBanana poll HTTPError: %s (taskId=%s)",
                           last_err, task_id)
            if e.code in (401, 403):
                break
            time.sleep(sleep_s)
            sleep_s = min(5.0, sleep_s * 1.25)
        except Exception as e:
            last_err = f"poll error: {e}"
            logger.warning("NanoBanana poll error: %s (taskId=%s)",
                           last_err, task_id)
            time.sleep(sleep_s)
            sleep_s = min(5.0, sleep_s * 1.25)

    if last_err:
        logger.warning("NanoBanana poll failed: %s (taskId=%s)",
                       last_err, task_id)
    return None


def _generate_overlay_image_from_item(overlay: dict) -> Optional[str]:
    """Generate overlay image using NanoBananaPromptBuilder. Returns path or None."""
    if not _NB_KEY:
        return None

    _OVERLAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = NanoBananaPromptBuilder.cache_key(overlay)
    cached = _OVERLAY_CACHE_DIR / f"{cache_key}.png"
    if cached.exists():
        logger.info("Overlay cache hit: %s", cached)
        return str(cached)

    compiled_prompt = NanoBananaPromptBuilder.build(overlay)
    endpoint = NanoBananaPromptBuilder.select_endpoint(overlay)

    ri = overlay.get("render_intent", {})
    logger.info(
        "NanoBanana routing: endpoint=%s profile=%s has_text=%s "
        "requires_hf_text=%s",
        "Pro" if endpoint == _NB_ENDPOINT_PRO else "Regular",
        ri.get("profile", "?"),
        ri.get("has_text", False),
        ri.get("requires_high_fidelity_text", False),
    )

    try:
        payload = json.dumps({
            "prompt": compiled_prompt,
            "numImages": 1,
            "type": "TEXTTOIAMGE",
            "image_size": "9:16",
        }).encode()

        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "compose-worker/1.0",
                "Authorization": f"Bearer {_NB_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:800]
            logger.warning("NanoBanana API HTTP %s: %s", e.code, body)
            return None

        task_id = None
        if isinstance(data, dict):
            task_id = data.get("taskId")
            if not task_id and isinstance(data.get("data"), dict):
                task_id = data["data"].get("taskId")

        if task_id:
            result_url = _nanobanana_poll_result_url(
                str(task_id), timeout_s=150.0,
            )
            if not result_url:
                logger.warning(
                    "NanoBanana async task no result (taskId=%s)", task_id,
                )
                return None

            img_req = urllib.request.Request(
                result_url,
                headers={
                    "Accept": "image/*",
                    "User-Agent": "compose-worker/1.0",
                },
                method="GET",
            )
            with urllib.request.urlopen(img_req, timeout=150) as img_resp:
                cached.write_bytes(img_resp.read())

            logger.info("Overlay image downloaded via async poll: %s", cached)
            return str(cached)

        image_url = None
        image_b64 = None

        if isinstance(data, dict):
            for key in ("url", "image_url", "imageUrl", "output"):
                if isinstance(data.get(key), str) and data[key].startswith("http"):
                    image_url = data[key]
                    break

            images = data.get("images", data.get("results", []))
            if isinstance(images, list) and images:
                item = images[0]
                if isinstance(item, str):
                    image_url = item if item.startswith("http") else None
                    image_b64 = None if image_url else item
                elif isinstance(item, dict):
                    image_url = item.get("url") or item.get("image_url")
                    image_b64 = item.get("base64") or item.get("b64")

            if not image_url and not image_b64:
                image_b64 = data.get("base64") or data.get("image_base64")

        if image_url:
            with urllib.request.urlopen(
                urllib.request.Request(image_url), timeout=150,
            ) as img_resp:
                cached.write_bytes(img_resp.read())
            logger.info("Overlay image downloaded: %s", cached)
            return str(cached)

        if image_b64:
            cached.write_bytes(base64.b64decode(image_b64))
            logger.info("Overlay image decoded from base64: %s", cached)
            return str(cached)

        logger.warning(
            "NanoBanana response had no usable image data: %s",
            list(data.keys()) if isinstance(data, dict) else type(data),
        )
        return None

    except Exception as e:
        logger.warning("NanoBanana generation failed (non-fatal): %s", e)
        return None


# ===================================================================
# LLM helper: call Claude and parse JSON
# ===================================================================

def _strip_fences(raw: str) -> str:
    """Remove markdown code fences from an LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
    return raw.strip()


def _call_claude(
    client: anthropic.Anthropic, system: str,
    user_msg: str, max_tokens: int = 4096,
) -> Optional[str]:
    """Call Claude Haiku and return the raw text response, or None."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning("Claude call failed: %s", e)
        return None


# ===================================================================
# Transcript / analysis helpers
# ===================================================================

def _compress_transcript(transcript: dict) -> str:
    """Compress transcript to essential info for the planner."""
    lines = []
    for seg in transcript.get("segments", []):
        lines.append(f"[{seg['start']:.1f}-{seg['end']:.1f}] {seg['text']}")
    return "\n".join(lines)


def _summarize_silences(analysis: dict) -> str:
    silences = analysis.get("silences", [])
    if not silences:
        return "No significant silences detected."
    lines = [
        f"  {s['start']:.1f}-{s['end']:.1f}s ({s['duration']:.1f}s)"
        for s in silences[:20]
    ]
    return f"{len(silences)} silences found:\n" + "\n".join(lines)


def _transcript_snippet_at(transcript: dict, t: float, max_chars: int = 80) -> str:
    """Return the transcript text closest to time *t*, truncated."""
    best_seg = None
    best_dist = float("inf")
    for seg in transcript.get("segments", []):
        mid = (seg["start"] + seg["end"]) / 2
        dist = abs(mid - t)
        if dist < best_dist:
            best_dist = dist
            best_seg = seg
    if best_seg is None:
        return "(no transcript)"
    text = best_seg.get("text", "").strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return f"[{best_seg['start']:.1f}s] {text}"


def _summarize_emphasis(analysis: dict) -> str:
    moments = analysis.get("emphasis_moments", [])
    if not moments:
        return "No emphasis moments detected."
    lines = [
        f"  {m['time']:.1f}s (strength: {m['strength']:.1f}x)"
        for m in moments[:20]
    ]
    return f"{len(moments)} emphasis moments:\n" + "\n".join(lines)


# ===================================================================
# VisualDirector -> EditPlan mapping helpers
# ===================================================================

def _extract_overlay_times(
    ov: dict,
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Extract start/end times from an overlay dict, backwards-compatibly.

    Prefers start_orig/end_orig if present and numeric.
    Falls back to start/end if present and numeric.
    Returns (start, end, None) on success, or (None, None, drop_reason).
    """
    for s_key, e_key in [("start_orig", "end_orig"), ("start", "end")]:
        s_raw = ov.get(s_key)
        e_raw = ov.get(e_key)
        if s_raw is None or e_raw is None:
            continue
        try:
            s = float(s_raw)
            e = float(e_raw)
        except (ValueError, TypeError):
            continue
        if not (math.isfinite(s) and math.isfinite(e)):
            continue
        if s >= e:
            return None, None, "START_GE_END"
        return s, e, None

    has_any = any(ov.get(k) is not None for k in ("start_orig", "end_orig", "start", "end"))
    return None, None, ("NON_NUMERIC_TIMES" if has_any else "MISSING_TIMES")


def _log_overlay_drop_diagnostics(
    idx: int,
    ov: dict,
    mapped_start: Optional[float],
    mapped_end: Optional[float],
    drop_reason: Optional[str],
) -> None:
    """Log compact diagnostics for a single raw overlay (first 3 only)."""
    field_flags: list[str] = []
    numeric_parts: list[str] = []
    for key in ("start", "end", "start_orig", "end_orig"):
        val = ov.get(key)
        if val is not None:
            field_flags.append(key)
            try:
                numeric_parts.append(f"{key}={float(val):.3f}")
            except (ValueError, TypeError):
                numeric_parts.append(f"{key}=NaN")

    mapped_str = ""
    if mapped_start is not None and mapped_end is not None:
        mapped_str = f" mapped={mapped_start:.3f}-{mapped_end:.3f}"
    elif mapped_start is not None or mapped_end is not None:
        mapped_str = f" mapped=({mapped_start},{mapped_end})"

    status = f"drop_reason={drop_reason}" if drop_reason else "KEPT"
    logger.debug(
        "overlay[%d] has=(%s) %s%s %s",
        idx,
        ",".join(field_flags) or "none",
        " ".join(numeric_parts) or "no_numeric",
        mapped_str,
        status,
    )


def _map_vd_overlays(
    vd_overlays: list[dict],
    timeline_map: list[dict],
) -> list[dict]:
    """Map VisualDirector overlays from original to final timeline.

    Backwards-compatible: prefers start_orig/end_orig, falls back to
    start/end.  Drops items that fall entirely outside kept cuts.
    """
    mapped: list[dict] = []
    for idx, ov in enumerate(vd_overlays):
        orig_s, orig_e, drop_reason = _extract_overlay_times(ov)

        fs = fe = None
        if not drop_reason:
            fs = _map_time(orig_s, timeline_map)
            fe = _map_time(orig_e, timeline_map)
            if fs is None or fe is None:
                drop_reason = "FAILED_TO_MAP_ORIG_TO_FINAL"
            elif fe <= fs:
                drop_reason = "START_GE_END"

        if idx < 3:
            _log_overlay_drop_diagnostics(idx, ov, fs, fe, drop_reason)

        if drop_reason:
            continue

        mapped.append({
            "type": "image_overlay",
            "start": round(fs, 3),
            "end": round(fe, 3),
            "anchor_phrase": "",
            "keyword": "",
            "query": ov.get("image_prompt", ""),
            "source": "ai",
            "style_hint": "",
            "placement": ov.get("placement", {}),
            "animation": ov.get("animation", {}),
            "notes": ov.get("reason", ""),
            "intent": ov.get("intent", ""),
            "style_notes": ov.get("style_notes"),
            "must_include": ov.get("must_include", []),
            "must_avoid": ov.get("must_avoid", []),
            "text": ov.get("text"),
            "render_intent": ov.get("render_intent", {}),
        })
    return mapped


def _map_vd_broll(
    vd_broll: list[dict],
    timeline_map: list[dict],
) -> list[dict]:
    """Map VisualDirector b-roll from original to final timeline.

    Converts start_orig/end_orig -> start/end and formats for EditPlan.
    Drops items that fall entirely outside kept cuts.
    """
    mapped: list[dict] = []
    for br in vd_broll:
        fs = _map_time(br["start_orig"], timeline_map)
        fe = _map_time(br["end_orig"], timeline_map)
        if fs is None or fe is None or fe <= fs:
            continue
        query = br["query"]
        keywords = query.split()[:3]
        mapped.append({
            "start": round(fs, 3),
            "end": round(fe, 3),
            "query": query,
            "keywords": keywords,
            "source": "pexels",
            "notes": br.get("reason", ""),
        })
    return mapped


def _log_mapping_examples(
    label: str, orig_items: list[dict], mapped_items: list[dict],
) -> None:
    """Log first 3 items before/after timeline mapping for debugging."""
    for i, (o, m) in enumerate(zip(orig_items[:3], mapped_items[:3])):
        logger.info(
            "VisualDirector %s [%d]: orig=%.3f-%.3f -> final=%.3f-%.3f",
            label, i,
            o.get("start_orig", 0), o.get("end_orig", 0),
            m["start"], m["end"],
        )


def _log_debug_scheduling(
    broll_inserts: list[dict],
    overlay_items: list[dict],
    transcript: dict,
) -> None:
    """Log debug info for the first 3 b-roll inserts and overlays."""
    for i, br in enumerate(broll_inserts[:3]):
        snippet = _transcript_snippet_at(transcript, br["start"])
        query = br.get("query", "")
        if len(query) > 180:
            query = query[:180] + "..."
        logger.info(
            "DEBUG broll[%d]: final=%.3f-%.3f transcript=%s query=%s",
            i, br["start"], br["end"], snippet, query,
        )

    for i, ov in enumerate(overlay_items[:3]):
        snippet = _transcript_snippet_at(transcript, ov["start"])
        ri = ov.get("render_intent", {})
        if isinstance(ri, dict):
            has_text = ri.get("has_text", False)
            hf_text = ri.get("requires_high_fidelity_text", False)
            profile = ri.get("profile", "?")
        else:
            has_text = getattr(ri, "has_text", False)
            hf_text = getattr(ri, "requires_high_fidelity_text", False)
            profile = getattr(ri, "profile", "?")

        use_pro = has_text or hf_text
        prompt_str = ov.get("query", "")
        if len(prompt_str) > 180:
            prompt_str = prompt_str[:180] + "..."

        logger.info(
            "DEBUG overlay[%d]: final=%.3f-%.3f transcript=%s "
            "prompt=%s endpoint=%s (profile=%s has_text=%s hf_text=%s)",
            i, ov["start"], ov["end"], snippet, prompt_str,
            "Pro" if use_pro else "Regular", profile, has_text, hf_text,
        )


# ===================================================================
# Main entry point — Pass 1 (Claude) + VisualDirector (Gemini)
# ===================================================================

def plan_edit(
    transcript: dict,
    analysis: dict,
    prompt: str,
    preset_id: str,
    video_duration: float,
    video_path: Optional[str] = None,
) -> EditPlan:
    """Generate an EditPlan: Claude Pass 1 + VisualDirector (Gemini).

    Pass 1:           Claude decides main_cuts / punch_ins / captions / music.
    VisualDirector:   Gemini proposes overlays + b-roll in ORIGINAL timeline,
                      then we map to FINAL timeline and merge into the plan.
    """
    if DEMO_MODE:
        logger.info("Demo mode: using rule-based planner")
        return _demo_plan(transcript, analysis, preset_id, video_duration)

    preset = get_preset(preset_id) or get_preset("snappy-creator")
    config = preset["config"]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ---------------------------------------------------------------
    # PASS 1:  main_cuts / punch_ins / captions / music
    # ---------------------------------------------------------------
    compressed_transcript = _compress_transcript(transcript)
    silence_summary = _summarize_silences(analysis)
    emphasis_summary = _summarize_emphasis(analysis)

    pass1_msg = (
        f"Create an EditPlan for this video.\n\n"
        f"VIDEO DURATION: {video_duration:.1f}s\n\n"
        f"USER PROMPT: {prompt}\n\n"
        f"PRESET: {preset_id}\n"
        f"PRESET CONFIG: {json.dumps(config, indent=2)}\n\n"
        f"TRANSCRIPT (with timestamps):\n{compressed_transcript}\n\n"
        f"SILENCE ANALYSIS:\n{silence_summary}\n\n"
        f"EMPHASIS MOMENTS:\n{emphasis_summary}\n\n"
        f"OUTPUT SCHEMA:\n{EDIT_PLAN_SCHEMA}\n\n"
        f"IMPORTANT: Set broll.enabled=false and broll.inserts=[] "
        f"(b-roll timing will be added separately).\n"
        f"Set overlays.enabled=false and overlays.items=[] "
        f"(overlays will be added separately).\n"
        f"Focus on main_cuts, punch_ins, captions, and music.\n\n"
        f"Generate the EditPlan JSON now. Remember: ONLY valid JSON, "
        f"no markdown."
    )

    plan = None
    for attempt in range(2):
        raw = _call_claude(client, PLANNER_SYSTEM_PROMPT, pass1_msg)
        if raw is None:
            break
        try:
            raw = _strip_fences(raw)
            plan_data = json.loads(raw)

            if not isinstance(plan_data.get("broll"), dict):
                plan_data["broll"] = {}
            plan_data["broll"]["enabled"] = False
            plan_data["broll"]["strategy"] = plan_data["broll"].get(
                "strategy", "cutaway_fullscreen",
            )
            plan_data["broll"]["inserts"] = []

            if not isinstance(plan_data.get("overlays"), dict):
                plan_data["overlays"] = {}
            plan_data["overlays"]["enabled"] = False
            plan_data["overlays"]["items"] = []

            plan = EditPlan.model_validate(plan_data)

            if plan.total_duration() < 10:
                raise ValueError("Plan total duration too short (< 10s)")

            logger.info(
                "Pass 1 plan: %d cuts, %d punch-ins",
                len(plan.main_cuts), len(plan.punch_ins),
            )
            break
        except Exception as e:
            if attempt == 0:
                logger.warning("Pass 1 attempt %d failed: %s. Retrying...",
                               attempt + 1, e)
                pass1_msg = (
                    f"The previous JSON was invalid: {e!s}\n\n"
                    f"Fix it to valid JSON matching the schema. "
                    f"Do not change the meaning.\n\n"
                    f"Previous response:\n{raw}\n\n"
                    f"Return ONLY valid JSON."
                )
            else:
                logger.error("Pass 1 failed after 2 attempts: %s", e)

    if plan is None:
        logger.info("Pass 1 failed, falling back to demo planner")
        plan = _demo_plan(transcript, analysis, preset_id, video_duration)

    # ---------------------------------------------------------------
    # VisualDirector:  overlays + b-roll  (Gemini multimodal)
    # ---------------------------------------------------------------
    overlay_items: list[dict] = []
    broll_inserts: list[dict] = []

    if GEMINI_API_KEY:
        try:
            from apps.api.visual_director import VisualDirector

            vd = VisualDirector()
            vd_result = vd.propose(
                video_path=video_path,
                transcript=transcript,
                prompt=prompt,
                video_duration=video_duration,
            )

            vd_overlays = vd_result.get("overlays", [])
            vd_broll = vd_result.get("broll", [])
            logger.info(
                "VisualDirector raw: overlays=%d broll=%d",
                len(vd_overlays), len(vd_broll),
            )

            # Map original -> final timeline
            tmap = _build_timeline_map_from_cuts(plan.main_cuts)

            if vd_overlays:
                overlay_items = _map_vd_overlays(vd_overlays, tmap)
                _log_mapping_examples("overlay", vd_overlays, overlay_items)
                overlay_items = _enforce_nonoverlap(overlay_items)
                logger.info(
                    "VisualDirector overlays after mapping+nonoverlap: %d",
                    len(overlay_items),
                )

            if vd_broll:
                broll_inserts = _map_vd_broll(vd_broll, tmap)
                _log_mapping_examples("broll", vd_broll, broll_inserts)
                broll_inserts = _enforce_nonoverlap(broll_inserts)
                pre_count = len(broll_inserts)
                broll_inserts = _enforce_min_broll_start(broll_inserts, tmap)
                logger.info(
                    "VisualDirector broll after mapping+nonoverlap: %d, "
                    "after min-start filter: %d",
                    pre_count, len(broll_inserts),
                )

        except Exception as e:
            logger.warning("VisualDirector failed (non-fatal): %s", e)
            overlay_items = []
            broll_inserts = []
    else:
        logger.info("VisualDirector skipped: GEMINI_API_KEY not set")

    # ---------------------------------------------------------------
    # Assemble final plan
    # ---------------------------------------------------------------
    plan_dict = plan.model_dump()

    if overlay_items:
        plan_dict["overlays"] = {"enabled": True, "items": overlay_items}

    if broll_inserts:
        plan_dict["broll"] = {
            "enabled": True,
            "strategy": "cutaway_fullscreen",
            "inserts": broll_inserts,
        }

    plan = EditPlan.model_validate(plan_dict)

    # ---------------------------------------------------------------
    # Debug logging for first 3 b-roll + overlays
    # ---------------------------------------------------------------
    _log_debug_scheduling(broll_inserts, overlay_items, transcript)

    # ---------------------------------------------------------------
    # Best-effort NanoBanana asset generation for AI overlays
    # ---------------------------------------------------------------
    if plan.overlays.enabled and plan.overlays.items:
        _generate_overlay_assets(plan)

    logger.info(
        "Final plan: %d cuts, %d punch-ins, %d b-roll, %d overlays",
        len(plan.main_cuts), len(plan.punch_ins),
        len(plan.broll.inserts), len(plan.overlays.items),
    )
    return plan


def _generate_overlay_assets(plan: EditPlan) -> None:
    """Best-effort: generate NanoBanana images for AI-sourced overlays."""
    if not _NB_KEY:
        return
    for item in plan.overlays.items:
        if item.source == "ai" and not item.asset_path and item.query:
            overlay_dict = item.model_dump()
            path = _generate_overlay_image_from_item(overlay_dict)
            if path:
                item.asset_path = path


# ===================================================================
# Demo / fallback planner
# ===================================================================

def _demo_plan(
    transcript: dict,
    analysis: dict,
    preset_id: str,
    video_duration: float,
) -> EditPlan:
    """Rule-based fallback planner for demo mode."""
    preset = get_preset(preset_id) or get_preset("snappy-creator")
    config = preset["config"]
    target_dur = min(config["target_duration_sec"], video_duration)
    silence_threshold_s = config["silence_trim_ms"] / 1000.0

    segments = transcript.get("segments", [])
    emphasis = analysis.get("emphasis_moments", [])

    cuts = []
    if segments:
        for seg in segments:
            cuts.append({"start": seg["start"], "end": seg["end"]})
    else:
        cuts.append({"start": 0.0, "end": min(target_dur, video_duration)})

    # Merge adjacent/overlapping cuts
    merged = []
    for cut in sorted(cuts, key=lambda c: c["start"]):
        if merged and cut["start"] <= merged[-1]["end"] + silence_threshold_s:
            merged[-1]["end"] = max(merged[-1]["end"], cut["end"])
        else:
            merged.append(dict(cut))

    # Trim to target duration
    final_cuts = []
    total = 0.0
    for cut in merged:
        dur = cut["end"] - cut["start"]
        if total + dur > target_dur:
            remaining = target_dur - total
            if remaining > 1.0:
                final_cuts.append({
                    "start": cut["start"],
                    "end": cut["start"] + remaining,
                })
            break
        final_cuts.append(cut)
        total += dur

    if not final_cuts:
        final_cuts = [{"start": 0.0, "end": min(target_dur, video_duration)}]

    # Generate punch-ins from emphasis moments
    scale_min, scale_max = config["punch_in_scale_range"]
    punch_ins = []
    for em in emphasis[:8]:
        t = em["time"]
        for cut in final_cuts:
            if cut["start"] <= t <= cut["end"]:
                scale = min(
                    scale_max,
                    scale_min + (em.get("strength", 1.0) - 1.0) * 0.05,
                )
                punch_ins.append({
                    "start": max(cut["start"], t - 0.3),
                    "end": min(cut["end"], t + 0.5),
                    "scale": round(scale, 2),
                })
                break

    cap_style = config["caption_style"]

    return EditPlan.model_validate({
        "version": "1",
        "preset_id": preset_id,
        "output": {
            "aspect_ratio": "9:16",
            "resolution": [1080, 1920],
            "max_duration_sec": int(target_dur),
        },
        "main_cuts": final_cuts,
        "punch_ins": punch_ins,
        "broll": {
            "enabled": False,
            "strategy": "cutaway_fullscreen",
            "inserts": [],
        },
        "overlays": {
            "enabled": False,
            "items": [],
        },
        "captions": {
            "enabled": True,
            "style_id": cap_style["style_id"],
            "max_words_per_line": cap_style["max_words_per_line"],
            "max_lines": cap_style["max_lines"],
        },
        "music": {
            "enabled": True,
            "track_id": config["default_music_track"],
            "target_volume_db": -18.0,
        },
        "rationale": {
            "hook": "Demo mode: rule-based editing with silence removal",
            "structure": [
                "Kept speech segments",
                "Removed silences",
                "Added emphasis zoom",
            ],
        },
    })
