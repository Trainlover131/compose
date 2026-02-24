"""Unit tests for helvetica_punch caption style — no network calls."""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from apps.api.services.render_compiler import (
    _chunk_words_micro,
    _format_ass_time,
    _pick_helvetica_font,
    generate_ass_subtitles,
    _HELVETICA_FONT_FALLBACK,
)
from apps.api.models.schemas import EditPlan


class TestChunkWordsMicro(unittest.TestCase):
    """Verify 1–3 word micro-chunking with pause-awareness."""

    def _words(self, data):
        """Helper: list of {word, start, end} dicts."""
        return [{"word": w, "start": s, "end": e} for w, s, e in data]

    def test_three_words_single_chunk(self):
        words = self._words([("Hello", 0.0, 0.3), ("beautiful", 0.35, 0.7), ("world", 0.75, 1.0)])
        chunks = _chunk_words_micro(words, max_words=3)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "Hello beautiful world")
        self.assertAlmostEqual(chunks[0]["start"], 0.0)
        # Verify raw words are preserved for karaoke timing
        self.assertEqual(len(chunks[0]["words"]), 3)
        self.assertEqual(chunks[0]["words"][0]["word"], "Hello")

    def test_four_words_splits_at_three(self):
        words = self._words([
            ("one", 0.0, 0.2), ("two", 0.25, 0.4),
            ("three", 0.45, 0.6), ("four", 0.65, 0.8),
        ])
        chunks = _chunk_words_micro(words, max_words=3)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["text"], "one two three")
        self.assertEqual(chunks[1]["text"], "four")

    def test_pause_splits_chunk(self):
        words = self._words([
            ("yes", 0.0, 0.2),
            ("no", 1.0, 1.2),  # 0.8s gap > 0.35s threshold
        ])
        chunks = _chunk_words_micro(words, max_words=3, pause_threshold=0.35)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["text"], "yes")
        self.assertEqual(chunks[1]["text"], "no")

    def test_end_pad_applied(self):
        words = self._words([("word", 1.0, 1.5)])
        chunks = _chunk_words_micro(words, end_pad=0.06)
        self.assertEqual(len(chunks), 1)
        self.assertAlmostEqual(chunks[0]["end"], 1.56)

    def test_empty_input(self):
        self.assertEqual(_chunk_words_micro([]), [])

    def test_single_word(self):
        words = self._words([("solo", 2.0, 2.5)])
        chunks = _chunk_words_micro(words, max_words=3)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "solo")

    def test_exactly_max_words_no_leftover(self):
        words = self._words([
            ("a", 0.0, 0.1), ("b", 0.15, 0.2), ("c", 0.25, 0.3),
        ])
        chunks = _chunk_words_micro(words, max_words=3)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "a b c")

    def test_six_words_two_chunks(self):
        words = self._words([
            ("a", 0.0, 0.1), ("b", 0.12, 0.2), ("c", 0.22, 0.3),
            ("d", 0.32, 0.4), ("e", 0.42, 0.5), ("f", 0.52, 0.6),
        ])
        chunks = _chunk_words_micro(words, max_words=3)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["text"], "a b c")
        self.assertEqual(chunks[1]["text"], "d e f")


class TestFontFallback(unittest.TestCase):
    """Verify font fallback order."""

    def test_fallback_order(self):
        self.assertEqual(
            _HELVETICA_FONT_FALLBACK,
            ("Liberation Sans", "Nimbus Sans", "DejaVu Sans"),
        )

    def test_pick_returns_string(self):
        font = _pick_helvetica_font()
        self.assertIsInstance(font, str)
        self.assertIn(font, _HELVETICA_FONT_FALLBACK)


