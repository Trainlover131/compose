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
            # At least one dialogue line should have \kf karaoke fill tags
            has_karaoke = any("{\\kf" in d for d in dialogues)
            self.assertTrue(has_karaoke, "Expected \\kf karaoke tags when enabled")
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


# ── Karaoke \kf tag tests ─────────────────────────────────────────────────

class TestKaraokeFillTags(unittest.TestCase):
    r"""Verify \kf (fill) tags are used and PrimaryColour stays white."""

    def _make_plan(self, style=None):
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
                "style_id": "helvetica_punch",
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
            "text": "Hello world test again",
            "segments": [{
                "id": 0, "start": 0.0, "end": 2.0,
                "text": "Hello world test again",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.3, "probability": 0.99},
                    {"word": "world", "start": 0.35, "end": 0.6, "probability": 0.99},
                    {"word": "test", "start": 0.65, "end": 0.9, "probability": 0.99},
                    {"word": "again", "start": 0.95, "end": 1.2, "probability": 0.99},
                ],
            }],
            "language": "en",
        }

    def test_karaoke_uses_kf_tags(self):
        """Karaoke mode should emit \\kf (fill) tags, not plain \\k."""
        plan = self._make_plan(style={
            "karaoke": {"enabled": True, "color": "#FF8800"},
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
            import re
            has_kf = False
            for d in dialogues:
                text = d.split(",,", 1)[-1]
                kf_tags = re.findall(r"\\kf\d+", text)
                if kf_tags:
                    has_kf = True
                # Ensure no bare \k (without f) — \k\d+ but not \kf\d+
                bare_k = re.findall(r"\\k(?!f)\d+", text)
                self.assertEqual(len(bare_k), 0,
                                 f"Found bare \\k tags (should be \\kf): {bare_k}")
            self.assertTrue(has_kf, "Expected \\kf karaoke tags in output")
        finally:
            os.unlink(path)

    def test_karaoke_white_primary_colour(self):
        """With karaoke enabled, PrimaryColour should be white."""
        plan = self._make_plan(style={
            "karaoke": {"enabled": True, "color": "#FF8800"},
        })
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            style_line = [l for l in content.splitlines() if l.startswith("Style:")][0]
            # PrimaryColour is the 4th field (0-indexed: Name=0, Fontname=1, Fontsize=2, Primary=3)
            parts = style_line.split(",")
            primary = parts[3]
            self.assertEqual(primary, "&H00FFFFFF",
                             "PrimaryColour should be white when karaoke is on")
        finally:
            os.unlink(path)

    def test_karaoke_secondary_is_highlight_color(self):
        """SecondaryColour should be the karaoke highlight color."""
        plan = self._make_plan(style={
            "karaoke": {"enabled": True, "color": "#FF8800"},
        })
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            style_line = [l for l in content.splitlines() if l.startswith("Style:")][0]
            parts = style_line.split(",")
            secondary = parts[4]
            # #FF8800 => &H000088FF (BGR swap)
            self.assertEqual(secondary, "&H000088FF",
                             "SecondaryColour should be karaoke highlight color")
        finally:
            os.unlink(path)


# ── Non-karaoke orange color test ─────────────────────────────────────────

class TestNonKaraokeColor(unittest.TestCase):
    """When color is set but karaoke is off, no \\k tags should appear."""

    def _make_plan(self, style=None):
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
                "style_id": "helvetica_punch",
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
            "text": "Orange text test",
            "segments": [{
                "id": 0, "start": 0.0, "end": 1.5,
                "text": "Orange text test",
                "words": [
                    {"word": "Orange", "start": 0.0, "end": 0.3, "probability": 0.99},
                    {"word": "text", "start": 0.35, "end": 0.6, "probability": 0.99},
                    {"word": "test", "start": 0.65, "end": 0.9, "probability": 0.99},
                ],
            }],
            "language": "en",
        }

    def test_orange_color_no_karaoke(self):
        """Orange color without karaoke: PrimaryColour=orange, no \\k tags."""
        plan = self._make_plan(style={"color": "orange"})
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # #FF8800 => &H000088FF
            self.assertIn("&H000088FF", content)
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                self.assertNotIn("{\\k", d)
                self.assertNotIn("{\\kf", d)
        finally:
            os.unlink(path)

    def test_named_color_red_no_karaoke(self):
        """Named color 'red' without karaoke: PrimaryColour=red, no \\k tags."""
        plan = self._make_plan(style={"color": "red"})
        transcript = self._make_transcript()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # #FF0000 => &H000000FF
            self.assertIn("&H000000FF", content)
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                self.assertNotIn("{\\kf", d)
        finally:
            os.unlink(path)


# ── Emphasis font heuristic tests ─────────────────────────────────────────

class TestEmphasisFontHeuristic(unittest.TestCase):
    """Verify pause-based emphasis and fallback every 8th chunk."""

    def _make_plan(self, style=None):
        data = {
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 30},
            "main_cuts": [{"start": 0.0, "end": 30.0}],
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
        }
        if style is not None:
            data["captions"]["style"] = style
        return EditPlan.model_validate(data)

    def _make_transcript_with_pause(self):
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

    def _make_long_transcript(self, n_words=30):
        """Generate a long transcript with evenly spaced words (no pauses)."""
        words = []
        for i in range(n_words):
            t = i * 0.3
            words.append({
                "word": f"word{i}",
                "start": t,
                "end": t + 0.2,
                "probability": 0.99,
            })
        return {
            "text": " ".join(w["word"] for w in words),
            "segments": [{
                "id": 0,
                "start": 0.0,
                "end": words[-1]["end"],
                "text": " ".join(w["word"] for w in words),
                "words": words,
            }],
            "language": "en",
        }

    @patch("shutil.which", return_value=None)
    def test_pause_triggers_emphasis(self, _mock):
        """A pause >= threshold wraps last word of chunk with emphasis font."""
        plan = self._make_plan(style={
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 0.4},
        })
        transcript = self._make_transcript_with_pause()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # At least one dialogue should have emphasis font wrapping
            self.assertIn("{\\fnDejaVu Serif}", content)
        finally:
            os.unlink(path)

    @patch("shutil.which", return_value=None)
    def test_emphasis_disabled_no_fn_tags(self, _mock):
        """When emphasis is disabled, no \\fn tags appear in dialogue."""
        plan = self._make_plan(style={
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": False},
        })
        transcript = self._make_transcript_with_pause()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            for d in dialogues:
                text = d.split(",,", 1)[-1]
                self.assertNotIn("{\\fnDejaVu Serif}", text)
        finally:
            os.unlink(path)

    @patch("shutil.which", return_value=None)
    @patch("random.choices", return_value=[1])  # force 1-word chunks for determinism
    def test_fallback_every_8th_chunk(self, _mock_choices, _mock_which):
        """Every 8th chunk gets emphasis even without a pause."""
        plan = self._make_plan(style={
            "font_emphasis": "DejaVu Serif",
            "pause_emphasis": {"enabled": True, "threshold_sec": 5.0},  # very high threshold
        })
        # 30 words, 1-word chunks => 30 chunks; 8th should have emphasis
        transcript = self._make_long_transcript(n_words=30)
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        try:
            generate_ass_subtitles(transcript, plan, path)
            with open(path) as f:
                content = f.read()
            # With 30 one-word chunks and threshold=5.0 (no natural pauses),
            # chunks 8, 16, 24 should get emphasis
            self.assertIn("{\\fnDejaVu Serif}", content)
            dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
            emphasis_count = sum(1 for d in dialogues if "{\\fnDejaVu Serif}" in d)
            self.assertGreaterEqual(emphasis_count, 1, "Expected at least one emphasis chunk via 8th fallback")
        finally:
            os.unlink(path)


