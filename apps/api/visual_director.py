"""VisualDirector — Gemini-powered autonomous overlay + b-roll selection.

Uses Gemini multimodal video analysis (Files API upload) to propose
overlays and b-roll inserts in ORIGINAL video timeline.  Falls back
to text-only mode (transcript + word timings) when video is unavailable.

Output JSON schema:
  {
    "overlays": [{ start_orig, end_orig, image_prompt, placement, animation, reason }],
    "broll":    [{ start_orig, end_orig, query, reason }]
  }
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from google import genai

from apps.api.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_OVERLAYS = 8
_MAX_BROLL = 6
_JSON_RETRIES = 2
_FILE_POLL_INTERVAL_S = 1.5
_FILE_POLL_TIMEOUT_S = 120.0

_EMPTY_RESULT: dict = {"overlays": [], "broll": []}

# ---------------------------------------------------------------------------
# Gemini output schema (for validation + retry prompt)
# ---------------------------------------------------------------------------
_OUTPUT_SCHEMA = """{
  "overlays": [
    {
      "start_orig": <float>,
      "end_orig": <float>,
      "image_prompt": "<string: concise image generation prompt>",
      "placement": {"x": <0..1>, "y": <0..1>, "w": <0..1>},
      "animation": {"fade_in": <float seconds>, "fade_out": <float seconds>},
      "reason": "<string: why this overlay here>"
    }
  ],
  "broll": [
    {
      "start_orig": <float>,
      "end_orig": <float>,
      "query": "<string: Pexels search terms>",
      "reason": "<string: why this b-roll here>"
    }
  ]
}"""


def _build_prompt(transcript: dict, prompt: str, video_duration: float | None = None) -> str:
    """Build the Gemini system+user prompt for overlay/b-roll proposals."""
    segments = transcript.get("segments", [])
    transcript_lines: list[str] = []
    for seg in segments:
        words = seg.get("words", [])
        if words:
            word_detail = " ".join(
                f"{w.get('word', '')}({w.get('start', 0):.2f}-{w.get('end', 0):.2f})"
                for w in words
            )
            transcript_lines.append(
                f"[{seg['start']:.2f}-{seg['end']:.2f}] "
                f"{seg['text'].strip()}\n"
                f"  word_timings: {word_detail}"
            )
        else:
            transcript_lines.append(
                f"[{seg['start']:.2f}-{seg['end']:.2f}] {seg['text'].strip()}"
            )

    transcript_block = (
        "\n".join(transcript_lines) if transcript_lines
        else "(no transcript available)"
    )

    dur_line = f"\nVideo duration: {video_duration:.1f}s" if video_duration else ""

    return f"""You are a Visual Director for short-form video editing. Analyze this video and propose overlays (image pop-ups) and b-roll (stock video cutaways) that enhance viewer engagement.{dur_line}

USER EDITING PROMPT: {prompt}

TRANSCRIPT (with per-word timestamps in seconds):
{transcript_block}

=== TIMING RULES (CRITICAL) ===
Every overlay and every b-roll MUST be anchored to a specific quote from the transcript above.

