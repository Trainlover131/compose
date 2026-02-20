"""AI Edit Planner using Claude Haiku (with demo fallback)."""

import hashlib
import json
import logging
import os
import re
import unicodedata
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import anthropic

from apps.api.config import ANTHROPIC_API_KEY, DEMO_MODE
from apps.api.models.presets import get_preset
from apps.api.models.schemas import EditPlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NanoBanana API configuration
# ---------------------------------------------------------------------------
NANOBANANA_API_KEY = os.getenv("NANOBANANA_API_KEY", "")
_OVERLAY_CACHE_DIR = (
    Path("/data/storage/overlay_cache")
    if Path("/data/storage").exists()
    else Path("/tmp/overlay_cache")
)

# ---------------------------------------------------------------------------
# Brand / concept keyword lists
# ---------------------------------------------------------------------------
_BRAND_SEEDS = {
    "y combinator", "yc", "jarvis", "tony stark", "iron man",
    "openai", "anthropic", "a16z", "sequoia",
}

_ABSTRACT_CONCEPTS = {
    "momentum", "focus", "burnout", "discipline", "flow", "fear",
    "confidence", "vision", "anxiety", "strategy", "growth",
}


# ---------------------------------------------------------------------------
# Helper: word extraction from transcript
# ---------------------------------------------------------------------------

def _extract_words(transcript: dict) -> list[dict]:
    """Return list of {word, start, end} from transcript word-level timestamps.

    Fallback: if segments have no .words, synthesise pseudo-words from
    segment text split evenly across the segment duration.
    """
    words: list[dict] = []
    for seg in transcript.get("segments", []):
        seg_words = seg.get("words")
        if seg_words:
            for w in seg_words:
                words.append({
                    "word": w.get("word", w.get("text", "")).strip(),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                })
        else:
            # Fallback: split segment text into pseudo-words
            text = seg.get("text", "").strip()
            if not text:
                continue
            tokens = text.split()
            seg_start = float(seg["start"])
            seg_end = float(seg["end"])
            seg_dur = seg_end - seg_start
            if seg_dur <= 0 or not tokens:
                continue
            per_word = seg_dur / len(tokens)
            for i, tok in enumerate(tokens):
                words.append({
                    "word": tok,
                    "start": round(seg_start + i * per_word, 3),
                    "end": round(seg_start + (i + 1) * per_word, 3),
                })
    return words


def _normalize_token(text: str) -> str:
    """Lowercase, strip punctuation, normalize unicode."""
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Helper: keyword extraction from user prompt
# ---------------------------------------------------------------------------

def _extract_overlay_keywords_from_prompt(prompt: str) -> list[str]:
    """Extract keywords from user prompt for overlay anchor detection.

    Sources:
    1. Quoted phrases in the prompt
    2. Seed brand keywords
    3. Capitalised phrases heuristic (2+ char words starting uppercase)
    """
    keywords: list[str] = []

    # 1) Quoted phrases
    for match in re.finditer(r'"([^"]+)"', prompt):
        keywords.append(match.group(1).strip())
    for match in re.finditer(r"'([^']+)'", prompt):
        keywords.append(match.group(1).strip())

    # 2) Brand seeds that appear in the prompt
    prompt_lower = prompt.lower()
    for brand in _BRAND_SEEDS:
        if brand in prompt_lower:
            keywords.append(brand)

    # 3) Capitalised phrases heuristic
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", prompt):
        phrase = match.group(1)
        if len(phrase) >= 2:
            keywords.append(phrase)

    # Normalise + dedupe (preserve order)
    seen: set[str] = set()
    deduped: list[str] = []
    for kw in keywords:
        norm = _normalize_token(kw)
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(kw.strip())
    return deduped


# ---------------------------------------------------------------------------
# Helper: keyword hit finder (supports multi-word)
# ---------------------------------------------------------------------------

def _find_keyword_hits(
    words: list[dict], keyword: str
) -> list[dict]:
    """Find all positions where *keyword* appears in the word stream.

    Returns list of {start, end, phrase} for each match.
    Supports multi-word keywords via sliding window.
    """
    kw_tokens = _normalize_token(keyword).split()
    if not kw_tokens:
        return []
    hits: list[dict] = []
    n = len(kw_tokens)
    for i in range(len(words) - n + 1):
        window = words[i : i + n]
        window_norm = [_normalize_token(w["word"]) for w in window]
        if window_norm == kw_tokens:
            hits.append({
                "start": window[0]["start"],
                "end": window[-1]["end"],
                "phrase": " ".join(w["word"] for w in window),
            })
    return hits