# ── Center position tests ─────────────────────────────────────────────────

class TestCenterPosition(unittest.TestCase):
    """Default Y position should be 960 (center screen for 1080x1920)."""

    def _make_plan(self, style=None):
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
                "style_id": "helvetica_punch",
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
            "text": "Center test",
            "segments": [{
                "id": 0, "start": 0.0, "end": 1.0,
                "text": "Center test",
                "words": [
                    {"word": "Center", "start": 0.0, "end": 0.3, "probability": 0.99},
                    {"word": "test", "start": 0.35, "end": 0.6, "probability": 0.99},
                ],
            }],
            "language": "en",
        }

    def test_default_y_1180(self):
        """Default Y should be 1180 (original helvetica_punch lower-middle position)."""
        plan = self._make_plan()
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
                self.assertIn("\\pos(540,1180)", text)
        finally:
            os.unlink(path)

    def test_custom_y_overrides_default(self):
        """Custom y=1400 overrides the default 960."""
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


# ── Named color tests ────────────────────────────────────────────────────

class TestNamedColors(unittest.TestCase):
    """Verify named colors resolve correctly."""

    def test_named_orange(self):
        self.assertEqual(_hex_to_ass_color("orange"), "&H000088FF")

    def test_named_red(self):
        self.assertEqual(_hex_to_ass_color("red"), "&H000000FF")

    def test_named_blue(self):
        self.assertEqual(_hex_to_ass_color("blue"), "&H00FF6600")

    def test_named_green(self):
        self.assertEqual(_hex_to_ass_color("green"), "&H0000CC00")

    def test_named_yellow(self):
        self.assertEqual(_hex_to_ass_color("yellow"), "&H0000CCFF")

    def test_named_white(self):
        self.assertEqual(_hex_to_ass_color("white"), "&H00FFFFFF")

    def test_named_black(self):
        self.assertEqual(_hex_to_ass_color("black"), "&H00000000")

    def test_named_case_insensitive(self):
        self.assertEqual(_hex_to_ass_color("RED"), "&H000000FF")
        self.assertEqual(_hex_to_ass_color("Orange"), "&H000088FF")

    def test_unknown_name_returns_default(self):
        self.assertEqual(_hex_to_ass_color("chartreuse"), "&H00FFFFFF")


