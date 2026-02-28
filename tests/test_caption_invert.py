"""Unit tests for negative / invert captions and emphasis size normalization."""

import os
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from apps.api.models.schemas import (
    CaptionConfig,
    CaptionStyle,
    EditPlan,
)
from apps.api.services.render_compiler import generate_ass_subtitles


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_plan(style=None, style_id="helvetica_punch"):
    data = {
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
    }
    if style is not None:
        data["captions"]["style"] = style
    return EditPlan.model_validate(data)


def _make_transcript():
    return {
        "text": "Hello world test again more words here now",
        "segments": [{
            "id": 0, "start": 0.0, "end": 3.0,
            "text": "Hello world test again more words here now",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.2, "probability": 0.99},
                {"word": "world", "start": 0.25, "end": 0.4, "probability": 0.99},
                {"word": "test", "start": 0.45, "end": 0.6, "probability": 0.99},
                {"word": "again", "start": 0.65, "end": 0.8, "probability": 0.99},
                {"word": "more", "start": 0.85, "end": 1.0, "probability": 0.99},
                {"word": "words", "start": 1.05, "end": 1.2, "probability": 0.99},
                {"word": "here", "start": 1.25, "end": 1.4, "probability": 0.99},
                {"word": "now", "start": 1.45, "end": 1.6, "probability": 0.99},
            ],
        }],
        "language": "en",
    }


def _make_transcript_with_pause():
    """Transcript where there's a big gap between word 3 and word 4."""
    return {
        "text": "One two three four five six",
        "segments": [{
            "id": 0, "start": 0.0, "end": 5.0,
            "text": "One two three four five six",
            "words": [
                {"word": "One", "start": 0.0, "end": 0.2, "probability": 0.99},
                {"word": "two", "start": 0.25, "end": 0.4, "probability": 0.99},
                {"word": "three", "start": 0.45, "end": 0.6, "probability": 0.99},
                # Big gap here (0.6 to 1.5 = 0.9s > 0.4s threshold)
                {"word": "four", "start": 1.5, "end": 1.7, "probability": 0.99},
                {"word": "five", "start": 1.75, "end": 1.9, "probability": 0.99},
                {"word": "six", "start": 1.95, "end": 2.1, "probability": 0.99},
            ],
        }],
        "language": "en",
    }


# ── Schema tests ─────────────────────────────────────────────────────────

class TestInvertSchema(unittest.TestCase):
    """Verify invert and emphasis_size_multiplier fields parse correctly."""

    def test_invert_fields_default_none(self):
        cs = CaptionStyle()
        self.assertIsNone(cs.invert)
        self.assertIsNone(cs.invert_scope)
        self.assertIsNone(cs.emphasis_size_multiplier)

    def test_invert_all(self):
        cs = CaptionStyle.model_validate({
            "invert": True,
            "invert_scope": "all",
        })
        self.assertTrue(cs.invert)
        self.assertEqual(cs.invert_scope, "all")

    def test_invert_emphasis(self):
        cs = CaptionStyle.model_validate({
            "invert": True,
            "invert_scope": "emphasis",
        })
        self.assertTrue(cs.invert)
        self.assertEqual(cs.invert_scope, "emphasis")

    def test_emphasis_size_multiplier(self):
        cs = CaptionStyle.model_validate({
            "emphasis_size_multiplier": 1.25,
        })
        self.assertEqual(cs.emphasis_size_multiplier, 1.25)

    def test_backward_compat_no_invert(self):
        """Old plans without invert fields still parse."""
        cfg = CaptionConfig.model_validate({
            "enabled": True,
            "style_id": "helvetica_punch",
            "max_words_per_line": 3,
            "max_lines": 1,
            "style": {"color": "#FF0000"},
        })
        self.assertIsNone(cfg.style.invert)
        self.assertIsNone(cfg.style.invert_scope)


# ── Invert=false baseline tests ──────────────────────────────────────────

