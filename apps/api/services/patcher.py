"""Chat-based edit patching using Claude Haiku (with demo fallback)."""

import json
import logging

import anthropic

from apps.api.config import ANTHROPIC_API_KEY, DEMO_MODE
from apps.api.models.schemas import EditPlan, PlanPatch, apply_patch

logger = logging.getLogger(__name__)

PATCHER_SYSTEM_PROMPT = """You are a video edit assistant. The user wants to make changes to their video edit.
You receive the current EditPlan JSON and a user instruction.

Your job: return ONLY a valid JSON PlanPatch that makes the MINIMAL change needed.

RULES:
1. Return ONLY valid JSON. No markdown, no explanation, no code fences.
2. DO NOT change main_cuts or b-roll timing unless user explicitly asks for pacing/length changes.
3. If instruction is about captions only, patch ONLY captions.
4. If instruction is about music only, patch ONLY music.
5. If ambiguous, choose the minimal change.

PlanPatch schema:
{
  "captions": { "style_id": "...", "max_words_per_line": N, "max_lines": N, "enabled": bool },
  "music": { "enabled": bool, "track_id": "...", "target_volume_db": N },
  "broll": { "enabled": bool, "max_broll_clips": N, "strategy": "..." },
  "punch_ins": { "enabled": bool, "strength_multiplier": N },
  "output": { "resolution": [W,H], "aspect_ratio": "..." },
  "timing_adjustments": { "target_duration_sec": N, "tightness": N }
}

All fields are optional. Only include fields that need to change.
Available music tracks: upbeat-energy, cinematic-ambient, clean-podcast, luxury-smooth, study-lofi
Caption styles: snappy, cinematic, podcast, luxury, study"""


def generate_patch(
    current_plan: EditPlan,
    instruction: str,
) -> PlanPatch:
    """Generate a PlanPatch from a user instruction."""
    if DEMO_MODE:
        logger.info("Demo mode: using rule-based patcher")
        return _demo_patch(instruction)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    plan_json = json.dumps(current_plan.model_dump(), indent=2)

    user_message = f"""Current EditPlan:
{plan_json}

User instruction: "{instruction}"

Return ONLY the PlanPatch JSON with minimal changes needed."""

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-haiku-4-20250414",
                max_tokens=2048,
                system=PATCHER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            raw_json = response.content[0].text.strip()
            if raw_json.startswith("```"):
                lines = raw_json.split("\n")
                raw_json = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                raw_json = raw_json.strip()

            patch_data = json.loads(raw_json)
            patch = PlanPatch.model_validate(patch_data)
            logger.info(f"Patch generated: {patch.model_dump(exclude_none=True)}")
            return patch

        except (json.JSONDecodeError, Exception) as e:
            if attempt == 0:
                logger.warning(f"Patch attempt {attempt + 1} failed: {e}. Retrying...")
                user_message = (
                    f"The previous JSON was invalid: {str(e)}\n"
                    f"Fix to valid JSON PlanPatch. Do not change meaning.\n"
                    f"Return ONLY valid JSON."
                )
            else:
                logger.error(f"Patch generation failed: {e}")
                return _demo_patch(instruction)

    return _demo_patch(instruction)


def apply_edit(current_plan: EditPlan, instruction: str) -> tuple[PlanPatch, EditPlan]:
    """Generate patch and apply it to the current plan.

    Returns (patch, new_plan).
    """
    patch = generate_patch(current_plan, instruction)
    new_plan = apply_patch(current_plan, patch)
    return patch, new_plan


def _demo_patch(instruction: str) -> PlanPatch:
    """Rule-based fallback patcher."""
    instruction_lower = instruction.lower()

    patch_data = {}

    # Detect intent from instruction
    if any(w in instruction_lower for w in ["caption", "subtitle", "text", "font", "bigger", "smaller"]):
        patch_data["captions"] = {}
        if "bigger" in instruction_lower or "larger" in instruction_lower:
            patch_data["captions"]["style_id"] = "snappy"
            patch_data["captions"]["max_words_per_line"] = 3
        elif "smaller" in instruction_lower:
            patch_data["captions"]["max_words_per_line"] = 7
        elif "off" in instruction_lower or "remove" in instruction_lower or "no caption" in instruction_lower:
            patch_data["captions"]["enabled"] = False
        elif "on" in instruction_lower or "add" in instruction_lower:
            patch_data["captions"]["enabled"] = True

    if any(w in instruction_lower for w in ["music", "song", "track", "audio", "volume"]):
        patch_data["music"] = {}
        if "off" in instruction_lower or "remove" in instruction_lower or "no music" in instruction_lower:
            patch_data["music"]["enabled"] = False
        elif "louder" in instruction_lower:
            patch_data["music"]["target_volume_db"] = -12.0
        elif "quieter" in instruction_lower or "softer" in instruction_lower:
            patch_data["music"]["target_volume_db"] = -24.0
        elif "upbeat" in instruction_lower or "energetic" in instruction_lower:
            patch_data["music"]["track_id"] = "upbeat-energy"
        elif "calm" in instruction_lower or "chill" in instruction_lower:
            patch_data["music"]["track_id"] = "study-lofi"
        elif "cinematic" in instruction_lower:
            patch_data["music"]["track_id"] = "cinematic-ambient"

    if any(w in instruction_lower for w in ["b-roll", "broll", "b roll", "stock"]):
        patch_data["broll"] = {}
        if "less" in instruction_lower or "fewer" in instruction_lower:
            patch_data["broll"]["max_broll_clips"] = 1
        elif "more" in instruction_lower:
            patch_data["broll"]["max_broll_clips"] = 6
        elif "off" in instruction_lower or "remove" in instruction_lower or "no" in instruction_lower:
            patch_data["broll"]["enabled"] = False

    if any(w in instruction_lower for w in ["zoom", "punch"]):
        patch_data["punch_ins"] = {}
        if "less" in instruction_lower or "subtle" in instruction_lower:
            patch_data["punch_ins"]["strength_multiplier"] = 0.7
        elif "more" in instruction_lower or "stronger" in instruction_lower:
            patch_data["punch_ins"]["strength_multiplier"] = 1.3
        elif "off" in instruction_lower or "remove" in instruction_lower or "no" in instruction_lower:
            patch_data["punch_ins"]["enabled"] = False

    if any(w in instruction_lower for w in ["shorter", "longer", "tighter", "pace"]):
        patch_data["timing_adjustments"] = {}
        if "shorter" in instruction_lower or "tighter" in instruction_lower:
            patch_data["timing_adjustments"]["tightness"] = 0.8
        elif "longer" in instruction_lower:
            patch_data["timing_adjustments"]["tightness"] = 1.2

    # If nothing detected, default to a no-op with captions toggle
    if not patch_data:
        patch_data["captions"] = {"enabled": True}

    return PlanPatch.model_validate(patch_data)
