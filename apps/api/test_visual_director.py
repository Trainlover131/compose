#!/usr/bin/env python3
"""Dev test script: run VisualDirector on a local video and print results.

Usage:
  GEMINI_API_KEY=<key> python -m apps.api.test_visual_director <video_path> [--prompt "your prompt"]

Requires:
  - GEMINI_API_KEY env var set
  - google-genai package installed
  - A local video file

Prints:
  - Raw VisualDirector JSON (original timeline)
  - Mapped overlays/b-roll (final timeline, using dummy cuts)
"""

import argparse
import json
import logging
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _make_dummy_transcript(duration: float) -> dict:
    """Create a minimal transcript for testing when no real transcript exists."""
    return {
        "text": "Sample transcript for testing.",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": duration,
                "text": "Sample transcript for testing.",
                "words": [
                    {"word": "Sample", "start": 0.0, "end": 0.5},
                    {"word": "transcript", "start": 0.5, "end": 1.2},
                    {"word": "for", "start": 1.2, "end": 1.4},
                    {"word": "testing.", "start": 1.4, "end": 2.0},
                ],
            }
        ],
        "language": "en",
    }


def _probe_duration(path: str) -> float:
    """Get video duration via ffprobe."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json", "-show_format", path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 30))
    except Exception as e:
        print(f"ffprobe failed: {e}, using 30s default", file=sys.stderr)
    return 30.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test VisualDirector on a local video",
    )
    parser.add_argument("video_path", help="Path to local video file")
    parser.add_argument(
        "--prompt", default="Make this video engaging with overlays and b-roll",
        help="User editing prompt",
    )
    parser.add_argument(
        "--transcript-json", default=None,
        help="Path to transcript JSON file (optional; uses dummy if omitted)",
    )
    args = parser.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY env var must be set", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(args.video_path):
        print(f"ERROR: Video not found: {args.video_path}", file=sys.stderr)
        sys.exit(1)

    # Load or create transcript
    if args.transcript_json and os.path.isfile(args.transcript_json):
        with open(args.transcript_json) as f:
            transcript = json.load(f)
    else:
        duration = _probe_duration(args.video_path)
        transcript = _make_dummy_transcript(duration)
        print(f"Using dummy transcript (video duration: {duration:.1f}s)")

    duration = _probe_duration(args.video_path)

    # Run VisualDirector
    from apps.api.visual_director import VisualDirector

    vd = VisualDirector()
    print(f"\n--- Running VisualDirector ---")
    print(f"Video: {args.video_path}")
    print(f"Prompt: {args.prompt}")
    print()

    result = vd.propose(
        video_path=args.video_path,
        transcript=transcript,
        prompt=args.prompt,
        video_duration=duration,
    )

    print("\n=== RAW VisualDirector Output (ORIGINAL timeline) ===")
    print(json.dumps(result, indent=2))

    # Demonstrate timeline mapping with simple identity cuts
    from apps.api.services.planner import (
        _build_timeline_map_from_cuts,
        _map_vd_overlays,
        _map_vd_broll,
        _enforce_nonoverlap,
    )

    # Use whole video as one cut for demo mapping
    dummy_cuts = [{"start": 0.0, "end": duration}]
    tmap = _build_timeline_map_from_cuts(dummy_cuts)

    if result["overlays"]:
        mapped_ov = _map_vd_overlays(result["overlays"], tmap)
        mapped_ov = _enforce_nonoverlap(mapped_ov)
        print(f"\n=== Mapped Overlays (FINAL timeline) [{len(mapped_ov)}] ===")
        print(json.dumps(mapped_ov, indent=2))

    if result["broll"]:
        mapped_br = _map_vd_broll(result["broll"], tmap)
        mapped_br = _enforce_nonoverlap(mapped_br)
        print(f"\n=== Mapped B-Roll (FINAL timeline) [{len(mapped_br)}] ===")
        print(json.dumps(mapped_br, indent=2))

    print("\nDone.")


if __name__ == "__main__":
    main()
