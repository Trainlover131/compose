"""AI Edit Planner using Claude Haiku (with demo fallback).

Four-pass LLM flow:
  Pass 1   — main_cuts / punch_ins / captions / music  (broll + overlays empty)
  Pass 1.5 — semantic anchor discovery from transcript + analysis + prompt
  Pass 2   — overlay anchors (word-timestamp-locked, Claude fills creative fields)
  Pass 3   — b-roll anchors  (abstract-concept keywords, Claude fills queries)
"""

import base64
import hashlib
import json
import logging
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import anthropic

from apps.api.config import ANTHROPIC_API_KEY, DEMO_MODE, NANOBANANA_API_KEY, LOCAL_STORAGE_PATH
from apps.api.models.presets import get_preset
from apps.api.models.schemas import EditPlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Brand seed list (lowercase) – used for overlay vs b-roll classification
# ---------------------------------------------------------------------------
_BRAND_SEEDS: set[str] = {
    "y combinator", "yc", "jarvis", "tony stark", "iron man",
    "openai", "anthropic", "a16z", "sequoia", "google", "meta",
    "apple", "microsoft", "amazon", "tesla", "nvidia", "stripe",
}

_ABSTRACT_CONCEPTS: set[str] = {
    "momentum", "focus", "burnout", "discipline", "flow", "fear",
    "confidence", "vision", "anxiety", "strategy", "growth",
    "hustle", "grind", "mindset", "resilience", "ambition",
    "creativity", "failure", "success", "passion", "energy",
}

# ---------------------------------------------------------------------------
# Overlay cache directory
# ---------------------------------------------------------------------------
_OVERLAY_CACHE_DIR = (
    LOCAL_STORAGE_PATH / "overlay_cache"
    if LOCAL_STORAGE_PATH.exists()
    else Path("/tmp/overlay_cache")
)

# ===================================================================
# System prompt & schema  (updated with overlay + b-roll lock rules)
# ===================================================================

PLANNER_SYSTEM_PROMPT = """You are an expert short-form video editor AI. You receive a transcript with word-level timestamps, audio analysis data (silences, emphasis moments), a user prompt describing desired edits, and a style preset configuration.

Your job is to output a valid JSON EditPlan that follows the schema exactly. The plan determines how to edit the raw talking-head video into an engaging short-form clip (9:16, 1080x1920).

RULES:
1. Return ONLY valid JSON. No markdown, no explanation, no code fences.
2. main_cuts must be non-overlapping, sorted by start time, and their total duration >= 15s.
3. main_cuts total duration must be <= max_duration_sec from the preset.
4. Remove filler words, long silences, and boring parts based on the user prompt and preset.
5. punch_ins should target emphasis moments (loud/important words). Scale range from preset config.
6. b-roll inserts should NOT overlap with each other. They reference time in the FINAL timeline (after cuts).
7. b-roll queries should be concise search terms for stock video (Pexels).
8. Choose a music track_id from the available tracks that matches the preset mood.
9. Caption style should match the preset configuration.
10. The rationale should briefly explain the editing strategy.
11. overlays.items must be non-overlapping. They reference time in the FINAL timeline (after cuts).
12. OVERLAY TYPE RULES:
    - brand/product/proper noun keyword => type "image_overlay" (corner pop)
    - abstract concept keyword => type "video_overlay" (full-screen cutaway)
13. OVERLAY SOURCE RULES:
    - logo/HUD/UI style => source "ai"
    - generic footage style => source "pexels"
14. You may be given REQUIRED OVERLAY ANCHORS with exact start/end.
    If provided, create exactly ONE overlays.items entry per anchor.
    DO NOT CHANGE the start or end values. You may only fill: type, query, source, style_hint, placement, animation, notes.
15. You may be given REQUIRED BROLL ANCHORS with exact start/end.
    If provided, create exactly ONE broll.inserts entry per anchor.
    DO NOT CHANGE the start or end values. You may only fill: query, keywords, source, notes.

Available music tracks: upbeat-energy, cinematic-ambient, clean-podcast, luxury-smooth, study-lofi"""

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
# Deterministic helpers – word extraction, keyword detection, anchoring
# ===================================================================

def _extract_words(transcript: dict) -> list[dict]:
    """Extract word-level {word, start, end} from transcript.

    Fallback: if no word-level timestamps exist, synthesise pseudo-words
    from segment-level text+timing so anchors can still be produced.
    """
    words: list[dict] = []
    for seg in transcript.get("segments", []):
        seg_words = seg.get("words", [])
        if seg_words:
            for w in seg_words:
                word_text = w.get("word", "").strip()
                if word_text and "start" in w and "end" in w:
                    words.append({"word": word_text, "start": w["start"], "end": w["end"]})
        else:
            # Fallback: split segment text into pseudo-words with interpolated timing
            text = seg.get("text", "").strip()
            if not text:
                continue
            tokens = text.split()
            if not tokens:
                continue
            seg_start = seg["start"]
            seg_end = seg["end"]
            seg_dur = seg_end - seg_start
            per_word = seg_dur / len(tokens) if len(tokens) > 0 else seg_dur
            for i, tok in enumerate(tokens):
                words.append({
                    "word": tok,
                    "start": round(seg_start + i * per_word, 3),
                    "end": round(seg_start + (i + 1) * per_word, 3),
                })
    return words