For each item you propose:
1. Identify the exact words being spoken that motivate the overlay or b-roll.
2. Set start_orig = (first anchor word's start timestamp) − 0.2 to 0.6s padding.
3. Set end_orig   = (last anchor word's end timestamp)   + 0.2 to 0.6s padding.
4. In the "reason" field, include the anchor quote verbatim.  Format:
   "reason": "anchor: \\"<exact words>\\" — <your creative rationale>"

Do NOT place items at arbitrary round-number times. Use the word_timings above.

=== B-ROLL RULES ===
- query must describe LITERAL, DOCUMENTARY footage that directly depicts the concrete nouns or actions being spoken at that moment.
- Good: speaker says "we built a factory" → query: "factory assembly line manufacturing"
- Bad:  speaker says "we built a factory" → query: "abstract growth metaphor light rays"
- Avoid abstract, surreal, or metaphorical stock footage UNLESS the user prompt explicitly requests it (e.g. "make it dreamy", "add surreal visuals").
- Each b-roll should last 1.0–3.0 seconds.

=== OVERLAY RULES ===
- image_prompt should be a concise, descriptive prompt for AI image generation.
- Each overlay should last 0.8–2.0 seconds.
- placement: x,y = position (0=left/top, 1=right/bottom), w = width fraction. Common: top-right corner = {{"x":0.78,"y":0.08,"w":0.20}}.
- animation: fade_in and fade_out in seconds (typically 0.1–0.3s).

=== GENERAL ===
- Use ORIGINAL video timestamps (seconds).
- Max {_MAX_OVERLAYS} overlays, max {_MAX_BROLL} b-roll inserts.
- Avoid overlapping items when possible.
- If the user prompt requests specific overlays or b-roll, include them.

Return ONLY valid JSON with exactly this structure (no markdown, no commentary, no preface text):
{_OUTPUT_SCHEMA}"""


class VisualDirector:
    """Gemini-powered overlay + b-roll proposer.

    Primary path: upload video via Gemini Files API, then multimodal analysis.
    Fallback: text-only mode with transcript + word timings.
    """

    def __init__(self) -> None:
        api_key = GEMINI_API_KEY
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required for VisualDirector")
        self._client = genai.Client(api_key=api_key)
        self._model = GEMINI_MODEL

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose(
        self,
        video_path: Optional[str],
        transcript: dict,
        prompt: str,
        video_duration: float | None = None,
    ) -> dict:
        """Propose overlays + b-roll in ORIGINAL timeline.

        Returns {"overlays": [...], "broll": [...]}.
        Never raises — returns empty result on failure.
        """
        prompt_text = _build_prompt(transcript, prompt, video_duration)

        # Try multimodal (video + text) first
        file_obj = None
        if video_path and Path(video_path).is_file():
            file_obj = self._upload_and_wait_active(video_path)

        if file_obj is not None:
            contents = [file_obj, prompt_text]
        else:
            logger.info("VisualDirector: running in text-only mode (no video file)")
            contents = [prompt_text]

        raw_text = self._gemini_generate(contents)
        if raw_text is None:
            logger.warning("VisualDirector: Gemini returned no response, disabling overlays/broll")
            return dict(_EMPTY_RESULT)

        result = self._parse_validate_or_retry(raw_text, contents)

        n_ov = len(result.get("overlays", []))
        n_br = len(result.get("broll", []))
        logger.info(f"VisualDirector: gemini returned overlays={n_ov} broll={n_br}")

        return result

    # ------------------------------------------------------------------
    # Files API upload
    # ------------------------------------------------------------------

    def _upload_and_wait_active(self, video_path: str) -> Optional[object]:
        """Upload video via Gemini Files API and poll until ACTIVE.

        Returns the file object ready for generate_content, or None on failure.
        """
        p = Path(video_path)
        filesize = p.stat().st_size
        basename = p.name
        logger.info(f"VisualDirector: video upload start filesize={filesize} basename={basename}")

        try:
            uploaded = self._client.files.upload(file=video_path)
        except Exception as exc:
            logger.warning(f"VisualDirector: file upload failed: {exc}")
            return None

        # Poll for readiness
        deadline = time.monotonic() + _FILE_POLL_TIMEOUT_S
        poll_count = 0
        while time.monotonic() < deadline:
            try:
                file_obj = self._client.files.get(name=uploaded.name)
            except Exception as exc:
                logger.warning(f"VisualDirector: files.get failed: {exc}")
                return None

            state_name = file_obj.state.name if hasattr(file_obj.state, "name") else str(file_obj.state)
            poll_count += 1
            if poll_count % 5 == 0:
                logger.info(f"VisualDirector: file state={state_name} (poll #{poll_count})")

            if state_name == "ACTIVE":
                logger.info(f"VisualDirector: file ready (ACTIVE) after {poll_count} polls")
                return file_obj

            if state_name == "FAILED":
                logger.warning("VisualDirector: file processing FAILED, aborting upload")
                return None

            time.sleep(_FILE_POLL_INTERVAL_S)

        logger.warning(f"VisualDirector: file poll timed out after {_FILE_POLL_TIMEOUT_S}s")
        return None

    # ------------------------------------------------------------------
    # Gemini generate
    # ------------------------------------------------------------------

    def _gemini_generate(self, contents_parts: list) -> Optional[str]:
        """Call Gemini generate_content and return raw text, or None."""
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents_parts,
            )
            return response.text.strip() if response.text else None
        except Exception as exc:
            logger.warning(f"VisualDirector: Gemini generate failed: {exc}")
            return None

    # ------------------------------------------------------------------
    # Parse, validate, retry
    # ------------------------------------------------------------------

    def _parse_validate_or_retry(self, raw_text: str, original_contents: list) -> dict:
        """Parse JSON from Gemini, validate, retry up to _JSON_RETRIES times.

        Returns validated result or empty dict on total failure.
        """
        for attempt in range(_JSON_RETRIES + 1):
            parsed = self._try_parse_json(raw_text)
            if parsed is not None:
                validated = self._validate_result(parsed)
                if validated is not None:
                    return validated

            if attempt < _JSON_RETRIES:
                logger.warning(
                    f"VisualDirector: JSON parse/validate failed (attempt {attempt + 1}/{_JSON_RETRIES + 1}), retrying"
                )
                fix_prompt = (
                    f"Your previous response was not valid JSON or failed validation.\n\n"
                    f"Invalid output:\n{raw_text[:3000]}\n\n"
                    f"Required schema:\n{_OUTPUT_SCHEMA}\n\n"
                    f"Return ONLY JSON, no markdown, no commentary."
                )
                retry_text = self._gemini_generate([fix_prompt])
                if retry_text is None:
                    break
                raw_text = retry_text

        logger.warning("VisualDirector: all parse/validate attempts failed, returning empty")
        return dict(_EMPTY_RESULT)

    def _try_parse_json(self, raw: str) -> Optional[dict]:
        """Attempt to parse raw text as JSON. Strips markdown fences if present."""
        raw = raw.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[-1].strip() == "```":
                raw = "\n".join(lines[1:-1])
            else:
                raw = "\n".join(lines[1:])
            raw = raw.strip()

        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def _validate_result(self, data: dict) -> Optional[dict]:
        """Validate the parsed Gemini output. Returns cleaned dict or None."""
        overlays_raw = data.get("overlays")
        broll_raw = data.get("broll")

        if not isinstance(overlays_raw, list) or not isinstance(broll_raw, list):
            return None

        valid_overlays: list[dict] = []
        for ov in overlays_raw:
            if not isinstance(ov, dict):
                continue
            v = self._validate_overlay(ov)
            if v is not None:
                valid_overlays.append(v)

        valid_broll: list[dict] = []
        for br in broll_raw:
            if not isinstance(br, dict):
                continue
            v = self._validate_broll(br)
            if v is not None:
                valid_broll.append(v)

        # Enforce max counts
        valid_overlays = sorted(valid_overlays, key=lambda x: x["start_orig"])[:_MAX_OVERLAYS]
        valid_broll = sorted(valid_broll, key=lambda x: x["start_orig"])[:_MAX_BROLL]

        return {"overlays": valid_overlays, "broll": valid_broll}

    def _validate_overlay(self, ov: dict) -> Optional[dict]:
        """Validate a single overlay item. Returns cleaned dict or None."""
        try:
            start = float(ov.get("start_orig", -1))
            end = float(ov.get("end_orig", -1))
        except (ValueError, TypeError):
            return None

        if end <= start or (end - start) < 0.15:
            return None

        image_prompt = ov.get("image_prompt", "")
        if not isinstance(image_prompt, str) or not image_prompt.strip():
            return None

        # Validate placement
        pl = ov.get("placement")
        if not isinstance(pl, dict):
            return None
        try:
            px = float(pl.get("x", -1))
            py = float(pl.get("y", -1))
            pw = float(pl.get("w", -1))
        except (ValueError, TypeError):
            return None
        if not (0 <= px <= 1 and 0 <= py <= 1 and 0 <= pw <= 1):
            return None

        # Validate animation
        an = ov.get("animation")
        if not isinstance(an, dict):
            return None
        try:
            fade_in = float(an.get("fade_in", -1))
            fade_out = float(an.get("fade_out", -1))
        except (ValueError, TypeError):
            return None
        if fade_in < 0 or fade_out < 0:
            return None

        reason = str(ov.get("reason", ""))

        return {
            "start_orig": round(start, 3),
            "end_orig": round(end, 3),
            "image_prompt": image_prompt.strip(),
            "placement": {"x": round(px, 3), "y": round(py, 3), "w": round(pw, 3)},
            "animation": {"fade_in": round(fade_in, 3), "fade_out": round(fade_out, 3)},
            "reason": reason,
        }

    def _validate_broll(self, br: dict) -> Optional[dict]:
        """Validate a single b-roll item. Returns cleaned dict or None."""
        try:
            start = float(br.get("start_orig", -1))
            end = float(br.get("end_orig", -1))
        except (ValueError, TypeError):
            return None

        if end <= start or (end - start) < 0.3:
            return None

        query = br.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return None

        reason = str(br.get("reason", ""))

        return {
            "start_orig": round(start, 3),
            "end_orig": round(end, 3),
            "query": query.strip(),
            "reason": reason,
        }