# ---------------------------------------------------------------------------
# Helper: build overlay anchor windows in ORIGINAL timeline
# ---------------------------------------------------------------------------

def _make_anchor_windows(
    transcript: dict,
    prompt: str,
    max_anchors: int = 8,
    logo_dur_s: float = 1.2,
    pad_before: float = 0.15,
) -> list[dict]:
    """Build keyword-anchored overlay windows on the ORIGINAL timeline.

    Returns list of {keyword, anchor_phrase, orig_start, orig_end}.
    """
    words = _extract_words(transcript)
    if not words:
        return []

    keywords = _extract_overlay_keywords_from_prompt(prompt)
    if not keywords:
        return []

    anchors: list[dict] = []
    for kw in keywords:
        hits = _find_keyword_hits(words, kw)
        for hit in hits:
            anchors.append({
                "keyword": kw,
                "anchor_phrase": hit["phrase"],
                "orig_start": round(max(0.0, hit["start"] - pad_before), 3),
                "orig_end": round(hit["start"] - pad_before + logo_dur_s, 3),
            })
        if len(anchors) >= max_anchors:
            break

    # Sort and trim
    anchors.sort(key=lambda a: a["orig_start"])
    return anchors[:max_anchors]


# ---------------------------------------------------------------------------
# Helper: timeline mapping (original -> final after main_cuts)
# ---------------------------------------------------------------------------

def _build_timeline_map_from_cuts(main_cuts: list) -> list[dict]:
    """Build a mapping from original timeline to final timeline.

    Each entry: {orig_start, orig_end, final_start, final_end}.
    """
    timeline_map: list[dict] = []
    final_offset = 0.0
    for cut in main_cuts:
        c_start = cut["start"] if isinstance(cut, dict) else cut.start
        c_end = cut["end"] if isinstance(cut, dict) else cut.end
        dur = c_end - c_start
        timeline_map.append({
            "orig_start": c_start,
            "orig_end": c_end,
            "final_start": final_offset,
            "final_end": final_offset + dur,
        })
        final_offset += dur
    return timeline_map


def _map_time(orig_t: float, timeline_map: list[dict]) -> Optional[float]:
    """Map a single original-timeline timestamp to the final timeline.

    Returns None if the timestamp is outside all cuts (i.e. it was cut out).
    """
    for m in timeline_map:
        if m["orig_start"] <= orig_t <= m["orig_end"]:
            return m["final_start"] + (orig_t - m["orig_start"])
    return None


def _anchors_to_final_timeline(
    anchors: list[dict], main_cuts: list
) -> list[dict]:
    """Convert anchors from ORIGINAL to FINAL timeline.

    Drops anchors whose start falls outside retained cuts.
    Returns list of {keyword, anchor_phrase, start, end}.
    """
    tmap = _build_timeline_map_from_cuts(main_cuts)
    result: list[dict] = []
    for a in anchors:
        final_start = _map_time(a["orig_start"], tmap)
        final_end = _map_time(a["orig_end"], tmap)
        if final_start is None:
            continue
        if final_end is None:
            # end might be outside the cut; clamp to the cut boundary
            for m in tmap:
                if m["orig_start"] <= a["orig_start"] <= m["orig_end"]:
                    final_end = m["final_end"]
                    break
            if final_end is None:
                continue
        result.append({
            "keyword": a["keyword"],
            "anchor_phrase": a.get("anchor_phrase", ""),
            "start": round(final_start, 3),
            "end": round(final_end, 3),
        })
    return result


# ---------------------------------------------------------------------------
# Helper: deterministic non-overlap enforcement
# ---------------------------------------------------------------------------

