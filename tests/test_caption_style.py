"""Unit tests for captions.style customization — no network calls."""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from apps.api.models.schemas import (
    CaptionConfig,
    CaptionKaraokeStyle,
    CaptionPatch,
    CaptionPauseEmphasis,
    CaptionStyle,
    EditPlan,
)
from apps.api.services.render_compiler import (
    _apply_caption_style,
    _clamp,
    _hex_to_ass_color,
    _resolve_font,
    generate_ass_subtitles,
)


# ── Schema tests ─────────────────────────────────────────────────────────

class TestCaptionStyleSchema(unittest.TestCase):
    """Verify CaptionStyle schema is additive and backward compatible."""

    def test_caption_config_without_style(self):
        """Old plans without style field still parse."""
        cfg = CaptionConfig.model_validate({
            "enabled": True,
            "style_id": "helvetica_punch",
            "max_words_per_line": 3,
            "max_lines": 1,
        })
        self.assertIsNone(cfg.style)

    def test_caption_config_with_style(self):
        cfg = CaptionConfig.model_validate({
            "enabled": True,
            "style_id": "helvetica_punch",
            "max_words_per_line": 3,
            "max_lines": 1,
            "style": {
                "font_primary": "Helvetica",
                "size": 72,
                "bold": True,
                "color": "#FF0000",
            },
        })
        self.assertIsNotNone(cfg.style)
        self.assertEqual(cfg.style.font_primary, "Helvetica")
        self.assertEqual(cfg.style.size, 72)
        self.assertTrue(cfg.style.bold)
        self.assertEqual(cfg.style.color, "#FF0000")
        # Unset fields remain None
        self.assertIsNone(cfg.style.italic)
        self.assertIsNone(cfg.style.y)
        self.assertIsNone(cfg.style.karaoke)

    def test_caption_config_partial_style(self):
        """Only font_primary specified, everything else None."""
        cfg = CaptionConfig.model_validate({
            "enabled": True,
            "style_id": "snappy",
            "max_words_per_line": 3,
            "max_lines": 1,
            "style": {"font_primary": "Inter"},
        })
        self.assertEqual(cfg.style.font_primary, "Inter")
        self.assertIsNone(cfg.style.font_emphasis)
        self.assertIsNone(cfg.style.size)

    def test_caption_config_with_karaoke(self):
        cfg = CaptionConfig.model_validate({
            "enabled": True,
            "style_id": "helvetica_punch",
            "max_words_per_line": 3,
            "max_lines": 1,
            "style": {
                "karaoke": {"enabled": True, "color": "#FF0000"},
            },
        })
        self.assertTrue(cfg.style.karaoke.enabled)
        self.assertEqual(cfg.style.karaoke.color, "#FF0000")

    def test_caption_patch_with_style(self):
        """CaptionPatch also supports the style field."""
        patch = CaptionPatch.model_validate({
            "style": {"size": 48, "tracking": -2},
        })
        self.assertIsNotNone(patch.style)
        self.assertEqual(patch.style.size, 48)
        self.assertEqual(patch.style.tracking, -2)

    def test_editplan_backward_compatible(self):
        """Full EditPlan without style field validates fine."""
        plan = EditPlan.model_validate({
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 30},
            "main_cuts": [{"start": 0.0, "end": 10.0}],
            "punch_ins": [],
            "broll": {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            "overlays": {"enabled": False, "items": []},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
                "max_words_per_line": 3,
                "max_lines": 1,
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        })
        self.assertIsNone(plan.captions.style)

    def test_editplan_with_style(self):
        """Full EditPlan with style field validates."""
        plan = EditPlan.model_validate({
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 30},
            "main_cuts": [{"start": 0.0, "end": 10.0}],
            "punch_ins": [],
            "broll": {"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            "overlays": {"enabled": False, "items": []},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
                "max_words_per_line": 3,
                "max_lines": 1,
                "style": {"font_primary": "Garamond", "size": 40, "y": 1400},
            },
            "music": {"enabled": False, "track_id": "upbeat-energy", "target_volume_db": -18.0},
            "rationale": {"hook": "test", "structure": []},
        })
        self.assertEqual(plan.captions.style.font_primary, "Garamond")
        self.assertEqual(plan.captions.style.size, 40)
        self.assertEqual(plan.captions.style.y, 1400)


# ── Clamping / validation tests ──────────────────────────────────────────

class TestClamping(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50, 24, 96, 64), 50)

    def test_clamp_below_min(self):
        self.assertEqual(_clamp(-999, -8, 8, 0), -8)

    def test_clamp_above_max(self):
        self.assertEqual(_clamp(999, 0, 10, 0), 10)

    def test_clamp_none_returns_default(self):
        self.assertEqual(_clamp(None, 0, 10, 5), 5)


