"""AI Edit Planner using Claude Haiku (with demo fallback)."""

import json
import logging
from typing import Optional

import anthropic

from apps.api.config import ANTHROPIC_API_KEY, DEMO_MODE
from apps.api.models.presets import get_preset
from apps.api.models.schemas import EditPlan

logger = logging.getLogger(__name__)

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


def plan_edit(
    transcript: dict,
    analysis: dict,
    prompt: str,
    preset_id: str,
    video_duration: float,
) -> EditPlan:
    """Generate an EditPlan using Claude Haiku or demo fallback."""
    if DEMO_MODE:
        logger.info("Demo mode: using rule-based planner")
        return _demo_plan(transcript, analysis, preset_id, video_duration)

    preset = get_preset(preset_id) or get_preset("snappy-creator")
    config = preset["config"]

    # Compress transcript for the prompt
    compressed_transcript = _compress_transcript(transcript)
    silence_summary = _summarize_silences(analysis)
    emphasis_summary = _summarize_emphasis(analysis)

    user_message = f"""Create an EditPlan for this video.

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

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-haiku-4-20250414",
                max_tokens=4096,
                system=PLANNER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            raw_json = response.content[0].text.strip()
            # Strip markdown fences if present
            if raw_json.startswith("```"):
                lines = raw_json.split("\n")
                raw_json = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                raw_json = raw_json.strip()

            plan_data = json.loads(raw_json)
            plan = EditPlan.model_validate(plan_data)

            # Validate constraints
            if plan.total_duration() < 10:
                raise ValueError("Plan total duration too short (< 10s)")

            logger.info(f"Edit plan generated: {len(plan.main_cuts)} cuts, "
                       f"{len(plan.punch_ins)} punch-ins, "
                       f"{len(plan.broll.inserts)} b-roll inserts")
            return plan

        except (json.JSONDecodeError, Exception) as e:
            if attempt == 0:
                logger.warning(f"Plan attempt {attempt + 1} failed: {e}. Retrying...")
                user_message = (
                    f"The previous JSON was invalid: {str(e)}\n\n"
                    f"Fix it to valid JSON matching the schema. Do not change the meaning.\n\n"
                    f"Previous response:\n{raw_json if 'raw_json' in dir() else 'N/A'}\n\n"
                    f"Return ONLY valid JSON."
                )
            else:
                logger.error(f"Plan generation failed after 2 attempts: {e}")
                logger.info("Falling back to demo planner")
                return _demo_plan(transcript, analysis, preset_id, video_duration)

    return _demo_plan(transcript, analysis, preset_id, video_duration)


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
