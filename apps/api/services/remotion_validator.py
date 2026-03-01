"""Server-side validation for Remotion inserts — don't trust planner output.

Enforces:
- Duration clamping [2s, 8s] (unless explicitly longer)
- Non-overlap: Remotion inserts must not overlap each other
- Non-overlap with Pexels b-roll: Remotion wins, b-roll is dropped/trimmed
- Max 3 inserts (unless explicitly requested)
- Insert windows must be within final timeline bounds
- Template ID validation
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Budget constants
MAX_INSERTS_DEFAULT = 3
MIN_INSERT_DURATION = 2.0
MAX_INSERT_DURATION = 8.0
MAX_TOTAL_REMOTION_SEC = 18.0

VALID_TEMPLATE_IDS = {
    "kpi-counter",
    "line-chart",
    "quote-highlight",
    "steps-list",
    "profile-card",
    "code-card",
    "custom",
}


def validate_remotion_inserts(
    remotion_inserts: list[dict],
    broll_inserts: list[dict],
    total_timeline_duration: float,
    max_inserts: int = MAX_INSERTS_DEFAULT,
) -> tuple[list[dict], list[dict], list[str]]:
    """Validate and fix remotion inserts.

    Args:
        remotion_inserts: List of remotion insert dicts from planner
        broll_inserts: List of b-roll insert dicts from planner
        total_timeline_duration: Duration of the final video timeline
        max_inserts: Max number of inserts allowed

    Returns:
        (validated_remotion_inserts, adjusted_broll_inserts, log_messages)
    """
    logs: list[str] = []

    if not remotion_inserts:
        return [], broll_inserts, logs

    validated = []

    for i, insert in enumerate(remotion_inserts):
        start = float(insert.get("start", 0))
        end = float(insert.get("end", 0))
        template_id = insert.get("template_id", "")
        duration = end - start

        # Validate template ID
        if template_id not in VALID_TEMPLATE_IDS:
            logs.append(f"Insert {i}: invalid template_id '{template_id}', skipping")
            continue

        # Validate start < end
        if start >= end:
            logs.append(f"Insert {i}: start ({start}) >= end ({end}), skipping")
            continue

        # Clamp duration
        if duration < MIN_INSERT_DURATION:
            logs.append(f"Insert {i}: duration {duration:.2f}s < {MIN_INSERT_DURATION}s, extending")
            end = start + MIN_INSERT_DURATION
            duration = MIN_INSERT_DURATION

        if duration > MAX_INSERT_DURATION:
            mode = insert.get("mode", "default")
            if mode != "custom":
                logs.append(f"Insert {i}: duration {duration:.2f}s > {MAX_INSERT_DURATION}s, clamping")
                end = start + MAX_INSERT_DURATION
                duration = MAX_INSERT_DURATION

        # Validate within timeline bounds
        if start < 0:
            logs.append(f"Insert {i}: start {start} < 0, clamping to 0")
            start = 0.0
        if end > total_timeline_duration:
            logs.append(
                f"Insert {i}: end {end:.2f} > timeline {total_timeline_duration:.2f}, clamping"
            )
            end = total_timeline_duration
            if end - start < MIN_INSERT_DURATION:
                logs.append(f"Insert {i}: too short after clamping, skipping")
                continue

        insert_copy = dict(insert)
        insert_copy["start"] = start
        insert_copy["end"] = end
        validated.append(insert_copy)

    # Sort by start time
    validated.sort(key=lambda x: x["start"])

    # Enforce non-overlap between remotion inserts
    deduped = []
    for i, ins in enumerate(validated):
        if deduped:
            prev = deduped[-1]
            if ins["start"] < prev["end"]:
                logs.append(
                    f"Insert {i}: overlaps previous ({ins['start']:.2f} < {prev['end']:.2f}), "
                    f"shifting start to {prev['end']:.2f}"
                )
                ins["start"] = prev["end"]
                if ins["end"] - ins["start"] < MIN_INSERT_DURATION:
                    logs.append(f"Insert {i}: too short after overlap fix, skipping")
                    continue
        deduped.append(ins)

    # Enforce max count
    if len(deduped) > max_inserts:
        logs.append(
            f"Remotion inserts exceed max ({len(deduped)} > {max_inserts}), keeping first {max_inserts}"
        )
        deduped = deduped[:max_inserts]

    # Enforce total duration budget
    total_dur = 0.0
    budget_filtered = []
    for ins in deduped:
        dur = ins["end"] - ins["start"]
        if total_dur + dur > MAX_TOTAL_REMOTION_SEC:
            logs.append(
                f"Remotion total duration budget exceeded ({total_dur:.1f}+{dur:.1f} > "
                f"{MAX_TOTAL_REMOTION_SEC}s), skipping remaining"
            )
            break
        budget_filtered.append(ins)
        total_dur += dur

    # Resolve overlap with b-roll: Remotion wins
    adjusted_broll = _resolve_broll_overlap(budget_filtered, broll_inserts, logs)

    for msg in logs:
        logger.info("RemotionValidator: %s", msg)

    return budget_filtered, adjusted_broll, logs


def _resolve_broll_overlap(
    remotion_inserts: list[dict],
    broll_inserts: list[dict],
    logs: list[str],
) -> list[dict]:
    """Remove or trim b-roll inserts that overlap with remotion inserts.

    Remotion inserts take priority over b-roll.
    """
    if not remotion_inserts or not broll_inserts:
        return broll_inserts

    adjusted = []
    for bi in broll_inserts:
        b_start = float(bi.get("start", 0))
        b_end = float(bi.get("end", 0))

        # Check against all remotion windows
        keep = True
        for ri in remotion_inserts:
            r_start = float(ri["start"])
            r_end = float(ri["end"])

            # No overlap
            if b_end <= r_start or b_start >= r_end:
                continue

            # Full overlap: b-roll is completely within remotion window
            if b_start >= r_start and b_end <= r_end:
                logs.append(
                    f"B-roll [{b_start:.2f}-{b_end:.2f}] fully overlapped by "
                    f"remotion [{r_start:.2f}-{r_end:.2f}], dropping"
                )
                keep = False
                break

            # Partial overlap: trim b-roll
            if b_start < r_start and b_end > r_start:
                logs.append(
                    f"B-roll [{b_start:.2f}-{b_end:.2f}] trimmed end to {r_start:.2f} "
                    f"(remotion [{r_start:.2f}-{r_end:.2f}])"
                )
                bi = dict(bi)
                bi["end"] = r_start
                b_end = r_start

            if b_start < r_end and b_end > r_end:
                logs.append(
                    f"B-roll [{b_start:.2f}-{b_end:.2f}] trimmed start to {r_end:.2f} "
                    f"(remotion [{r_start:.2f}-{r_end:.2f}])"
                )
                bi = dict(bi)
                bi["start"] = r_end
                b_start = r_end

        # Check minimum remaining duration
        if keep and (float(bi.get("end", 0)) - float(bi.get("start", 0))) < 0.5:
            logs.append(
                f"B-roll [{float(bi.get('start', 0)):.2f}-{float(bi.get('end', 0)):.2f}] "
                f"too short after trimming, dropping"
            )
            keep = False

        if keep:
            adjusted.append(bi)

    return adjusted
