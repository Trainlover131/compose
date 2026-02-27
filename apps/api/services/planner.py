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
    PEXELS_API_KEY, OVERLAY_SOURCE_PRIMARY, OVERLAY_SOURCE_FALLBACK_AI,
    CLIP_ENABLED, CLIP_CANDIDATES_PER_VARIANT,
    LOGO_DEV_SECRET_KEY, LOGO_DEV_PUBLISHABLE_KEY,
)
from apps.api.models.presets import get_preset
from apps.api.models.schemas import EditPlan
from apps.api.services.overlay_qc import detect_checkerboard_background

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
    "   If the user specifies any caption styling (font, color, size, "
    "position, outline, shadow, italic, bold, karaoke, etc.), populate "
    "captions.style with ONLY the fields they specified. Leave all other "
    "style fields as null so the renderer defaults apply. Do NOT emit "
    "raw ASS tags — only structured style fields.\n"
    "   FONT INTENT MAP — When the user asks for a font vibe, choose "
    "from these ordered fallback chains. Prefer the first available font. "
    "If the user asks for a specific font name, try it first; if "
    "unavailable, the renderer falls back to the closest intent chain.\n"
    "     * sans / helvetica / clean / modern → Liberation Sans, Roboto, "
    "DejaVu Sans, Noto Sans\n"
    "     * serif / classic / editorial / fancy / playfair → Playfair "
    "Display, EB Garamond, DejaVu Serif, Noto Serif\n"
    "     * handwritten / cursive / script → Comic Neue, DejaVu Sans, "
    "Noto Sans (script fonts often missing; keep safe fallbacks)\n"
    "     * mono / code / terminal → Noto Mono, DejaVu Sans Mono\n"
    "   COLOR FORMAT — Use #RRGGBB hex. For named colors: red=#FF0000, "
    "orange=#FF8800, blue=#0066FF, green=#00CC00, yellow=#FFCC00, "
    "white=#FFFFFF, black=#000000, pink=#FF69B4, cyan=#00FFFF, "
    "purple=#9900FF.\n"
    "   KARAOKE RULES — If the user asks for karaoke or word-by-word "
    "highlighting, set karaoke.enabled=true and karaoke.color to the "
    "highlight color. Do NOT set captions.style.color to the karaoke "
    "color; that changes the base text color. The base text stays white "
    "unless the user explicitly asks to change the caption base color.\n"
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
    "max_lines": <int>,
    "style": {
      "font_primary": "<string or null>",
      "font_emphasis": "<string or null>",
      "size": "<int or null>",
      "bold": "<bool or null>",
      "italic": "<bool or null>",
      "color": "<#RRGGBB or null>",
      "outline_color": "<#RRGGBB or null>",
      "outline_width": "<int 0-10 or null>",
      "shadow_depth": "<int 0-10 or null>",
      "tracking": "<int -6..6 or null>",
      "y": "<int 900-1700 or null>",
      "align": "<int 1-9 or null>",
      "karaoke": { "enabled": "<bool or null>", "color": "<#RRGGBB or null>" },
      "pause_emphasis": { "enabled": "<bool or null>", "threshold_sec": "<float or null>" }
    }
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

    POLICY: MIN_BROLL_START applies ONLY to b-roll inserts.
            Overlays are explicitly allowed at any time including [0.0, 3.0).
            This function must NEVER be called on overlay items.

    Called AFTER:
      (a) mapping orig->final timeline, AND
      (b) non-overlap shifting.

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
                "Transparent background PNG with real alpha channel. "
                "Crisp vector-clean edges, tight bounding box around subject, "
                "centered composition. "
                "No checkerboard, no transparency grid, "
                "no alpha preview background, no tiled background pattern."
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