def _enforce_nonoverlap(
    items: list[dict],
    shift_s: float = 0.2,
    max_total_shift_s: float = 0.6,
) -> list[dict]:
    """Enforce non-overlap on a list of items with 'start'/'end' keys.

    Strategy:
    1. Shift later items forward by *shift_s* until no overlap, up to
       *max_total_shift_s* cumulative shift per item.
    2. If still overlapping after max shift, reduce duration to fit.
    """
    if len(items) <= 1:
        return items
    items = sorted(items, key=lambda x: x["start"])
    for i in range(1, len(items)):
        total_shifted = 0.0
        while items[i]["start"] < items[i - 1]["end"]:
            if total_shifted >= max_total_shift_s:
                # Reduce duration: push start to previous end
                dur = items[i]["end"] - items[i]["start"]
                items[i]["start"] = round(items[i - 1]["end"], 3)
                items[i]["end"] = round(items[i]["start"] + max(0.1, dur * 0.5), 3)
                break
            items[i]["start"] = round(items[i]["start"] + shift_s, 3)
            items[i]["end"] = round(items[i]["end"] + shift_s, 3)
            total_shifted += shift_s
    return items


# ---------------------------------------------------------------------------
# Helper: brand / abstract concept classification
# ---------------------------------------------------------------------------

def _is_brand_like(keyword: str) -> bool:
    """True if keyword looks like a brand / product / proper noun."""
    kw_lower = keyword.lower().strip()
    if kw_lower in _BRAND_SEEDS:
        return True
    # All-caps acronym (length <= 5)
    if keyword.isupper() and len(keyword) <= 5:
        return True
    # Contains digits (e.g. "GPT-4")
    if any(c.isdigit() for c in keyword):
        return True
    return False


def _is_abstract_concept(keyword: str) -> bool:
    """True if keyword is an abstract concept suitable for b-roll cutaway."""
    if not keyword or not keyword.strip():
        return False
    if _is_brand_like(keyword):
        return False
    kw_lower = keyword.lower().strip()
    if kw_lower in _ABSTRACT_CONCEPTS:
        return True
    # Fallback: anything that isn't brand-like counts as abstract
    return True


def _build_broll_anchors(
    orig_anchors: list[dict],
    main_cuts: list,
    broll_dur_s: float = 1.6,
    pad_before: float = 0.10,
) -> list[dict]:
    """Select abstract-concept anchors and build b-roll timing windows.

    Duration = min(broll_dur_s, remaining clip duration after anchor start).
    Returns anchors in ORIGINAL timeline.
    """
    # Compute total video end from main_cuts (original timeline)
    video_end = 0.0
    for cut in main_cuts:
        c_end = cut["end"] if isinstance(cut, dict) else cut.end
        if c_end > video_end:
            video_end = c_end

    broll_anchors: list[dict] = []
    for a in orig_anchors:
        if not _is_abstract_concept(a["keyword"]):
            continue
        orig_start = round(max(0.0, a["orig_start"] - pad_before + 0.15), 3)
        remaining = max(0.1, video_end - orig_start)
        dur = min(broll_dur_s, remaining)
        broll_anchors.append({
            "keyword": a["keyword"],
            "anchor_phrase": a.get("anchor_phrase", ""),
            "orig_start": orig_start,
            "orig_end": round(orig_start + dur, 3),
        })
    return broll_anchors


# ---------------------------------------------------------------------------
# Helper: NanoBanana AI image generation (best-effort)
# ---------------------------------------------------------------------------