class TestHexToAssColor(unittest.TestCase):

    def test_valid_color(self):
        self.assertEqual(_hex_to_ass_color("#FF0000"), "&H000000FF")

    def test_valid_color_white(self):
        self.assertEqual(_hex_to_ass_color("#FFFFFF"), "&H00FFFFFF")

    def test_valid_color_green(self):
        self.assertEqual(_hex_to_ass_color("#00FF00"), "&H0000FF00")

    def test_invalid_color_returns_default(self):
        self.assertEqual(_hex_to_ass_color("not-a-color"), "&H00FFFFFF")

    def test_none_returns_default(self):
        self.assertEqual(_hex_to_ass_color(None), "&H00FFFFFF")

    def test_custom_default(self):
        self.assertEqual(_hex_to_ass_color("bad", "&H00AABBCC"), "&H00AABBCC")

    def test_short_hex_rejected(self):
        self.assertEqual(_hex_to_ass_color("#FFF"), "&H00FFFFFF")


# ── Font resolution tests ────────────────────────────────────────────────

class TestFontResolution(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(_resolve_font(None))

    def test_empty_returns_none(self):
        self.assertIsNone(_resolve_font(""))

    @patch("shutil.which", return_value=None)
    def test_helvetica_alias_no_fclist(self, _mock_which):
        result = _resolve_font("Helvetica")
        self.assertEqual(result, "Liberation Sans")

    @patch("shutil.which", return_value=None)
    def test_garamond_alias_no_fclist(self, _mock_which):
        result = _resolve_font("Garamond")
        self.assertEqual(result, "EB Garamond")

    @patch("shutil.which", return_value=None)
    def test_unknown_font_falls_back(self, _mock_which):
        result = _resolve_font("SomeWeirdFont")
        # Falls back to Liberation Sans (first in helvetica fallback)
        self.assertEqual(result, "SomeWeirdFont")

    @patch("shutil.which", return_value="/usr/bin/fc-list")
    @patch("subprocess.check_output", return_value="DejaVu Sans\nLiberation Sans\n")
    def test_known_font_with_fclist(self, _mock_out, _mock_which):
        result = _resolve_font("Helvetica")
        # Liberation Sans is in the fc-list output and in the alias map
        self.assertEqual(result, "Liberation Sans")

    @patch("shutil.which", return_value="/usr/bin/fc-list")
    @patch("subprocess.check_output", return_value="DejaVu Sans\n")
    def test_alias_fallback_with_fclist(self, _mock_out, _mock_which):
        # Garamond -> tries EB Garamond (not installed), then DejaVu Serif (not installed)
        # Falls back to first candidate
        result = _resolve_font("Garamond")
        self.assertEqual(result, "EB Garamond")


# ── _apply_caption_style tests ───────────────────────────────────────────

class TestApplyCaptionStyle(unittest.TestCase):

    def _base_style(self):
        return {
            "fontname": "Liberation Sans",
            "fontsize": 64,
            "outline": 0,
            "shadow": 0,
            "bold": 1,
            "margin_v": 500,
            "spacing": -3,
        }

    def test_none_style_no_change(self):
        base = self._base_style()
        result = _apply_caption_style(base, None)
        self.assertEqual(result["fontsize"], 64)
        self.assertEqual(result["spacing"], -3)

    def test_size_clamped(self):
        base = self._base_style()
        cs = CaptionStyle(size=999)
        _apply_caption_style(base, cs)
        self.assertEqual(base["fontsize"], 96)

    def test_size_clamped_low(self):
        base = self._base_style()
        cs = CaptionStyle(size=5)
        _apply_caption_style(base, cs)
        self.assertEqual(base["fontsize"], 24)

    def test_tracking_clamped(self):
        base = self._base_style()
        cs = CaptionStyle(tracking=-999)
        _apply_caption_style(base, cs)
        self.assertEqual(base["spacing"], -8)

    def test_outline_clamped(self):
        base = self._base_style()
        cs = CaptionStyle(outline_width=20)
        _apply_caption_style(base, cs)
        self.assertEqual(base["outline"], 10)

    def test_shadow_clamped(self):
        base = self._base_style()
        cs = CaptionStyle(shadow_depth=15)
        _apply_caption_style(base, cs)
        self.assertEqual(base["shadow"], 10)

    def test_y_override_clamped(self):
        base = self._base_style()
        cs = CaptionStyle(y=100)
        _apply_caption_style(base, cs)
        self.assertEqual(base["_y_override"], 600)

    def test_y_override_valid(self):
        base = self._base_style()
        cs = CaptionStyle(y=1400)
        _apply_caption_style(base, cs)
        self.assertEqual(base["_y_override"], 1400)

    def test_align_override(self):
        base = self._base_style()
        cs = CaptionStyle(align=2)
        _apply_caption_style(base, cs)
        self.assertEqual(base["_align_override"], 2)

    def test_align_invalid_defaults_to_5(self):
        base = self._base_style()
        cs = CaptionStyle(align=99)
        _apply_caption_style(base, cs)
        self.assertEqual(base["_align_override"], 5)

    def test_color_override(self):
        base = self._base_style()
        cs = CaptionStyle(color="#FF0000")
        _apply_caption_style(base, cs)
        self.assertEqual(base["_primary_colour"], "&H000000FF")

    def test_italic_override(self):
        base = self._base_style()
        cs = CaptionStyle(italic=True)
        _apply_caption_style(base, cs)
        self.assertEqual(base["italic"], 1)

    def test_bold_false(self):
        base = self._base_style()
        cs = CaptionStyle(bold=False)
        _apply_caption_style(base, cs)
        self.assertEqual(base["bold"], 0)


# ── End-to-end ASS generation tests ──────────────────────────────────────

class TestCaptionStyleASS(unittest.TestCase):

    def _make_plan(self, style_id="helvetica_punch", style=None):
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

    def _make_transcript(self):
        return {
            "text": "Hello world test",
            "segments": [{
                "id": 0, "start": 0.0, "end": 2.0,
                "text": "Hello world test",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.3, "probability": 0.99},
                    {"word": "world", "start": 0.35, "end": 0.6, "probability": 0.99},
                    {"word": "test", "start": 0.65, "end": 0.9, "probability": 0.99},
                ],
            }],
            "language": "en",
        }

    def test_default_no_style_unchanged(self):
        """When captions.style is absent, output is same as before."""
        plan = self._make_plan()
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # Default white, no karaoke
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            self.assertGreater(len(dialogues), 0)
            for d in dialogues:
                text = d.split(",,", 1)[-1]
                self.assertIn("{\\an5\\pos(540,1180)}", text)
                self.assertNotIn("{\\k", text)
        finally:
            os.unlink(path)

    def test_karaoke_only_when_enabled(self):
        """Karaoke tags appear only when karaoke.enabled=True."""
        plan = self._make_plan(style={
            "karaoke": {"enabled": True, "color": "#FF0000"},
        })
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            self.assertGreater(len(dialogues), 0)
            # At least one dialogue line should have karaoke tags
            has_karaoke = any("{\\k" in d for d in dialogues)
            self.assertTrue(has_karaoke, "Expected karaoke tags when enabled")
            # SecondaryColour should be red (BGR for #FF0000 = 0000FF)
            self.assertIn("&H000000FF", content)
        finally:
            os.unlink(path)

    def test_karaoke_disabled_no_tags(self):
        """When karaoke.enabled=False, no karaoke tags."""
        plan = self._make_plan(style={
            "karaoke": {"enabled": False},
        })
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                self.assertNotIn("{\\k", d)
        finally:
            os.unlink(path)

    def test_custom_y_position(self):
        """Custom y position is applied."""
        plan = self._make_plan(style={"y": 1400})
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                text = d.split(",,", 1)[-1]
                self.assertIn("\\pos(540,1400)", text)
        finally:
            os.unlink(path)

    def test_custom_color_in_header(self):
        """Custom color appears in the ASS style line."""
        plan = self._make_plan(style={"color": "#00FF00"})
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # #00FF00 -> &H0000FF00
            self.assertIn("&H0000FF00", content)
        finally:
            os.unlink(path)

    def test_custom_size_in_header(self):
        """Custom size appears in the ASS style line."""
        plan = self._make_plan(style={"size": 48})
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # fontsize should be 48
            self.assertIn(",48,", content)
        finally:
            os.unlink(path)

    def test_style_does_not_affect_cinematic(self):
        """CaptionStyle is only applied to helvetica_punch/snappy, not cinematic."""
        plan = self._make_plan(style_id="cinematic", style={"size": 80, "y": 1400})
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # Cinematic default fontsize=48, should not be overridden
            self.assertIn(",48,", content)
            # Should not have \pos override
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                self.assertNotIn("\\pos", d)
        finally:
            os.unlink(path)

    def test_italic_in_ass_header(self):
        """Italic override appears in the ASS style."""
        plan = self._make_plan(style={"italic": True})
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # Bold=1, Italic=1 in style line
            style_line = [l for l in content.splitlines() if l.startswith("Style:")][0]
            # Format: ...,Bold,Italic,...
            # The style with bold=1, italic=1 should contain ",1,1,"
            self.assertIn(",1,1,", style_line)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