class TestHelveticaPunchASS(unittest.TestCase):
    """End-to-end test: generate ASS with helvetica_punch style."""

    def _make_plan(self, style_id="helvetica_punch"):
        return EditPlan.model_validate({
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 30},
            "main_cuts": [{"start": 0.0, "end": 10.0}],
            "punch_ins": [],
            "broll": {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            "overlays": {"enabled": False, "items": []},
            "captions": {
                "enabled": True,
                "style_id": style_id,
                "max_words_per_line": 3,
                "max_lines": 1,
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        })

    def _make_transcript(self):
        return {
            "text": "This is a test of the captions",
            "segments": [{
                "id": 0,
                "start": 0.0,
                "end": 3.0,
                "text": "This is a test of the captions",
                "words": [
                    {"word": "This", "start": 0.0, "end": 0.3, "probability": 0.99},
                    {"word": "is", "start": 0.35, "end": 0.5, "probability": 0.99},
                    {"word": "a", "start": 0.55, "end": 0.6, "probability": 0.99},
                    {"word": "test", "start": 0.65, "end": 0.9, "probability": 0.99},
                    {"word": "of", "start": 0.95, "end": 1.1, "probability": 0.99},
                    {"word": "the", "start": 1.15, "end": 1.3, "probability": 0.99},
                    {"word": "captions", "start": 1.35, "end": 1.8, "probability": 0.99},
                ],
            }],
            "language": "en",
        }

    def test_generates_micro_chunks(self):
        plan = self._make_plan()
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            result = generate_ass_subtitles(transcript, plan, path)
            self.assertEqual(result, path)
            with open(path) as f:
                content = f.read()

            # Should contain Liberation Sans (or fallback font)
            self.assertIn("Liberation Sans", content)

            # Should have MarginV=346 (lower-middle center)
            self.assertIn(",346,", content)

            # Count Dialogue lines — 7 words / 3-word chunks = ~3 chunks
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            self.assertGreaterEqual(len(dialogues), 2)
            self.assertLessEqual(len(dialogues), 4)

            # Every Dialogue must have karaoke tags and alignment override
            for d in dialogues:
                text = d.split(",,", 1)[-1]
                self.assertIn("{\\an2}", text)
                self.assertIn("{\\k", text)
                self.assertNotIn("\\pos", text)
        finally:
            os.unlink(path)

    def test_ass_times_correct(self):
        """Verify ASS timestamps match word-level timing (mapped through timeline)."""
        plan = self._make_plan()
        transcript = {
            "text": "Hello world",
            "segments": [{
                "id": 0, "start": 0.0, "end": 1.0, "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 0.5, "end": 0.8, "probability": 0.99},
                    {"word": "world", "start": 0.85, "end": 1.0, "probability": 0.99},
                ],
            }],
            "language": "en",
        }
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            self.assertEqual(len(dialogues), 1)
            d = dialogues[0]
            text = d.split(",,", 1)[-1]
            # Karaoke tags present for each word
            self.assertIn("{\\an2}", text)
            self.assertIn("{\\k", text)
            self.assertIn("Hello", text)
            self.assertIn("world", text)
            # Start should be 0:00:00.50 (0.5s)
            self.assertIn("0:00:00.50", d)
            # No \\pos overrides
            self.assertNotIn("\\pos", text)
            # Verify karaoke centisecond values:
            # Hello: 0.5 -> 0.85 (next word start) = 0.35s = 35cs
            # world: 0.85 -> 1.0 (chunk end) = 0.15s = 15cs
            self.assertIn("{\\k35}", text)
            self.assertIn("{\\k15}", text)
        finally:
            os.unlink(path)

    def test_standard_style_unchanged(self):
        """Verify non-punch styles still use the standard chunking path."""
        plan = self._make_plan(style_id="snappy")
        plan.captions.max_words_per_line = 4
        plan.captions.max_lines = 2
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # Should use Inter font (not Liberation Sans)
            self.assertIn("Inter", content)
            # Should use MarginV=180 (standard)
            self.assertIn(",180,", content)
        finally:
            os.unlink(path)


class TestDefaultPresetUsesHelveticaPunch(unittest.TestCase):
    """Verify the default preset (snappy-creator) ships with helvetica_punch."""

    def test_default_preset_caption_style(self):
        from apps.api.models.presets import get_preset

        preset = get_preset("snappy-creator")
        self.assertIsNotNone(preset)
        cap = preset["config"]["caption_style"]
        self.assertEqual(cap["style_id"], "helvetica_punch")
        self.assertEqual(cap["max_words_per_line"], 3)
        self.assertEqual(cap["max_lines"], 1)


if __name__ == "__main__":
    unittest.main()