def _nanobanana_generate(query: str, style_hint: str = "", placement_w: float = 0.18) -> Optional[str]:
    """Generate an AI overlay image via NanoBanana API. Returns local path or None.

    Best-effort: never raises; returns None on any failure.
    """
    if not NANOBANANA_API_KEY:
        return None

    # Cache check
    cache_key = hashlib.sha256(
        f"{query}|{style_hint}|{placement_w}|9:16".encode()
    ).hexdigest()[:24]
    _OVERLAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = _OVERLAY_CACHE_DIR / f"{cache_key}.png"
    if cached.exists():
        logger.info("NanoBanana cache hit: %s", cached)
        return str(cached)

    try:
        payload = json.dumps({
            "prompt": query,
            "numImages": 1,
            "type": "TEXTTOIMAGE",
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())

        # Check for direct image URL in response
        image_url = None
        if isinstance(result, dict):
            # Try common response shapes
            for key in ("imageUrl", "image_url", "url", "output"):
                if key in result and isinstance(result[key], str) and result[key].startswith("http"):
                    image_url = result[key]
                    break
            # Array of images
            images = result.get("images", result.get("data", []))
            if isinstance(images, list) and images:
                first = images[0]
                if isinstance(first, str) and first.startswith("http"):
                    image_url = first
                elif isinstance(first, dict):
                    image_url = first.get("url") or first.get("imageUrl")

        if image_url:
            img_req = urllib.request.Request(image_url)
            with urllib.request.urlopen(img_req, timeout=30) as img_resp:
                cached.write_bytes(img_resp.read())
            logger.info("NanoBanana image saved: %s", cached)
            return str(cached)

        # If we only got a taskId with no immediate URL, we don't poll
        logger.info("NanoBanana returned taskId only; skipping (no polling).")
        return None

    except Exception as e:
        logger.warning("NanoBanana generation failed (best-effort): %s", e)
        return None


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
11. REQUIRED OVERLAY ANCHORS: If provided, you MUST return exactly one overlays.items entry per anchor. DO NOT CHANGE the start or end values. You may only fill: type, source, query, style_hint, placement, animation, notes.
12. Overlay type rule: brand/product/proper noun => type "image_overlay" (corner pop). Abstract concept => type "video_overlay" (full-screen cutaway).
13. Overlay source rule: logo/HUD/UI images => source "ai". Generic footage => source "pexels".
14. overlays.items must be non-overlapping and sorted by start time.
15. REQUIRED BROLL ANCHORS: If provided, you MUST return broll.inserts entries matching those exact start/end times. DO NOT CHANGE start or end. You may ONLY fill query, keywords, source, notes for b-roll inserts.
16. broll inserts must be non-overlapping.

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
        "anchor_phrase": "<string>",
        "keyword": "<string>",
        "query": "<search/gen prompt>",
        "source": "ai or pexels",
        "style_hint": "<string>",
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


def _strip_json_fences(raw: str) -> str:
    """Strip markdown code fences from raw LLM output."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return raw.strip()


def _llm_call(client, system: str, user_msg: str, max_tokens: int = 4096) -> str:
    """Single LLM call returning raw text. Raises on API errors."""
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text.strip()


def _build_deterministic_fallback_overlays(
    final_anchors: list[dict],
) -> list[dict]:
    """Deterministic fallback overlay items from anchors."""
    items = []
    for a in final_anchors:
        kw = a["keyword"]
        items.append({
            "type": "image_overlay",
            "start": a["start"],
            "end": a["end"],
            "anchor_phrase": a.get("anchor_phrase", ""),
            "keyword": kw,
            "query": f"Minimal {kw} logo sticker, flat, white, transparent background",
            "source": "ai",
            "style_hint": "logo",
            "placement": {"x": 0.82, "y": 0.12, "w": 0.18},
            "animation": {"fade_in": 0.12, "fade_out": 0.12},
            "notes": "deterministic fallback overlay",
        })
    return _enforce_nonoverlap(items)


def _build_deterministic_fallback_broll(
    final_anchors: list[dict],
) -> list[dict]:
    """Deterministic fallback b-roll inserts from anchors."""
    inserts = []
    for a in final_anchors:
        kw = a["keyword"]
        inserts.append({
            "start": a["start"],
            "end": a["end"],
            "query": f"{kw} cinematic b-roll",
            "keywords": [kw],
            "source": "pexels",
            "notes": "fallback b-roll",
        })
    return _enforce_nonoverlap(inserts)


def plan_edit(
    transcript: dict,
    analysis: dict,
    prompt: str,
    preset_id: str,
    video_duration: float,
) -> EditPlan:
    """Generate an EditPlan using Claude Haiku or demo fallback.

    Three-pass LLM flow:
      Pass 1 – main_cuts, punch_ins, captions, music (broll/overlays empty)
      Pass 2 – overlay creative fill (timing locked to word anchors)
      Pass 3 – b-roll creative fill (timing locked to abstract-concept anchors)
    """
    if DEMO_MODE:
        logger.info("Demo mode: using rule-based planner")
        return _demo_plan(transcript, analysis, preset_id, video_duration)

    preset = get_preset(preset_id) or get_preset("snappy-creator")
    config = preset["config"]

    compressed_transcript = _compress_transcript(transcript)
    silence_summary = _summarize_silences(analysis)
    emphasis_summary = _summarize_emphasis(analysis)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ------------------------------------------------------------------
    # PASS 1: Core plan (main_cuts, punch_ins, captions, music)
    # ------------------------------------------------------------------
    pass1_msg = f"""Create an EditPlan for this video.
Focus ONLY on: main_cuts, punch_ins, captions, music, rationale.
Leave broll disabled/empty and overlays disabled/empty for now.

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

Generate the EditPlan JSON now. Remember: ONLY valid JSON, no markdown."""

    plan = None
    for attempt in range(2):
        try:
            raw_json = _strip_json_fences(_llm_call(client, PLANNER_SYSTEM_PROMPT, pass1_msg))
            plan_data = json.loads(raw_json)
            # Ensure overlays/broll disabled for pass 1
            plan_data.setdefault("overlays", {"enabled": False, "items": []})
            plan_data.setdefault("broll", {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []})
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
                logger.warning("Pass 1 attempt %d failed: %s. Retrying...", attempt + 1, e)
                pass1_msg = (
                    f"The previous JSON was invalid: {e}\n\n"
                    f"Fix it. Return ONLY valid JSON matching the schema.\n\n"
                    f"Previous response:\n{raw_json if 'raw_json' in dir() else 'N/A'}"
                )
            else:
                logger.error("Pass 1 failed after 2 attempts: %s", e)
                return _demo_plan(transcript, analysis, preset_id, video_duration)

    if plan is None:
        return _demo_plan(transcript, analysis, preset_id, video_duration)

    # ------------------------------------------------------------------
    # Compute overlay anchors (deterministic, ORIGINAL timeline)
    # ------------------------------------------------------------------
    orig_overlay_anchors = _make_anchor_windows(
        transcript, prompt, max_anchors=8, logo_dur_s=1.2, pad_before=0.15,
    )
    main_cuts_dicts = [{"start": c.start, "end": c.end} for c in plan.main_cuts]
    final_overlay_anchors = _anchors_to_final_timeline(orig_overlay_anchors, main_cuts_dicts)

    # ------------------------------------------------------------------
    # PASS 2: Overlay creative fill
    # ------------------------------------------------------------------
    overlay_items: list[dict] = []
    if final_overlay_anchors:
        anchors_desc = "\n".join(
            f"  - keyword={a['keyword']}, anchor_phrase={a['anchor_phrase']!r}, "
            f"start={a['start']}, end={a['end']}"
            for a in final_overlay_anchors
        )
        pass2_msg = f"""You are given REQUIRED OVERLAY ANCHORS with exact start/end times.
Return ONLY a JSON object: {{"overlays": {{"enabled": true, "items": [...]}}}}

REQUIRED OVERLAY ANCHORS (DO NOT change start/end):
{anchors_desc}

RULES:
- Exactly one item per anchor, same order.
- DO NOT change start or end.
- For each item fill: type, query, source, style_hint, placement, animation, keyword, anchor_phrase, notes.
- brand/product/proper noun => type "image_overlay", source "ai"
- abstract concept => type "video_overlay", source "pexels"

USER PROMPT: {prompt}

Return ONLY valid JSON, no markdown."""

        use_fallback = False
        try:
            raw = _strip_json_fences(_llm_call(client, PLANNER_SYSTEM_PROMPT, pass2_msg, max_tokens=2048))
            overlay_data = json.loads(raw)
            claude_items = overlay_data.get("overlays", {}).get("items", [])

            # STRICT VALIDATION: check timing unchanged
            if len(claude_items) != len(final_overlay_anchors):
                logger.warning("Pass 2: item count mismatch (%d vs %d anchors). Using fallback.",
                               len(claude_items), len(final_overlay_anchors))
                use_fallback = True
            else:
                for ci, anchor in zip(claude_items, final_overlay_anchors):
                    if (abs(ci.get("start", -1) - anchor["start"]) > 0.01
                            or abs(ci.get("end", -1) - anchor["end"]) > 0.01):
                        logger.warning("Pass 2: Claude changed timing. Discarding response.")
                        use_fallback = True
                        break

            if not use_fallback:
                overlay_items = claude_items
        except Exception as e:
            logger.warning("Pass 2 overlay call failed: %s. Using fallback.", e)
            use_fallback = True

        if use_fallback:
            overlay_items = _build_deterministic_fallback_overlays(final_overlay_anchors)
        else:
            overlay_items = _enforce_nonoverlap(overlay_items)

        # Best-effort NanoBanana generation for AI-sourced image overlays
        for item in overlay_items:
            if item.get("source") == "ai" and item.get("type") == "image_overlay":
                asset = _nanobanana_generate(
                    item.get("query", ""),
                    item.get("style_hint", ""),
                    item.get("placement", {}).get("w", 0.18),
                )
                if asset:
                    item["asset_path"] = asset

    # ------------------------------------------------------------------
    # Compute b-roll anchors (deterministic, abstract concepts only)
    # ------------------------------------------------------------------
    orig_broll_anchors = _build_broll_anchors(
        orig_overlay_anchors, main_cuts_dicts, broll_dur_s=1.6, pad_before=0.10,
    )
    final_broll_anchors = _anchors_to_final_timeline(orig_broll_anchors, main_cuts_dicts)

    # ------------------------------------------------------------------
    # PASS 3: B-roll creative fill (timing locked)
    # ------------------------------------------------------------------
    broll_inserts: list[dict] = []
    if final_broll_anchors:
        broll_anchors_desc = "\n".join(
            f"  - keyword={a['keyword']}, start={a['start']}, end={a['end']}"
            for a in final_broll_anchors
        )
        pass3_msg = f"""You are given REQUIRED BROLL ANCHORS with exact start/end times.
Return ONLY a JSON object: {{"broll": {{"enabled": true, "strategy": "cutaway_fullscreen", "inserts": [...]}}}}

REQUIRED BROLL ANCHORS (DO NOT change start/end):
{broll_anchors_desc}

RULES:
- Exactly one insert per anchor, same order.
- DO NOT change start or end.
- For each insert fill ONLY: query, keywords, source, notes.
- source should be "pexels" for stock footage.

USER PROMPT: {prompt}

Return ONLY valid JSON, no markdown."""

        use_broll_fallback = False
        try:
            raw = _strip_json_fences(_llm_call(client, PLANNER_SYSTEM_PROMPT, pass3_msg, max_tokens=2048))
            broll_data = json.loads(raw)
            claude_inserts = broll_data.get("broll", {}).get("inserts", [])

            # STRICT VALIDATION: check timing unchanged
            if len(claude_inserts) != len(final_broll_anchors):
                logger.warning("Pass 3: insert count mismatch (%d vs %d anchors). Using fallback.",
                               len(claude_inserts), len(final_broll_anchors))
                use_broll_fallback = True
            else:
                for ci, anchor in zip(claude_inserts, final_broll_anchors):
                    if (abs(ci.get("start", -1) - anchor["start"]) > 0.01
                            or abs(ci.get("end", -1) - anchor["end"]) > 0.01):
                        logger.warning("Pass 3: Claude changed b-roll timing. Discarding response.")
                        use_broll_fallback = True
                        break

            if not use_broll_fallback:
                broll_inserts = claude_inserts
        except Exception as e:
            logger.warning("Pass 3 b-roll call failed: %s. Using fallback.", e)
            use_broll_fallback = True

        if use_broll_fallback:
            broll_inserts = _build_deterministic_fallback_broll(final_broll_anchors)
        else:
            broll_inserts = _enforce_nonoverlap(broll_inserts)

    # ------------------------------------------------------------------
    # Attach overlays + b-roll to the plan
    # ------------------------------------------------------------------
    plan_dict = plan.model_dump()

    if overlay_items:
        plan_dict["overlays"] = {"enabled": True, "items": overlay_items}
    else:
        plan_dict["overlays"] = {"enabled": False, "items": []}

    if broll_inserts:
        plan_dict["broll"] = {
            "enabled": True,
            "strategy": "cutaway_fullscreen",
            "inserts": broll_inserts,
        }
    # else: keep broll as-is from pass 1 (disabled/empty)

    plan = EditPlan.model_validate(plan_dict)

    logger.info(
        "Final plan: %d cuts, %d punch-ins, %d overlays, %d b-roll inserts",
        len(plan.main_cuts), len(plan.punch_ins),
        len(plan.overlays.items), len(plan.broll.inserts),
    )
    return plan


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