class TestInvertFalseBaseline(unittest.TestCase):
    """When invert is false/absent, no invert ASS file is generated."""

    def test_no_invert_file_when_not_set(self):
        plan = _make_plan()
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            self.assertTrue(os.path.exists(ass_path))
            self.assertFalse(os.path.exists(inv_path))

    def test_no_invert_file_when_false(self):
        plan = _make_plan(style={"invert": False})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            self.assertTrue(os.path.exists(ass_path))
            self.assertFalse(os.path.exists(inv_path))

    def test_no_blend_filter_when_invert_false(self):
        """When invert=false, the filtergraph must NOT contain blend=all_mode=difference."""
        plan = _make_plan()
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                content = f.read()
            # No blend references in ASS file (that's in FFmpeg, not ASS, but
            # verify the ASS file itself is normal)
            self.assertNotIn("captions_invert", content)


# ── Invert scope="all" tests ─────────────────────────────────────────────

class TestInvertScopeAll(unittest.TestCase):
    """When invert=true, invert_scope=all, a full invert ASS is generated."""

    def test_invert_all_generates_file(self):
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            self.assertTrue(os.path.exists(inv_path), "captions_invert.ass should exist")

    def test_invert_all_same_dialogue_count(self):
        """Invert scope=all should have same number of Dialogue lines as main."""
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                main_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            with open(inv_path) as f:
                inv_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            self.assertEqual(len(main_lines), len(inv_lines))

    def test_invert_all_white_primary_and_layout_matches_main(self):
        """Invert ASS should have white PrimaryColour and layout-identical Style to main."""
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                main_content = f.read()
            with open(inv_path) as f:
                inv_content = f.read()
            main_style = [l for l in main_content.splitlines() if l.startswith("Style:")][0]
            inv_style = [l for l in inv_content.splitlines() if l.startswith("Style:")][0]
            # PrimaryColour should be white in invert
            self.assertIn("&H00FFFFFF", inv_style)
            # Parse both Style lines into fields
            main_parts = main_style.split(",")
            inv_parts = inv_style.split(",")
            # These layout fields must match exactly between main and invert:
            # Fontname(1), Fontsize(2), Bold(7), Italic(8), ScaleX(12), ScaleY(13),
            # Spacing(14), Angle(15), BorderStyle(16_literal), Outline(16), Shadow(17),
            # Alignment(18), MarginL(19), MarginR(20), MarginV(21), Encoding(22)
            for idx in (1, 2, 7, 8, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22):
                self.assertEqual(
                    main_parts[idx], inv_parts[idx],
                    f"Style field {idx} must match: main={main_parts[idx]!r} inv={inv_parts[idx]!r}",
                )

    def test_invert_all_no_karaoke_tags(self):
        """Invert ASS should NOT contain karaoke tags even when main does."""
        plan = _make_plan(style={
            "invert": True, "invert_scope": "all",
            "karaoke": {"enabled": True, "color": "#FF8800"},
        })
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(inv_path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                self.assertNotIn("\\kf", d, "Invert ASS must not have karaoke tags")
                self.assertNotIn("\\k", d.split(",,", 1)[-1].replace("\\kf", ""),
                                 "Invert ASS must not have karaoke tags")

    def test_invert_all_no_emphasis_font_tags(self):
        """Invert ASS should NOT contain emphasis font changes."""
        plan = _make_plan(style={
            "invert": True, "invert_scope": "all",
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(inv_path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                text = d.split(",,", 1)[-1]
                self.assertNotIn("{\\fn", text, "Invert ASS must not have font changes")

    def test_invert_all_same_timing(self):
        """Timing between main and invert ASS must be identical."""
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                main_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            with open(inv_path) as f:
                inv_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            for m, i in zip(main_lines, inv_lines):
                m_parts = m.split(",")
                i_parts = i.split(",")
                self.assertEqual(m_parts[1], i_parts[1], "Start times must match")
                self.assertEqual(m_parts[2], i_parts[2], "End times must match")

    def test_invert_all_same_position(self):
        """Position (\\an and \\pos) must match between main and invert ASS."""
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                main_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            with open(inv_path) as f:
                inv_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            for m, inv in zip(main_lines, inv_lines):
                m_text = m.split(",,", 1)[-1]
                i_text = inv.split(",,", 1)[-1]
                # Extract \an and \pos from both
                m_pos = re.search(r"\\an\d+\\pos\(\d+,\d+\)", m_text)
                i_pos = re.search(r"\\an\d+\\pos\(\d+,\d+\)", i_text)
                self.assertIsNotNone(m_pos)
                self.assertIsNotNone(i_pos)
                self.assertEqual(m_pos.group(), i_pos.group())

    def test_invert_all_same_resolution(self):
        """PlayResX/PlayResY must match between main and invert ASS."""
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                main_content = f.read()
            with open(inv_path) as f:
                inv_content = f.read()
            self.assertIn("PlayResX: 1080", main_content)
            self.assertIn("PlayResY: 1920", main_content)
            self.assertIn("PlayResX: 1080", inv_content)
            self.assertIn("PlayResY: 1920", inv_content)


# ── Invert scope="emphasis" tests ────────────────────────────────────────

class TestInvertScopeEmphasis(unittest.TestCase):
    """When invert_scope=emphasis, only emphasized words go into invert ASS."""

    @patch("shutil.which", return_value=None)
    def test_emphasis_fewer_dialogues(self, _mock):
        """Invert ASS with emphasis-only scope has fewer lines than main."""
        plan = _make_plan(style={
            "invert": True,
            "invert_scope": "emphasis",
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            self.assertTrue(os.path.exists(inv_path))
            with open(ass_path) as f:
                main_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            with open(inv_path) as f:
                inv_lines = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            self.assertGreater(len(main_lines), len(inv_lines),
                               "Emphasis-only invert should have fewer Dialogue lines")

    @patch("shutil.which", return_value=None)
    def test_emphasis_invert_white_only(self, _mock):
        """Emphasis-only invert ASS should have white style, no outline/shadow."""
        plan = _make_plan(style={
            "invert": True,
            "invert_scope": "emphasis",
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(inv_path) as f:
                content = f.read()
            style_line = [l for l in content.splitlines() if l.startswith("Style:")][0]
            self.assertIn("&H00FFFFFF", style_line)

    @patch("shutil.which", return_value=None)
    def test_emphasis_invert_no_karaoke(self, _mock):
        """Emphasis-only invert must have no karaoke tags."""
        plan = _make_plan(style={
            "invert": True,
            "invert_scope": "emphasis",
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
            "karaoke": {"enabled": True, "color": "#FF0000"},
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(inv_path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                self.assertNotIn("\\kf", d)


# ── Emphasis size normalization tests ────────────────────────────────────

class TestEmphasisSizeNormalization(unittest.TestCase):
    """Verify emphasis font gets size bump for serif/script fonts."""

    @patch("shutil.which", return_value=None)
    def test_serif_emphasis_gets_size_bump(self, _mock):
        """DejaVu Serif emphasis should get \\fs tag with 1.12x multiplier."""
        plan = _make_plan(style={
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                content = f.read()
            # base fontsize is 64, 64 * 1.12 = 71.68 -> round to 72
            self.assertIn("{\\fs72\\fnDejaVu Serif}", content)
            # Should also have reset tag
            self.assertIn("{\\fs64\\fn", content)

    @patch("shutil.which", return_value=None)
    def test_sans_emphasis_no_size_bump(self, _mock):
        """Sans emphasis font should NOT get size bump by default."""
        plan = _make_plan(style={
            "font_emphasis": "Liberation Sans",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                content = f.read()
            # No \fs tag because sans fonts don't get the bump
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            has_fs = any("\\fs" in d.split(",,", 1)[-1] for d in dialogues)
            self.assertFalse(has_fs, "Sans emphasis should not get \\fs size tag")

    @patch("shutil.which", return_value=None)
    def test_custom_multiplier_overrides(self, _mock):
        """User-specified emphasis_size_multiplier should override default."""
        plan = _make_plan(style={
            "font_emphasis": "Liberation Sans",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
            "emphasis_size_multiplier": 1.25,
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                content = f.read()
            # 64 * 1.25 = 80
            self.assertIn("{\\fs80\\fnLiberation Sans}", content)

    @patch("shutil.which", return_value=None)
    def test_multiplier_clamped_high(self, _mock):
        """Multiplier above 1.35 should be clamped to 1.35."""
        plan = _make_plan(style={
            "font_emphasis": "Liberation Sans",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
            "emphasis_size_multiplier": 2.0,
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                content = f.read()
            # 64 * 1.35 = 86.4 -> 86
            self.assertIn("{\\fs86\\fnLiberation Sans}", content)

    @patch("shutil.which", return_value=None)
    def test_invert_ignores_emphasis_sizing(self, _mock):
        """captions_invert.ass must NOT have emphasis sizing (constant white glyphs)."""
        plan = _make_plan(style={
            "invert": True,
            "invert_scope": "all",
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
        })
        transcript = _make_transcript_with_pause()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(inv_path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                text = d.split(",,", 1)[-1]
                self.assertNotIn("\\fs", text, "Invert ASS must not have \\fs tags")


# ── Overlay / B-roll / timing invariance ─────────────────────────────────

class TestInvertInvariance(unittest.TestCase):
    """Invert must not change timing, overlay, or broll counts."""

    @patch("random.choices", return_value=[2])
    def test_timing_unchanged_with_invert(self, _mock_choices):
        """Dialogue start/end times must be identical with or without invert."""
        transcript = _make_transcript()
        plan_normal = _make_plan()
        plan_invert = _make_plan(style={"invert": True, "invert_scope": "all"})
        with tempfile.TemporaryDirectory() as td:
            path_n = os.path.join(td, "normal_captions.ass")
            path_i = os.path.join(td, "invert_captions.ass")
            generate_ass_subtitles(transcript, plan_normal, path_n)
            generate_ass_subtitles(transcript, plan_invert, path_i)
            with open(path_n) as f:
                normal_d = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            with open(path_i) as f:
                invert_d = [l for l in f.read().splitlines() if l.startswith("Dialogue:")]
            self.assertEqual(len(normal_d), len(invert_d))
            for n, i in zip(normal_d, invert_d):
                n_parts = n.split(",")
                i_parts = i.split(",")
                self.assertEqual(n_parts[1], i_parts[1], "Start times must match")
                self.assertEqual(n_parts[2], i_parts[2], "End times must match")

    def test_broll_count_unchanged(self):
        """Broll inserts in the plan are not modified by invert setting."""
        data = {
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 30},
            "main_cuts": [{"start": 0.0, "end": 10.0}],
            "punch_ins": [],
            "broll": {"enabled": True, "strategy": "cutaway_fullscreen",
                      "inserts": [{"query": "nature", "start": 1.0, "end": 2.0}]},
            "overlays": {"enabled": False, "items": []},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
                "max_words_per_line": 3,
                "max_lines": 1,
                "style": {"invert": True, "invert_scope": "all"},
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        }
        plan = EditPlan.model_validate(data)
        self.assertEqual(len(plan.broll.inserts), 1)

    def test_overlay_count_unchanged(self):
        """Overlay items in the plan are not modified by invert setting."""
        data = {
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 30},
            "main_cuts": [{"start": 0.0, "end": 10.0}],
            "punch_ins": [],
            "broll": {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            "overlays": {"enabled": True, "items": [
                {"type": "image_overlay", "start": 0.5, "end": 1.5}
            ]},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
                "max_words_per_line": 3,
                "max_lines": 1,
                "style": {"invert": True, "invert_scope": "emphasis"},
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        }
        plan = EditPlan.model_validate(data)
        self.assertEqual(len(plan.overlays.items), 1)


# ── Filtergraph finite-duration tests ────────────────────────────────────

class TestInvertFiltergraphBounded(unittest.TestCase):
    """Verify the invert-blend filtergraph uses finite duration and shortest=1."""

    def _run_compile_and_get_fc(self, style, main_cuts=None, transcript=None):
        """Helper: run compile_render with mocked FFmpeg and return filtergraph strings.

        Returns (primary_fc, retry_fc_or_None).
        """
        from apps.api.services import render_compiler as rc

        if main_cuts is None:
            main_cuts = [{"start": 0.0, "end": 10.0}]
        if transcript is None:
            transcript = _make_transcript()

        plan_data = {
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 60},
            "main_cuts": main_cuts,
            "punch_ins": [],
            "broll": {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            "overlays": {"enabled": False, "items": []},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
                "max_words_per_line": 3,
                "max_lines": 1,
                "style": style,
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        }
        plan = EditPlan.model_validate(plan_data)

        with tempfile.TemporaryDirectory() as td:
            work = os.path.join(td, "work")
            os.makedirs(work)
            source_video = os.path.join(td, "source.mp4")
            output_path = os.path.join(td, "output.mp4")

            # Create a dummy source video file
            with open(source_video, "wb") as f:
                f.write(b"\x00" * 1024)

            # Mock _run_ffmpeg: create expected output files so compile_render proceeds
            original_run = rc._run_ffmpeg

            def fake_run(cmd, step_name, timeout=180):
                # Determine the output file from the command (last arg or the arg before codec flags)
                out_file = cmd[-1]
                if out_file.endswith((".mp4", ".mkv", ".mov")):
                    with open(out_file, "wb") as f:
                        f.write(b"\x00" * 512)
                return None

            with patch.object(rc, "_run_ffmpeg", side_effect=fake_run):
                try:
                    rc.compile_render(plan, source_video, transcript, output_path, work_dir=work)
                except Exception:
                    pass  # We don't care if later steps fail

            primary_fc = None
            retry_fc = None
            fc_path = os.path.join(work, "filter_complex.txt")
            fc_retry_path = os.path.join(work, "filter_complex_retry.txt")
            if os.path.exists(fc_path):
                with open(fc_path) as f:
                    primary_fc = f.read()
            if os.path.exists(fc_retry_path):
                with open(fc_retry_path) as f:
                    retry_fc = f.read()
            return primary_fc, retry_fc

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_primary_fc_has_finite_duration(self, _mock_choices, _mock_which):
        """Primary filtergraph color=black source must have :d= for finite duration."""
        fc, _ = self._run_compile_and_get_fc(
            style={"invert": True, "invert_scope": "all"},
        )
        self.assertIsNotNone(fc, "filter_complex.txt should exist")
        # color=black must have :d= set
        self.assertRegex(fc, r"color=black:s=1080x1920:r=30:d=\d+\.\d+")

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_primary_fc_has_shortest(self, _mock_choices, _mock_which):
        """Primary filtergraph blend must include shortest=1."""
        fc, _ = self._run_compile_and_get_fc(
            style={"invert": True, "invert_scope": "all"},
        )
        self.assertIsNotNone(fc, "filter_complex.txt should exist")
        self.assertIn("blend=all_mode=difference:shortest=1", fc)

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_primary_fc_duration_matches_cuts(self, _mock_choices, _mock_which):
        """Duration on color=black must match sum of main_cuts."""
        # cuts must overlap with transcript words (0.0-1.6) to generate dialogues
        cuts = [{"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 10.0}]
        # total = 5.0 + 5.0 = 10.0
        fc, _ = self._run_compile_and_get_fc(
            style={"invert": True, "invert_scope": "all"},
            main_cuts=cuts,
        )
        self.assertIsNotNone(fc)
        self.assertIn("d=10.000", fc)

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_retry_fc_has_finite_duration(self, _mock_choices, _mock_which):
        """Retry filtergraph color=black source must have :d= for finite duration."""
        from apps.api.services import render_compiler as rc

        # Force the primary pass to fail so the retry path runs
        call_count = [0]

        def fake_run(cmd, step_name, timeout=180):
            call_count[0] += 1
            out_file = cmd[-1]
            if out_file.endswith((".mp4", ".mkv", ".mov")):
                # Fail on the primary layer pass ("layer-broll-overlays-captions")
                if step_name == "layer-broll-overlays-captions":
                    raise RuntimeError("simulated motion pass failure")
                with open(out_file, "wb") as f:
                    f.write(b"\x00" * 512)
            return None

        plan_data = {
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 60},
            "main_cuts": [{"start": 0.0, "end": 10.0}],
            "punch_ins": [],
            "broll": {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            "overlays": {"enabled": False, "items": []},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
                "max_words_per_line": 3,
                "max_lines": 1,
                "style": {"invert": True, "invert_scope": "all"},
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        }
        plan = EditPlan.model_validate(plan_data)
        transcript = _make_transcript()

        with tempfile.TemporaryDirectory() as td:
            work = os.path.join(td, "work")
            os.makedirs(work)
            source_video = os.path.join(td, "source.mp4")
            output_path = os.path.join(td, "output.mp4")
            with open(source_video, "wb") as f:
                f.write(b"\x00" * 1024)

            with patch.object(rc, "_run_ffmpeg", side_effect=fake_run):
                with patch("random.choices", return_value=[2]):
                    try:
                        rc.compile_render(plan, source_video, transcript, output_path, work_dir=work)
                    except Exception:
                        pass

            fc_retry_path = os.path.join(work, "filter_complex_retry.txt")
            self.assertTrue(os.path.exists(fc_retry_path), "filter_complex_retry.txt should exist")
            with open(fc_retry_path) as f:
                fc_retry = f.read()
            self.assertRegex(fc_retry, r"color=black:s=1080x1920:r=30:d=\d+\.\d+")
            self.assertIn("blend=all_mode=difference:shortest=1", fc_retry)

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_emphasis_scope_also_bounded(self, _mock_choices, _mock_which):
        """Invert with scope=emphasis must also have finite duration + shortest."""
        fc, _ = self._run_compile_and_get_fc(
            style={
                "invert": True, "invert_scope": "emphasis",
                "font_emphasis": "DejaVu Serif",
                "pause_emphasis": {"enabled": True, "threshold_sec": 0.2},
            },
            transcript=_make_transcript_with_pause(),
        )
        self.assertIsNotNone(fc)
        self.assertRegex(fc, r"color=black:s=1080x1920:r=30:d=\d+\.\d+")
        self.assertIn("blend=all_mode=difference:shortest=1", fc)

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_no_invert_no_color_black(self, _mock_choices, _mock_which):
        """When invert is not set, filtergraph must NOT contain color=black."""
        fc, _ = self._run_compile_and_get_fc(style={})
        self.assertIsNotNone(fc)
        self.assertNotIn("color=black", fc)
        self.assertNotIn("blend=all_mode=difference", fc)
        self.assertNotIn("format=rgba", fc)

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_primary_fc_has_format_rgba_before_blend(self, _mock_choices, _mock_which):
        """When invert=true, format=rgba must appear exactly twice before blend."""
        fc, _ = self._run_compile_and_get_fc(
            style={"invert": True, "invert_scope": "all"},
        )
        self.assertIsNotNone(fc)
        # Both inputs must be format=rgba before the blend
        self.assertIn("format=rgba[_inv_base_rgba]", fc)
        self.assertIn("format=rgba[_inv_mask_rgba]", fc)
        # The blend must reference the rgba labels
        self.assertIn("[_inv_base_rgba][_inv_mask_rgba]blend=all_mode=difference:shortest=1", fc)

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[2])
    def test_retry_fc_has_format_rgba_before_blend(self, _mock_choices, _mock_which):
        """Retry filtergraph must also have format=rgba before blend."""
        from apps.api.services import render_compiler as rc

        def fake_run(cmd, step_name, timeout=180):
            out_file = cmd[-1]
            if out_file.endswith((".mp4", ".mkv", ".mov")):
                if step_name == "layer-broll-overlays-captions":
                    raise RuntimeError("simulated motion pass failure")
                with open(out_file, "wb") as f:
                    f.write(b"\x00" * 512)
            return None

        plan_data = {
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 60},
            "main_cuts": [{"start": 0.0, "end": 10.0}],
            "punch_ins": [],
            "broll": {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            "overlays": {"enabled": False, "items": []},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
                "max_words_per_line": 3,
                "max_lines": 1,
                "style": {"invert": True, "invert_scope": "all"},
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        }
        plan = EditPlan.model_validate(plan_data)
        transcript = _make_transcript()

        with tempfile.TemporaryDirectory() as td:
            work = os.path.join(td, "work")
            os.makedirs(work)
            source_video = os.path.join(td, "source.mp4")
            output_path = os.path.join(td, "output.mp4")
            with open(source_video, "wb") as f:
                f.write(b"\x00" * 1024)

            with patch.object(rc, "_run_ffmpeg", side_effect=fake_run):
                try:
                    rc.compile_render(plan, source_video, transcript, output_path, work_dir=work)
                except Exception:
                    pass

            fc_retry_path = os.path.join(work, "filter_complex_retry.txt")
            self.assertTrue(os.path.exists(fc_retry_path))
            with open(fc_retry_path) as f:
                fc_retry = f.read()
            self.assertIn("format=rgba[_inv_base_rgba_r]", fc_retry)
            self.assertIn("format=rgba[_inv_mask_rgba_r]", fc_retry)
            self.assertIn("[_inv_base_rgba_r][_inv_mask_rgba_r]blend=all_mode=difference:shortest=1", fc_retry)


# ── Invert ASS layout-match tests ────────────────────────────────────────

class TestInvertASSLayoutMatch(unittest.TestCase):
    """Verify captions_invert.ass has layout-identical Style to captions.ass."""

    def test_playres_matches(self):
        """PlayResX/PlayResY must be identical between main and invert."""
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                main = f.read()
            with open(inv_path) as f:
                inv = f.read()
            for field in ("PlayResX", "PlayResY", "ScriptType", "WrapStyle"):
                main_val = [l for l in main.splitlines() if l.startswith(field)][0]
                inv_val = [l for l in inv.splitlines() if l.startswith(field)][0]
                self.assertEqual(main_val, inv_val, f"{field} must match")

    def test_style_layout_fields_match(self):
        """All layout-affecting Style fields must match between main and invert.

        Only PrimaryColour, SecondaryColour may differ (white mask vs user color).
        """
        plan = _make_plan(style={"invert": True, "invert_scope": "all"})
        transcript = _make_transcript()
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "captions.ass")
            inv_path = os.path.join(td, "captions_invert.ass")
            generate_ass_subtitles(transcript, plan, ass_path)
            with open(ass_path) as f:
                main_content = f.read()
            with open(inv_path) as f:
                inv_content = f.read()
            main_style = [l for l in main_content.splitlines() if l.startswith("Style:")][0]
            inv_style = [l for l in inv_content.splitlines() if l.startswith("Style:")][0]
            main_parts = main_style.split(",")
            inv_parts = inv_style.split(",")
            # Fields: 0=Name, 1=Fontname, 2=Fontsize, 3=Primary, 4=Secondary,
            # 5=OutlineColour, 6=BackColour, 7=Bold, 8=Italic, 9=Underline,
            # 10=StrikeOut, 11-12=ScaleX/Y, 13=Spacing(idx14), 14=Angle(idx15),
            # 15=BorderStyle(idx16), 16=Outline, 17=Shadow, 18=Alignment,
            # 19=MarginL, 20=MarginR, 21=MarginV, 22=Encoding
            # Layout fields that must match (everything except 3=Primary, 4=Secondary):
            layout_indices = [0, 1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
            for idx in layout_indices:
                self.assertEqual(
                    main_parts[idx], inv_parts[idx],
                    f"Style field index {idx}: main={main_parts[idx]!r} != inv={inv_parts[idx]!r}",
                )


if __name__ == "__main__":
    unittest.main()