def _normalize_token(s: str) -> str:
    """Lowercase and strip non-alphanumeric edges."""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _extract_overlay_keywords_from_prompt(prompt: str) -> list[str]:
    """Extract overlay-worthy keywords from the user prompt.

    Sources:
      1. Quoted phrases  ("like this")
      2. Brand seed list matches
      3. Capitalized multi-word phrases heuristic
    Returns de-duped list (normalised).
    """
    kws: list[str] = []

    # 1. Quoted phrases
    for m in re.finditer(r'"([^"]+)"', prompt):
        kws.append(m.group(1).strip())
    for m in re.finditer(r"'([^']+)'", prompt):
        kws.append(m.group(1).strip())

    # 2. Brand seed matches present in prompt
    prompt_lower = prompt.lower()
    for brand in _BRAND_SEEDS:
        if brand in prompt_lower:
            kws.append(brand)

    # 3. Capitalized phrases (2+ words starting with uppercase)
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", prompt):
        kws.append(m.group(1).strip())

    # 4. Single capitalized words that aren't common English starts
    _STOP = {"the", "a", "an", "i", "my", "we", "he", "she", "it", "is", "am",
             "are", "was", "were", "be", "do", "does", "did", "will", "can",
             "make", "create", "edit", "cut", "add", "remove", "this", "that"}
    for m in re.finditer(r"\b([A-Z][a-z]{2,})\b", prompt):
        word = m.group(1)
        if word.lower() not in _STOP:
            kws.append(word)

    # Normalise + dedupe preserving order
    seen: set[str] = set()
    result: list[str] = []
    for kw in kws:
        n = _normalize_token(kw)
        if n and n not in seen:
            seen.add(n)
            result.append(n)
    return result


def _find_keyword_hits(words: list[dict], keyword: str) -> list[dict]:
    """Find occurrences of *keyword* (possibly multi-word) in *words*.

    Returns list of {word, start, end} where start/end span the full match.
    """
    tokens = _normalize_token(keyword).split()
    if not tokens:
        return []
    hits: list[dict] = []
    n = len(tokens)
    for i in range(len(words) - n + 1):
        match = True
        for j in range(n):
            if _normalize_token(words[i + j]["word"]) != tokens[j]:
                match = False
                break
        if match:
            phrase = " ".join(words[i + j]["word"] for j in range(n))
            hits.append({
                "word": phrase,
                "start": words[i]["start"],
                "end": words[i + n - 1]["end"],
            })
    return hits


def _filter_nonoverlapping_anchors(anchors: list[dict], min_gap_s: float = 0.0) -> list[dict]:
    """Given anchors sorted by orig_start, drop any that overlap the previous kept anchor.

    Invariant enforced:
      next.orig_start >= prev.orig_end (+ optional min_gap_s)
    """
    if not anchors:
        return []

    anchors = sorted(anchors, key=lambda a: a["orig_start"])
    kept: list[dict] = [anchors[0]]

    for a in anchors[1:]:
        prev = kept[-1]
        if a["orig_start"] < (prev["orig_end"] + min_gap_s):
            continue
        kept.append(a)

    return kept


def _make_anchor_windows(
    transcript: dict,
    prompt: str,
    max_anchors: int = 8,
    logo_dur_s: float = 1.2,
    pad_before: float = 0.15,
) -> list[dict]:
    """Build overlay anchor windows in the ORIGINAL video timeline.

    Returns [{keyword, anchor_phrase, orig_start, orig_end}, ...]
    """
    words = _extract_words(transcript)
    if not words:
        return []

    keywords = _extract_overlay_keywords_from_prompt(prompt)

    # Also scan transcript itself for brand seeds
    all_text_lower = " ".join(w["word"] for w in words).lower()
    existing = {_normalize_token(k) for k in keywords}
    for brand in _BRAND_SEEDS:
        n = _normalize_token(brand)
        if n in all_text_lower and n not in existing:
            keywords.append(n)
            existing.add(n)

    anchors: list[dict] = []
    used_starts: set[float] = set()

    for kw in keywords:
        hits = _find_keyword_hits(words, kw)
        for hit in hits:
            # Dedupe by rough start time (avoid two anchors on same word)
            rounded = round(hit["start"], 1)
            if rounded in used_starts:
                continue
            used_starts.add(rounded)

            candidate_start = round(max(0.0, hit["start"] - pad_before), 3)
            candidate_end = round(hit["start"] - pad_before + logo_dur_s, 3)

            anchors.append({
                "keyword": kw,
                "anchor_phrase": hit["word"],
                "orig_start": candidate_start,
                "orig_end": candidate_end,
            })

            if len(anchors) >= max_anchors:
                break
        if len(anchors) >= max_anchors:
            break

    # Sort + hard enforce non-overlap chronologically (order-independent)
    anchors = _filter_nonoverlapping_anchors(anchors)

    # Enforce max_anchors after filtering (filtering can only reduce count)
    return anchors[:max_anchors]

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
    """Map a single original-timeline timestamp to final timeline. None if outside all cuts."""
    for entry in timeline_map:
        if entry["orig_start"] <= orig_t <= entry["orig_end"]:
            return entry["final_start"] + (orig_t - entry["orig_start"])
    return None