def _parse_nanobanana_pro_result_url(
    payload: dict,
) -> tuple[Optional[str], Optional[str]]:
    """Parse NanoBanana Pro callback-shaped response.

    Authoritative shape:
        {"code": 200, "msg": "...", "data": {"taskId": "...", "info": {"resultImageUrl": "..."}}}

    Returns (task_id, result_url).  Either may be None if not present/ready.
    ONLY used for Pro endpoint responses.  Regular parsing is untouched.
    """
    if not isinstance(payload, dict):
        return None, None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None, None

    task_id = data.get("taskId")
    if task_id is not None:
        task_id = str(task_id)

    result_url = None
    info = data.get("info")
    if isinstance(info, dict):
        url_val = info.get("resultImageUrl")
        if isinstance(url_val, str) and url_val.startswith("http"):
            result_url = url_val

    return task_id, result_url


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

    is_pro = endpoint == _NB_ENDPOINT_PRO
    endpoint_label = "Pro" if is_pro else "Regular"
    logger.info("NanoBanana: using %s endpoint", endpoint_label)

    result = _nanobanana_call_and_parse(endpoint, compiled_prompt, cached, is_pro)

    # Pro fallback: retry ONCE with Regular if Pro failed
    if result is None and is_pro:
        logger.info(
            "NanoBanana: Pro endpoint failed, falling back to Regular endpoint"
        )
        result = _nanobanana_call_and_parse(
            _NB_ENDPOINT_REGULAR, compiled_prompt, cached, False,
        )

    # --- Overlay QC: checkerboard detection + one retry ---
    if result is not None and detect_checkerboard_background(result):
        logger.info(
            "Overlay QC: checkerboard detected; regenerating once "
            "(endpoint=%s)", endpoint_label,
        )
        # Remove the bad cached file so _nanobanana_call_and_parse writes fresh
        try:
            cached.unlink(missing_ok=True)
        except OSError:
            pass
        result = _nanobanana_call_and_parse(
            endpoint, compiled_prompt, cached, is_pro,
        )
        if result is not None and detect_checkerboard_background(result):
            logger.info(
                "Overlay QC: checkerboard still present after retry; "
                "keeping image anyway"
            )

    return result


def _nanobanana_call_and_parse(
    endpoint: str,
    compiled_prompt: str,
    cached: Path,
    is_pro: bool,
) -> Optional[str]:
    """Send request to NanoBanana and parse response. Returns cached path or None."""
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

        # --- Pro endpoint: use dedicated parser ---
        if is_pro:
            pro_task_id, pro_url = _parse_nanobanana_pro_result_url(data)

            # Direct URL available (callback shape with immediate result)
            if pro_url:
                img_req = urllib.request.Request(
                    pro_url,
                    headers={"Accept": "image/*", "User-Agent": "compose-worker/1.0"},
                    method="GET",
                )
                with urllib.request.urlopen(img_req, timeout=150) as img_resp:
                    cached.write_bytes(img_resp.read())
                logger.info("Overlay image downloaded via Pro direct URL: %s", cached)
                return str(cached)

            # taskId but no URL yet — poll for result
            if pro_task_id:
                result_url = _nanobanana_poll_result_url(
                    pro_task_id, timeout_s=150.0,
                )
                if result_url:
                    img_req = urllib.request.Request(
                        result_url,
                        headers={"Accept": "image/*", "User-Agent": "compose-worker/1.0"},
                        method="GET",
                    )
                    with urllib.request.urlopen(img_req, timeout=150) as img_resp:
                        cached.write_bytes(img_resp.read())
                    logger.info("Overlay image downloaded via Pro async poll: %s", cached)
                    return str(cached)
                else:
                    logger.warning(
                        "NanoBanana Pro async task no result (taskId=%s)",
                        pro_task_id,
                    )
                    return None

            # Pro response didn't match expected shape at all
            logger.warning("NanoBanana Pro response had no taskId or URL")
            return None

        # --- Regular endpoint: UNCHANGED parsing logic below ---
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
    """Log compact INFO diagnostics for a single raw overlay (first 3 only)."""
    # Time field presence + values
    time_parts: list[str] = []
    for key in ("start", "end", "start_orig", "end_orig"):
        val = ov.get(key)
        if val is not None:
            try:
                time_parts.append(f"{key}={float(val):.3f}")
            except (ValueError, TypeError):
                time_parts.append(f"{key}=NaN")

    # Content field presence
    has_flags = (
        f"img_prompt={'Y' if ov.get('image_prompt') else 'N'} "
        f"intent={'Y' if ov.get('intent') else 'N'} "
        f"text={'Y' if ov.get('text') else 'N'}"
    )

    # Placement + animation
    pl = ov.get("placement")
    pl_str = f"pl={pl}" if isinstance(pl, dict) else "pl=MISSING"
    an = ov.get("animation")
    an_str = f"an={an}" if isinstance(an, dict) else "an=MISSING"

    mapped_str = ""
    if mapped_start is not None and mapped_end is not None:
        mapped_str = f" mapped={mapped_start:.3f}-{mapped_end:.3f}"
    elif mapped_start is not None or mapped_end is not None:
        mapped_str = f" mapped=({mapped_start},{mapped_end})"

    status = f"drop_reason={drop_reason}" if drop_reason else "KEPT"
    logger.info(
        "overlay[%d] %s | %s | %s %s%s | %s",
        idx,
        " ".join(time_parts) or "no_times",
        has_flags,
        pl_str, an_str,
        mapped_str,
        status,
    )