# ── Missing font fallback tests ──────────────────────────────────────────

class TestMissingFontFallback(unittest.TestCase):
    """Verify _resolve_font falls back safely for unknown fonts."""

    @patch("shutil.which", return_value=None)
    def test_unknown_font_returns_itself(self, _mock):
        """Without fc-list, unknown font returns itself as best-effort."""
        result = _resolve_font("TotallyFakeFont")
        self.assertEqual(result, "TotallyFakeFont")

    @patch("shutil.which", return_value=None)
    def test_alias_sans_resolves(self, _mock):
        result = _resolve_font("sans")
        # Should resolve to first item in _SANS_CHAIN (Google Sans)
        self.assertEqual(result, "Google Sans")

    @patch("shutil.which", return_value=None)
    def test_alias_serif_resolves(self, _mock):
        result = _resolve_font("serif")
        self.assertEqual(result, "Playfair Display")

    @patch("shutil.which", return_value=None)
    def test_alias_mono_resolves(self, _mock):
        result = _resolve_font("mono")
        # Should resolve to first item in _MONO_CHAIN (JetBrains Mono)
        self.assertEqual(result, "JetBrains Mono")


# ── Timing / broll / overlay invariance tests ─────────────────────────────

class TestTimingInvariance(unittest.TestCase):
    """Caption style changes must NOT alter timing or broll/overlay counts."""

    def _make_plan(self, style=None, broll_inserts=None, overlay_items=None):
        data = {
            "version": "1",
            "preset_id": "snappy-creator",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 30},
            "main_cuts": [{"start": 0.0, "end": 5.0}],
            "punch_ins": [],
            "broll": {"enabled": bool(broll_inserts), "strategy": "cutaway_fullscreen",
                       "inserts": broll_inserts or []},
            "overlays": {"enabled": bool(overlay_items), "items": overlay_items or []},
            "captions": {
                "enabled": True,
                "style_id": "helvetica_punch",
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
            "text": "Hello world",
            "segments": [{
                "id": 0, "start": 0.0, "end": 1.0,
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.3, "probability": 0.99},
                    {"word": "world", "start": 0.35, "end": 0.6, "probability": 0.99},
                ],
            }],
            "language": "en",
        }

    @patch("random.choices", return_value=[2])  # deterministic chunk size
    def test_style_change_preserves_timing(self, _mock_choices):
        """Changing caption style should not alter Dialogue start/end times."""
        transcript = self._make_transcript()
        # Generate with default style
        plan1 = self._make_plan()
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path1 = f.name
        # Generate with custom style
        plan2 = self._make_plan(style={"color": "orange", "size": 80, "y": 1400})
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path2 = f.name
        try:
            generate_ass_subtitles(transcript, plan1, path1)
            generate_ass_subtitles(transcript, plan2, path2)
            with open(path1) as f:
                content1 = f.read()
            with open(path2) as f:
                content2 = f.read()
            dialogues1 = [l for l in content1.splitlines() if l.startswith("Dialogue:")]
            dialogues2 = [l for l in content2.splitlines() if l.startswith("Dialogue:")]
            # Same number of dialogue lines
            self.assertEqual(len(dialogues1), len(dialogues2))
            # Same start/end times
            for d1, d2 in zip(dialogues1, dialogues2):
                parts1 = d1.split(",")
                parts2 = d2.split(",")
                # Start time is field 1, End time is field 2
                self.assertEqual(parts1[1], parts2[1], "Start times must match")
                self.assertEqual(parts1[2], parts2[2], "End times must match")
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_broll_count_unchanged_by_style(self):
        """Broll inserts in the plan are not modified by caption style changes."""
        plan = self._make_plan(
            style={"color": "red", "size": 72},
            broll_inserts=[{"query": "nature", "start": 1.0, "end": 2.0}],
        )
        self.assertEqual(len(plan.broll.inserts), 1)
        self.assertEqual(plan.broll.inserts[0].query, "nature")

    def test_overlay_count_unchanged_by_style(self):
        """Overlay items in the plan are not modified by caption style changes."""
        plan = self._make_plan(
            style={"color": "blue", "bold": True},
            overlay_items=[{"type": "image_overlay", "start": 0.0, "end": 1.0}],
        )
        self.assertEqual(len(plan.overlays.items), 1)


if __name__ == "__main__":
    unittest.main()