def _anchors_to_final_timeline(anchors: list[dict], main_cuts: list) -> list[dict]:
    """Convert orig_start/orig_end anchors to final-timeline start/end.

    Drops anchors that fall entirely outside the kept cuts.
    """
    tmap = _build_timeline_map_from_cuts(main_cuts)
    result: list[dict] = []
    for a in anchors:
        fs = _map_time(a["orig_start"], tmap)
        fe = _map_time(a["orig_end"], tmap)
        if fs is None:
            # Try mapping just the start of the spoken word (orig_start + pad_before)
            fs = _map_time(a["orig_start"] + 0.15, tmap)
        if fs is None or fe is None:
            continue
        if fe <= fs:
            continue
        result.append({
            "keyword": a["keyword"],
            "anchor_phrase": a.get("anchor_phrase", a["keyword"]),
            "start": round(fs, 3),
            "end": round(fe, 3),
        })
    return result


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
            # Ensure prev still has positive duration
            if prev["end"] <= prev["start"]:
                prev["end"] = round(prev["start"] + 0.1, 3)

    return items


# ===================================================================
# Brand-like vs abstract-concept classification
# ===================================================================

def _is_brand_like(keyword: str) -> bool:
    kw = _normalize_token(keyword)
    if kw in _BRAND_SEEDS:
        return True
    # All-caps acronym up to 5 chars
    if keyword.isupper() and len(keyword) <= 5 and keyword.isalpha():
        return True
    # Contains digits (version numbers, product IDs)
    if any(c.isdigit() for c in keyword):
        return True
    return False


def _is_abstract_concept(keyword: str) -> bool:
    kw = _normalize_token(keyword)
    if not kw:
        return False
    if _is_brand_like(keyword):
        return False
    if kw in _ABSTRACT_CONCEPTS:
        return True
    # Heuristic: single lowercase word >= 4 chars that isn't brand-like
    if " " not in kw and len(kw) >= 4:
        return True
    return False


def _build_broll_anchors(
    orig_anchors: list[dict],
    main_cuts: list,
    broll_dur_s: float = 1.6,
    pad_before: float = 0.10,
) -> list[dict]:
    """Select abstract-concept anchors and create b-roll timing windows.

    B-roll duration = min(broll_dur_s, remaining cut duration after anchor start).
    Returns anchors in ORIGINAL timeline with orig_start/orig_end.
    """
    tmap = _build_timeline_map_from_cuts(main_cuts)
    result: list[dict] = []

    for a in orig_anchors:
        if not _is_abstract_concept(a["keyword"]):
            continue

        # Find which cut this anchor falls in to compute remaining duration
        anchor_t = a["orig_start"]
        remaining = broll_dur_s
        for entry in tmap:
            if entry["orig_start"] <= anchor_t <= entry["orig_end"]:
                remaining = min(broll_dur_s, entry["orig_end"] - anchor_t)
                break

        if remaining < 0.3:
            continue

        result.append({
            "keyword": a["keyword"],
            "anchor_phrase": a.get("anchor_phrase", a["keyword"]),
            "orig_start": round(max(0.0, anchor_t - pad_before), 3),
            "orig_end": round(max(0.0, anchor_t - pad_before) + remaining, 3),
        })

    return result


# ===================================================================
# NanoBanana image generation (best-effort, never breaks pipeline)
# ===================================================================

def _nanobanana_cache_key(query: str, style_hint: str, placement_w: float) -> str:
    raw = f"{query}|{style_hint}|{placement_w:.2f}|9:16"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def _nanobanana_poll_result_url(task_id: str, timeout_s: float = 30.0) -> Optional[str]:
    """Poll NanoBanana record-info until the task completes. Return result image URL or None."""
    if not NANOBANANA_API_KEY or not task_id:
        return None

    deadline = time.time() + timeout_s
    last_err: Optional[str] = None

    while time.time() < deadline:
        try:
            url = f"https://api.nanobananaapi.ai/api/v1/nanobanana/record-info?taskId={task_id}"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {NANOBANANA_API_KEY}"},
                method="GET",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            # Defensive parsing
            payload = data.get("data", data) if isinstance(data, dict) else {}
            if not isinstance(payload, dict):
                payload = {}

            # Try all common URL keys
            result_url = (
                payload.get("resultImageUrl")
                or payload.get("resultImageURL")
                or payload.get("imageUrl")
                or payload.get("image_url")
                or payload.get("url")
            )

            success_flag = payload.get("successFlag")
            top_level_code = data.get("code") if isinstance(data, dict) else None

            # -------------------------
            # SUCCESS CONDITION
            # -------------------------
            # If we have a valid URL, we consider it done.
            if isinstance(result_url, str) and result_url.startswith("http"):
                return result_url

            # -------------------------
            # EXPLICIT FAILURE
            # -------------------------
            # successFlag meanings often:
            #   0 = processing
            #   1 = success
            #  -1 or 2 = failed
            if success_flag in (-1, 2):
                last_err = f"task failed (successFlag={success_flag})"
                break

            # Some APIs signal failure via top-level code
            if top_level_code and top_level_code not in (0, 200):
                last_err = f"task failed (code={top_level_code})"
                break

            # -------------------------
            # STILL PROCESSING
            # -------------------------
            time.sleep(1.0)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:800]
            last_err = f"HTTPError polling record-info: {e.code} body={body}"

            # If auth blocked, stop immediately
            if e.code in (401, 403):
                break

            time.sleep(1.0)

        except Exception as e:
            last_err = f"poll error: {e}"
            time.sleep(1.0)

    if last_err:
        logger.warning(f"NanoBanana poll failed: {last_err} (taskId={task_id})")

    return None