def _map_vd_overlays(
    vd_overlays: list[dict],
    timeline_map: list[dict],
) -> list[dict]:
    """Map VisualDirector overlays from original to final timeline.

    Backwards-compatible: prefers start_orig/end_orig, falls back to
    start/end.  Clips overlays that span cut boundaries instead of
    dropping them.  Only drops if entirely outside all cuts.
    """
    mapped: list[dict] = []
    for idx, ov in enumerate(vd_overlays):
        orig_s, orig_e, drop_reason = _extract_overlay_times(ov)

        fs = fe = None
        if not drop_reason:
            fs = _map_time(orig_s, timeline_map)
            fe = _map_time(orig_e, timeline_map)

            # Clip to cut boundary when one end falls in a gap
            if fs is not None and fe is None:
                for entry in timeline_map:
                    if entry["orig_start"] <= orig_s <= entry["orig_end"]:
                        fe = entry["final_end"]
                        break
            elif fs is None and fe is not None:
                for entry in timeline_map:
                    if entry["orig_start"] <= orig_e <= entry["orig_end"]:
                        fs = entry["final_start"]
                        break

            if fs is None or fe is None:
                drop_reason = "FAILED_TO_MAP_ORIG_TO_FINAL"
            elif fe <= fs:
                drop_reason = "START_GE_END"

        if idx < 3:
            _log_overlay_drop_diagnostics(idx, ov, fs, fe, drop_reason)

        if drop_reason:
            continue

        pl = ov.get("placement", {})
        logger.info(
            "overlay[%d] placement x=%.3f y=%.3f w=%.3f",
            idx, pl.get("x", 0), pl.get("y", 0), pl.get("w", 0),
        )

        mapped.append({
            "type": "image_overlay",
            "start": round(fs, 3),
            "end": round(fe, 3),
            "anchor_phrase": "",
            "keyword": "",
            "query": ov.get("image_prompt", ""),
            "source": "ai",
            "style_hint": "",
            "placement": pl,
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
            logger.info(
                "Timeline map (%d cuts): %s",
                len(tmap),
                ", ".join(
                    f"orig={e['orig_start']:.1f}-{e['orig_end']:.1f}->final={e['final_start']:.1f}-{e['final_end']:.1f}"
                    for e in tmap[:5]
                ),
            )

            if vd_overlays:
                overlay_items = _map_vd_overlays(vd_overlays, tmap)
                _log_mapping_examples("overlay", vd_overlays, overlay_items)
                overlay_items = _enforce_nonoverlap(overlay_items)
                # NOTE: MIN_BROLL_START is NOT applied to overlays.
                # Overlays are explicitly allowed at any time including [0.0, 3.0).
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


def _try_pexels_overlay(item) -> Optional[str]:
    """Try to find and download a Pexels photo for the overlay item.

    Returns local file path on success, None on failure.
    Only modifies item.asset_path and item.source — never touches
    placement, timing, or animation.
    """
    try:
        from apps.api.services.media_ranker.query_variants import variants
        from apps.api.services.media_ranker.pexels_client import (
            search_photos as mr_search_photos,
        )
        from apps.api.services.media_ranker.clip_ranker import rank_image_candidates

        query = item.query
        qvars = variants(query)
        logger.info(
            "Pexels overlay: query=%s variants=%d",
            query[:80], len(qvars),
        )

        # Pool candidates across variants (dedupe by id)
        seen_ids: set[int] = set()
        pool: list[dict] = []
        for v in qvars:
            results = mr_search_photos(v, per_page=CLIP_CANDIDATES_PER_VARIANT)
            for c in results:
                cid = c.get("id")
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    c["_variant"] = v
                    pool.append(c)

        logger.info(
            "Pexels overlay: pool=%d candidates for query=%s",
            len(pool), query[:80],
        )

        if not pool:
            return None

        # CLIP rank
        if CLIP_ENABLED:
            ranked = rank_image_candidates(pool, query=query, k=1)
        else:
            ranked = pool[:1]

        if not ranked:
            return None

        top = ranked[0]
        final_score = top.get("final_score", 0.0)
        pos_score = top.get("pos_score", 0.0)

        logger.info(
            "Pexels overlay top1: id=%s alt=%s pos=%.4f neg=%.4f "
            "clip=%.4f heur=%.4f final=%.4f variant=%s",
            top.get("id"), (top.get("alt") or "")[:60],
            top.get("pos_score", 0), top.get("neg_score", 0),
            top.get("clip_score", 0), top.get("heuristic_score", 0),
            final_score, top.get("variant_used", ""),
        )

        # Threshold check
        if final_score < 0.10 or pos_score < 0.20:
            logger.info(
                "Pexels overlay: below threshold (final=%.4f pos=%.4f), "
                "falling back to NanoBanana",
                final_score, pos_score,
            )
            return None

        # Download to overlay cache
        download_url = top.get("download_url")
        if not download_url:
            return None

        _OVERLAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ext = ".jpg"
        if ".png" in download_url.lower():
            ext = ".png"
        cache_key = hashlib.sha256(
            f"pexels:{top['id']}:{download_url}".encode()
        ).hexdigest()[:24]
        dest = _OVERLAY_CACHE_DIR / f"pexels_{cache_key}{ext}"

        if dest.exists():
            logger.info("Pexels overlay cache hit: %s", dest)
            return str(dest)

        from apps.api.services.media_ranker.http_utils import download_to_file
        ok = download_to_file(download_url, dest, timeout_s=10.0, retries=1)
        if ok and dest.exists():
            logger.info(
                "Pexels overlay downloaded: %s (id=%s)", dest, top.get("id"),
            )
            return str(dest)

        return None

    except Exception as exc:
        logger.warning("Pexels overlay attempt failed (non-fatal): %s", exc)
        return None


_LOGO_PROFILES = frozenset({"logo_badge", "brand_logo", "organization_logo"})


def _is_logo_overlay(item) -> bool:
    """Return True if the overlay should be sourced from Logo.dev."""
    ri = item.render_intent
    profile = ri.profile if hasattr(ri, "profile") else (ri or {}).get("profile", "")
    return profile in _LOGO_PROFILES


def _try_logo_dev_overlay(item) -> Optional[str]:
    """Try to fetch a Logo.dev logo for the overlay item.

    Returns local file path on success, None on failure.
    Only modifies item.asset_path — never touches placement, timing,
    or animation.
    """
    if not LOGO_DEV_PUBLISHABLE_KEY:
        return None

    try:
        from apps.api.integrations.logo_dev import fetch_logo_to_cache

        brand_name = item.query
        if not brand_name:
            return None

        result = fetch_logo_to_cache(brand_name, _OVERLAY_CACHE_DIR)
        if result and result.exists():
            return str(result)
        return None
    except Exception as exc:
        logger.warning("Logo.dev overlay attempt failed (non-fatal): %s", exc)
        return None


def _generate_overlay_assets(plan: EditPlan) -> None:
    """Best-effort: generate overlay images.

    Strategy per item (when source=="ai" and query exists):
      0) If overlay profile is a logo type (logo_badge/brand_logo/
         organization_logo) AND Logo.dev keys are set: try Logo.dev first.
         If Logo.dev fails, fall through to existing Pexels/NanoBanana
         pipeline as a fail-safe.
      1) If OVERLAY_SOURCE_PRIMARY=="pexels" and PEXELS_API_KEY set:
         try Pexels photo search + CLIP ranking.
      2) If Pexels fails or below threshold, fall back to NanoBanana
         (if OVERLAY_SOURCE_FALLBACK_AI is true).

    IMPORTANT: This function ONLY sets item.asset_path and item.source.
    It NEVER modifies placement, timing, animation, or any other field.
    """
    use_pexels = (
        OVERLAY_SOURCE_PRIMARY == "pexels"
        and bool(PEXELS_API_KEY)
    )

    for item in plan.overlays.items:
        if item.asset_path or not item.query:
            continue
        if item.source != "ai":
            continue

        chosen_source = None

        # Step 0: Logo.dev for logo-type overlays
        if _is_logo_overlay(item) and LOGO_DEV_PUBLISHABLE_KEY:
            logo_path = _try_logo_dev_overlay(item)
            if logo_path:
                item.asset_path = logo_path
                item.source = "logo_dev"
                chosen_source = "logo_dev"
                logger.info(
                    "Overlay source=logo_dev for query=%s", item.query[:80],
                )

        # Step A: Try Pexels first (skip for logo overlays already resolved)
        if not chosen_source and use_pexels:
            pexels_path = _try_pexels_overlay(item)
            if pexels_path:
                item.asset_path = pexels_path
                item.source = "pexels"
                chosen_source = "pexels"
                logger.info(
                    "Overlay source=pexels for query=%s", item.query[:80],
                )

        # Step B: Fall back to NanoBanana
        if not chosen_source and OVERLAY_SOURCE_FALLBACK_AI and _NB_KEY:
            overlay_dict = item.model_dump()
            path = _generate_overlay_image_from_item(overlay_dict)
            if path:
                item.asset_path = path
                chosen_source = "ai"
                logger.info(
                    "Overlay source=ai (NanoBanana) for query=%s",
                    item.query[:80],
                )

        if not chosen_source:
            logger.info(
                "Overlay: no asset generated for query=%s", item.query[:80],
            )


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