def _generate_overlay_image(query: str, style_hint: str, placement_w: float) -> Optional[str]:
    """Generate an overlay image via NanoBanana API. Returns local path or None."""
    if not NANOBANANA_API_KEY:
        return None

    _OVERLAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = _nanobanana_cache_key(query, style_hint, placement_w)
    cached = _OVERLAY_CACHE_DIR / f"{cache_key}.png"
    if cached.exists():
        logger.info(f"Overlay cache hit: {cached}")
        return str(cached)

    try:
        payload = json.dumps({
            "prompt": query,
            "numImages": 1,
            "type": "TEXTTOIAMGE",
            "image_size": "9:16",
        }).encode()

        req = urllib.request.Request(
            "https://api.nanobananaapi.ai/api/v1/nanobanana/generate",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {NANOBANANA_API_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:800]
            logger.warning(f"NanoBanana API HTTP {e.code}: {body}")
            return None

        # Try to extract image URL or base64 from response
        image_url = None
        image_b64 = None

        # Common response shapes
        if isinstance(data, dict):
            # Direct URL in response
            for key in ("url", "image_url", "imageUrl", "output"):
                if key in data and isinstance(data[key], str) and data[key].startswith("http"):
                    image_url = data[key]
                    break
            # Check nested images array
            images = data.get("images", data.get("results", []))
            if isinstance(images, list) and images:
                item = images[0]
                if isinstance(item, str):
                    if item.startswith("http"):
                        image_url = item
                    else:
                        image_b64 = item
                elif isinstance(item, dict):
                    image_url = item.get("url") or item.get("image_url")
                    image_b64 = item.get("base64") or item.get("b64")
            # Direct base64
            if not image_url and not image_b64:
                image_b64 = data.get("base64") or data.get("image_base64")

            # If async taskId returned, poll record-info for the result URL
            if not image_url and not image_b64:
                task_id = None
                if isinstance(data, dict):
                    # taskId may live at data["taskId"] or data["data"]["taskId"]
                    task_id = data.get("taskId")
                    if not task_id and isinstance(data.get("data"), dict):
                        task_id = data["data"].get("taskId")

                if task_id:
                    result_url = _nanobanana_poll_result_url(str(task_id), timeout_s=30.0)
                    if result_url:
                        img_req = urllib.request.Request(result_url)
                        with urllib.request.urlopen(img_req, timeout=30) as img_resp:
                            cached.write_bytes(img_resp.read())
                        logger.info(f"Overlay image downloaded via async poll: {cached}")
                        return str(cached)

                    logger.warning(f"NanoBanana async task did not produce a result within timeout (taskId={task_id})")
                    return None

        if image_url:
            img_req = urllib.request.Request(image_url)
            with urllib.request.urlopen(img_req, timeout=30) as img_resp:
                cached.write_bytes(img_resp.read())
            logger.info(f"Overlay image downloaded: {cached}")
            return str(cached)

        if image_b64:
            cached.write_bytes(base64.b64decode(image_b64))
            logger.info(f"Overlay image decoded from base64: {cached}")
            return str(cached)

        logger.warning(f"NanoBanana response had no usable image data: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return None

    except Exception as e:
        logger.warning(f"NanoBanana generation failed (non-fatal): {e}")
        return None


# ===================================================================
# LLM helper: call Claude and parse JSON
# ===================================================================

def _strip_fences(raw: str) -> str:
    """Remove markdown code fences from an LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return raw.strip()


def _call_claude(client: anthropic.Anthropic, system: str, user_msg: str, max_tokens: int = 4096) -> Optional[str]:
    """Call Claude Haiku and return the raw text response, or None on failure."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Claude call failed: {e}")
        return None


# ===================================================================
# Deterministic fallback builders
# ===================================================================

def _fallback_overlays(final_anchors: list[dict]) -> list[dict]:
    """Build deterministic overlay items when Claude fails or changes timing."""
    items = []
    for a in final_anchors:
        items.append({
            "type": "image_overlay",
            "start": a["start"],
            "end": a["end"],
            "anchor_phrase": a.get("anchor_phrase", ""),
            "keyword": a["keyword"],
            "query": f"Minimal {a['keyword']} logo sticker, flat, white, transparent background",
            "source": "ai",
            "style_hint": "logo",
            "placement": {"x": 0.82, "y": 0.12, "w": 0.18},
            "animation": {"fade_in": 0.12, "fade_out": 0.12},
            "notes": "deterministic fallback",
        })
    return _enforce_nonoverlap(items)


def _fallback_broll(final_anchors: list[dict]) -> list[dict]:
    """Build deterministic b-roll inserts when Claude fails or changes timing."""
    items = []
    for a in final_anchors:
        items.append({
            "start": a["start"],
            "end": a["end"],
            "query": f"{a['keyword']} cinematic b-roll",
            "keywords": [a["keyword"]],
            "source": "pexels",
            "notes": "fallback b-roll",
        })
    return _enforce_nonoverlap(items)


# ===================================================================
# Validation helpers for Claude's overlay / b-roll responses
# ===================================================================

_TIMING_TOLERANCE = 0.05  # seconds

def _validate_claude_overlays(
    claude_items: list[dict],
    required_anchors: list[dict],
) -> bool:
    """Return True if Claude returned exactly one item per anchor with unchanged timing
    and valid placement/animation dict shapes."""
    if len(claude_items) != len(required_anchors):
        return False

    for ci, ra in zip(
        sorted(claude_items, key=lambda x: x.get("start", 0)),
        sorted(required_anchors, key=lambda x: x["start"]),
    ):
        # Timing must match anchors
        if abs(ci.get("start", -1) - ra["start"]) > _TIMING_TOLERANCE:
            return False
        if abs(ci.get("end", -1) - ra["end"]) > _TIMING_TOLERANCE:
            return False
        # Validate placement is a dict with numeric x, y, w in [0, 1]
        pl = ci.get("placement")
        if not isinstance(pl, dict):
            return False
        for k in ("x", "y", "w"):
            v = pl.get(k)
            if not isinstance(v, (int, float)) or v < 0 or v > 1:
                return False
        # Validate animation is a dict with numeric fade_in, fade_out >= 0
        an = ci.get("animation")
        if not isinstance(an, dict):
            return False
        for k in ("fade_in", "fade_out"):
            v = an.get(k)
            if not isinstance(v, (int, float)) or v < 0:
                return False
    return True


def _validate_claude_broll(
    claude_inserts: list[dict],
    required_anchors: list[dict],
) -> bool:
    """Return True if Claude returned inserts matching anchor timing exactly."""
    if len(claude_inserts) != len(required_anchors):
        return False
    for ci, ra in zip(
        sorted(claude_inserts, key=lambda x: x.get("start", 0)),
        sorted(required_anchors, key=lambda x: x["start"]),
    ):
        if abs(ci.get("start", -1) - ra["start"]) > _TIMING_TOLERANCE:
            return False
        if abs(ci.get("end", -1) - ra["end"]) > _TIMING_TOLERANCE:
            return False
    return True


# ===================================================================
# Pass 1.5 — Semantic anchor discovery + deterministic locking
# ===================================================================

_ANCHOR_REQUEST_TERMS = frozenset({
    "overlay", "overlays", "logo", "jarvis", "b-roll", "broll",
    "cutaway", "insert", "stock footage", "pexels",
})


def _prompt_requests_anchors(prompt: str) -> bool:
    """Check if user prompt mentions overlay or b-roll concepts."""
    prompt_lower = prompt.lower()
    return any(term in prompt_lower for term in _ANCHOR_REQUEST_TERMS)


def _parse_anchor_candidates(raw_json: str) -> list[dict]:
    """Parse and validate anchor candidates from Claude's raw JSON response."""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return []

    # Accept {"anchors": [...]} or [...] directly
    if isinstance(data, dict):
        candidates = data.get("anchors", [])
    elif isinstance(data, list):
        candidates = data
    else:
        return []

    _REQUIRED = {"kind", "orig_time", "keyword"}
    result: list[dict] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        if not _REQUIRED.issubset(c):
            continue
        kind = c["kind"]
        if kind not in ("overlay", "broll"):
            continue
        try:
            orig_time = float(c["orig_time"])
        except (ValueError, TypeError):
            continue
        conf = max(0.0, min(1.0, float(c.get("confidence", 0.5))))
        result.append({
            "kind": kind,
            "orig_time": orig_time,
            "anchor_phrase": str(c.get("anchor_phrase", "")),
            "keyword": str(c["keyword"]),
            "reason": str(c.get("reason", "")),
            "confidence": conf,
        })

    result.sort(key=lambda x: x["orig_time"])
    return result


_PASS15_SYSTEM = (
    "You are a video editing anchor-discovery assistant. Given a transcript, "
    "audio emphasis data, and user editing prompt, identify semantic anchor "
    "moments where visual overlays or b-roll cutaways should appear in the "
    "ORIGINAL video timeline.\n\n"
    "RULES:\n"
    "1. Return ONLY valid JSON: {\"anchors\": [...]}.\n"
    "2. Each anchor object: {\"kind\":\"overlay\"|\"broll\", \"orig_time\":<float>, "
    "\"anchor_phrase\":\"<phrase from transcript or paraphrase>\", "
    "\"keyword\":\"<concept>\", \"reason\":\"<short>\", \"confidence\":<0..1>}.\n"
    "3. orig_time = seconds in the ORIGINAL video timeline where the concept "
    "is mentioned or implied.\n"
    "4. Do NOT output start/end windows — only a single orig_time per anchor.\n"
    "5. Account for ASR errors: 'YC' may appear as 'why see', 'Y C', "
    "'white sea', etc. Match semantically, not literally.\n"
    "6. Brand / product / proper noun → kind \"overlay\".\n"
    "7. Abstract concept / activity / profession → kind \"broll\".\n"
    "8. No markdown, no explanation — ONLY the JSON object."
)


def _discover_anchors_with_claude(
    client: anthropic.Anthropic,
    transcript: dict,
    analysis: dict,
    prompt: str,
    max_anchors: int = 10,
) -> dict:
    """Pass 1.5: Semantic anchor discovery using Claude.

    Returns {"overlay": [AnchorCandidate...], "broll": [AnchorCandidate...]}.
    """
    empty: dict = {"overlay": [], "broll": []}

    if not _prompt_requests_anchors(prompt):
        return empty

    compressed = _compress_transcript(transcript)
    emphasis = analysis.get("emphasis_moments", [])
    emph_summary = (
        ", ".join(f"{m['time']:.1f}s" for m in emphasis[:15])
        if emphasis else "none"
    )

    user_msg = (
        f"USER EDITING PROMPT: {prompt}\n\n"
        f"TRANSCRIPT (timestamps in seconds):\n{compressed}\n\n"
        f"EMPHASIS MOMENTS (times): {emph_summary}\n\n"
        f"Identify up to {max_anchors} anchor moments where the user's "
        f"requested overlays or b-roll should appear. Return ONLY JSON."
    )

    raw = _call_claude(client, _PASS15_SYSTEM, user_msg, max_tokens=2048)
    if not raw:
        return empty

    raw = _strip_fences(raw)
    candidates = _parse_anchor_candidates(raw)

    result: dict = {"overlay": [], "broll": []}
    for c in candidates:
        result[c["kind"]].append(c)
    return result


def _nearest_word_at_time(words: list[dict], t: float) -> Optional[dict]:
    """Choose word whose midpoint is closest to t. Return None if no words."""
    if not words:
        return None
    best = None
    best_dist = float("inf")
    for w in words:
        mid = (w["start"] + w["end"]) / 2.0
        d = abs(mid - t)
        if d < best_dist:
            best_dist = d
            best = w
    return best


def _snap_time_to_nearest_word_or_emphasis(
    words: list[dict],
    emphasis_moments: list[dict],
    t: float,
) -> float:
    """Snap t to nearest word start or emphasis moment time."""
    if words:
        w = _nearest_word_at_time(words, t)
        if w is not None:
            return w["start"]
    if emphasis_moments:
        best_t = t
        best_dist = float("inf")
        for m in emphasis_moments:
            d = abs(m["time"] - t)
            if d < best_dist:
                best_dist = d
                best_t = m["time"]
        return best_t
    return t


def _lock_candidates_to_anchor_windows(
    candidates: list[dict],
    transcript: dict,
    analysis: dict,
    max_anchors: int,
    win_dur_s: float,
    pad_before: float,
) -> list[dict]:
    """Convert Pass 1.5 candidates into deterministic locked anchor windows."""
    if not candidates:
        return []

    words = _extract_words(transcript)
    emphasis = analysis.get("emphasis_moments", [])

    anchors: list[dict] = []
    used_starts: set[float] = set()

    for c in candidates:
        snapped_t = _snap_time_to_nearest_word_or_emphasis(
            words, emphasis, c["orig_time"],
        )

        # Use nearest word text if available; otherwise keep candidate phrase
        nearest = _nearest_word_at_time(words, snapped_t) if words else None
        anchor_phrase = nearest["word"] if nearest else c.get("anchor_phrase", "")

        keyword = _normalize_token(c.get("keyword", ""))
        if not keyword:
            continue

        orig_start = round(max(0.0, snapped_t - pad_before), 3)
        orig_end = round(orig_start + win_dur_s, 3)

        # Deduplicate by rounded orig_start (0.1s granularity)
        rounded = round(orig_start, 1)
        if rounded in used_starts:
            continue
        used_starts.add(rounded)

        anchors.append({
            "keyword": keyword,
            "anchor_phrase": anchor_phrase,
            "orig_start": orig_start,
            "orig_end": orig_end,
        })

    # Enforce non-overlap and truncate
    anchors = _filter_nonoverlapping_anchors(anchors, min_gap_s=0.05)
    return anchors[:max_anchors]


# ===================================================================
# Existing helper functions (unchanged)
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
    lines = [f"  {s['start']:.1f}-{s['end']:.1f}s ({s['duration']:.1f}s)" for s in silences[:20]]
    return f"{len(silences)} silences found:\n" + "\n".join(lines)


def _summarize_emphasis(analysis: dict) -> str:
    moments = analysis.get("emphasis_moments", [])
    if not moments:
        return "No emphasis moments detected."
    lines = [f"  {m['time']:.1f}s (strength: {m['strength']:.1f}x)" for m in moments[:20]]
    return f"{len(moments)} emphasis moments:\n" + "\n".join(lines)


# ===================================================================
# Main entry point — three-pass plan_edit()
# ===================================================================

def plan_edit(
    transcript: dict,
    analysis: dict,
    prompt: str,
    preset_id: str,
    video_duration: float,
) -> EditPlan:
    """Generate an EditPlan using Claude Haiku (4-pass) or demo fallback."""
    if DEMO_MODE:
        logger.info("Demo mode: using rule-based planner")
        return _demo_plan(transcript, analysis, preset_id, video_duration)

    preset = get_preset(preset_id) or get_preset("snappy-creator")
    config = preset["config"]

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ---------------------------------------------------------------
    # PASS 1:  main_cuts / punch_ins / captions / music
    #          (broll empty, overlays empty — timing decided later)
    # ---------------------------------------------------------------
    compressed_transcript = _compress_transcript(transcript)
    silence_summary = _summarize_silences(analysis)
    emphasis_summary = _summarize_emphasis(analysis)

    pass1_msg = f"""Create an EditPlan for this video.

VIDEO DURATION: {video_duration:.1f}s

USER PROMPT: {prompt}

PRESET: {preset_id}
PRESET CONFIG: {json.dumps(config, indent=2)}

TRANSCRIPT (with timestamps):
{compressed_transcript}

SILENCE ANALYSIS:
{silence_summary}

EMPHASIS MOMENTS:
{emphasis_summary}

OUTPUT SCHEMA:
{EDIT_PLAN_SCHEMA}

IMPORTANT: Set broll.enabled=false and broll.inserts=[] (b-roll timing will be added in a later pass).
Set overlays.enabled=false and overlays.items=[] (overlays will be added in a later pass).
Focus on main_cuts, punch_ins, captions, and music.

Generate the EditPlan JSON now. Remember: ONLY valid JSON, no markdown."""

    plan = None
    for attempt in range(2):
        raw = _call_claude(client, PLANNER_SYSTEM_PROMPT, pass1_msg)
        if raw is None:
            break
        try:
            raw = _strip_fences(raw)
            plan_data = json.loads(raw)

            # Ensure broll/overlays are present and EMPTY for pass 1
            # (timing/contents added deterministically in later passes)
            if not isinstance(plan_data.get("broll"), dict):
                plan_data["broll"] = {}
            plan_data["broll"]["enabled"] = False
            plan_data["broll"]["strategy"] = plan_data["broll"].get("strategy", "cutaway_fullscreen")
            plan_data["broll"]["inserts"] = []

            if not isinstance(plan_data.get("overlays"), dict):
                plan_data["overlays"] = {}
            plan_data["overlays"]["enabled"] = False
            plan_data["overlays"]["items"] = []

            plan = EditPlan.model_validate(plan_data)

            if plan.total_duration() < 10:
                raise ValueError("Plan total duration too short (< 10s)")

            logger.info(
                f"Pass 1 plan: {len(plan.main_cuts)} cuts, "
                f"{len(plan.punch_ins)} punch-ins"
            )
            break
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Pass 1 attempt {attempt + 1} failed: {e}. Retrying...")
                pass1_msg = (
                    f"The previous JSON was invalid: {str(e)}\n\n"
                    f"Fix it to valid JSON matching the schema. Do not change the meaning.\n\n"
                    f"Previous response:\n{raw}\n\n"
                    f"Return ONLY valid JSON."
                )
            else:
                logger.error(f"Pass 1 failed after 2 attempts: {e}")

    if plan is None:
        logger.info("Pass 1 failed, falling back to demo planner")
        plan = _demo_plan(transcript, analysis, preset_id, video_duration)

    # ---------------------------------------------------------------
    # PASS 1.5:  Semantic anchor discovery + deterministic locking
    # ---------------------------------------------------------------
    discovered = _discover_anchors_with_claude(
        client, transcript, analysis, prompt, max_anchors=10,
    )
    overlay_candidates = discovered["overlay"]
    broll_candidates = discovered["broll"]
    logger.info(f"Pass 1.5 candidates: overlays={len(overlay_candidates)}, broll={len(broll_candidates)}")

    orig_overlay_anchors = _lock_candidates_to_anchor_windows(
        overlay_candidates, transcript, analysis,
        max_anchors=8, win_dur_s=1.2, pad_before=0.15,
    )
    orig_broll_anchors = _lock_candidates_to_anchor_windows(
        broll_candidates, transcript, analysis,
        max_anchors=6, win_dur_s=1.6, pad_before=0.10,
    )

    # Fallback to existing deterministic methods if Pass 1.5 returned nothing
    _wants_anchors = _prompt_requests_anchors(prompt)
    if not orig_overlay_anchors and _wants_anchors:
        orig_overlay_anchors = _make_anchor_windows(
            transcript, prompt, max_anchors=8, logo_dur_s=1.2,
        )
    if not orig_broll_anchors and _wants_anchors:
        _fb_anchors = orig_overlay_anchors or _make_anchor_windows(
            transcript, prompt, max_anchors=8, logo_dur_s=1.2,
        )
        orig_broll_anchors = _build_broll_anchors(
            _fb_anchors, plan.main_cuts, broll_dur_s=1.6,
        )
    logger.info(f"Pass 1.5 locked anchors: overlays={len(orig_overlay_anchors)}, broll={len(orig_broll_anchors)}")

    # ---------------------------------------------------------------
    # PASS 2:  Overlays (word-timestamp-locked)
    # ---------------------------------------------------------------
    final_overlay_anchors = _anchors_to_final_timeline(orig_overlay_anchors, plan.main_cuts)
    # do NOT enforce non-overlap on anchors; enforce on overlay_items later

    overlay_items: list[dict] = []
    if final_overlay_anchors:
        anchors_desc = "\n".join(
            f"  ANCHOR {i+1}: keyword=\"{a['keyword']}\", "
            f"anchor_phrase=\"{a.get('anchor_phrase','')}\", "
            f"start={a['start']:.3f}, end={a['end']:.3f}"
            for i, a in enumerate(final_overlay_anchors)
        )

        pass2_msg = f"""You are given REQUIRED OVERLAY ANCHORS with exact start/end times.
Create exactly ONE overlays.items entry per anchor.
DO NOT CHANGE the start or end values.
You may fill: type, query, source, style_hint, placement, animation, notes, keyword, anchor_phrase.

USER PROMPT: {prompt}

REQUIRED OVERLAY ANCHORS:
{anchors_desc}

Return ONLY a JSON object:
{{"overlays": {{"enabled": true, "items": [...]}}}}

Rules:
- brand/product/proper noun keyword => type "image_overlay", source "ai"
- abstract concept keyword => type "video_overlay", source "pexels"
- DO NOT change start or end values.
- placement MUST be a JSON object with numeric keys: {{"x": <0..1>, "y": <0..1>, "w": <0..1>}}. NEVER a string like "top-right".
- animation MUST be a JSON object with numeric keys: {{"fade_in": <float>, "fade_out": <float>}}. NEVER a string like "fade-in".
- Return ONLY valid JSON, no markdown."""

        raw2 = _call_claude(client, PLANNER_SYSTEM_PROMPT, pass2_msg, max_tokens=2048)
        if raw2:
            try:
                raw2 = _strip_fences(raw2)
                overlay_data = json.loads(raw2)
                claude_items = overlay_data.get("overlays", {}).get("items", [])

                if _validate_claude_overlays(claude_items, final_overlay_anchors):
                    # Keep exact locked timing (do NOT shift)
                    overlay_items = claude_items
                    logger.info(f"Pass 2: Claude returned {len(overlay_items)} valid overlays")
                else:
                    logger.warning("Pass 2: Claude changed overlay timing or count, using fallback")
                    overlay_items = _fallback_overlays(final_overlay_anchors)

            except Exception as e:
                logger.warning(f"Pass 2 overlay parse failed: {e}, using fallback")
                overlay_items = _fallback_overlays(final_overlay_anchors)
        else:
            overlay_items = _fallback_overlays(final_overlay_anchors)
    # ---------------------------------------------------------------
    # PASS 3:  B-roll timing lock (orig_broll_anchors from Pass 1.5)
    # ---------------------------------------------------------------
    final_broll_anchors = _anchors_to_final_timeline(orig_broll_anchors, plan.main_cuts)
    

    broll_inserts: list[dict] = []
    if final_broll_anchors:
        broll_desc = "\n".join(
            f"  ANCHOR {i+1}: keyword=\"{a['keyword']}\", "
            f"start={a['start']:.3f}, end={a['end']:.3f}"
            for i, a in enumerate(final_broll_anchors)
        )

        pass3_msg = f"""You are given REQUIRED BROLL ANCHORS with exact start/end times.
Create exactly ONE broll.inserts entry per anchor.
DO NOT CHANGE the start or end values.
You may ONLY fill: query, keywords, source, notes.

USER PROMPT: {prompt}

REQUIRED BROLL ANCHORS:
{broll_desc}

Return ONLY a JSON object:
{{"broll": {{"enabled": true, "strategy": "cutaway_fullscreen", "inserts": [...]}}}}

Rules:
- query should be concise Pexels search terms for the concept
- source should be "pexels"
- DO NOT change start or end values.
- Return ONLY valid JSON, no markdown."""

        raw3 = _call_claude(client, PLANNER_SYSTEM_PROMPT, pass3_msg, max_tokens=2048)
        if raw3:
            try:
                raw3 = _strip_fences(raw3)
                broll_data = json.loads(raw3)
                claude_inserts = broll_data.get("broll", {}).get("inserts", [])

                if _validate_claude_broll(claude_inserts, final_broll_anchors):
                    # Keep exact locked timing (do NOT shift)
                    broll_inserts = claude_inserts
                    logger.info(f"Pass 3: Claude returned {len(broll_inserts)} valid b-roll inserts")
                else:
                    logger.warning("Pass 3: Claude changed b-roll timing or count, using fallback")
                    broll_inserts = _fallback_broll(final_broll_anchors)

            except Exception as e:
                logger.warning(f"Pass 3 b-roll parse failed: {e}, using fallback")
                broll_inserts = _fallback_broll(final_broll_anchors)
        else:
            broll_inserts = _fallback_broll(final_broll_anchors)

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
    # Best-effort NanoBanana asset generation for AI overlays
    # ---------------------------------------------------------------
    if plan.overlays.enabled and plan.overlays.items:
        _generate_overlay_assets(plan)

    logger.info(
        f"Final plan: {len(plan.main_cuts)} cuts, "
        f"{len(plan.punch_ins)} punch-ins, "
        f"{len(plan.broll.inserts)} b-roll, "
        f"{len(plan.overlays.items)} overlays"
    )
    return plan


def _generate_overlay_assets(plan: EditPlan) -> None:
    """Best-effort: generate NanoBanana images for AI-sourced overlays."""
    if not NANOBANANA_API_KEY:
        return
    for item in plan.overlays.items:
        if item.source == "ai" and not item.asset_path and item.query:
            path = _generate_overlay_image(item.query, item.style_hint, item.placement.w)
            if path:
                item.asset_path = path


# ===================================================================
# Demo / fallback planner (unchanged logic, overlays added as empty)
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

    # Build cuts by including speech segments and removing silences
    segments = transcript.get("segments", [])
    silences = analysis.get("silences", [])
    emphasis = analysis.get("emphasis_moments", [])

    cuts = []
    if segments:
        for seg in segments:
            cuts.append({"start": seg["start"], "end": seg["end"]})
    else:
        # Fallback: use whole video
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
                final_cuts.append({"start": cut["start"], "end": cut["start"] + remaining})
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
        # Only add if within a cut range
        for cut in final_cuts:
            if cut["start"] <= t <= cut["end"]:
                scale = min(scale_max, scale_min + (em.get("strength", 1.0) - 1.0) * 0.05)
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
            "enabled": False,  # No b-roll in demo mode
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
            "structure": ["Kept speech segments", "Removed silences", "Added emphasis zoom"],
        },
    })
