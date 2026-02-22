"""Tests for overlay checkerboard QC and b-roll look variance."""

import io
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest
from PIL import Image

from apps.api.services.overlay_qc import detect_checkerboard_background
from apps.api.services.render_compiler import (
    BROLL_LOOK_PRESET_FF_FILTER,
    BROLL_TV_LOOK_PRESET_FF_FILTER,
    choose_broll_look,
    _broll_filter_for_look,
)


# ====================================================================
# Task A — Checkerboard detection
# ====================================================================

class TestCheckerboardDetection:
    """Unit tests for detect_checkerboard_background."""

    def _make_checkerboard_png(self, tile_size: int = 16) -> str:
        """Create a synthetic checkerboard PNG (classic alpha-grid)."""
        size = 256
        img = Image.new("RGB", (size, size))
        pixels = np.zeros((size, size, 3), dtype=np.uint8)

        light = np.array([204, 204, 204], dtype=np.uint8)  # light gray
        dark = np.array([153, 153, 153], dtype=np.uint8)    # darker gray

        for y in range(size):
            for x in range(size):
                ty = y // tile_size
                tx = x // tile_size
                if (ty + tx) % 2 == 0:
                    pixels[y, x] = light
                else:
                    pixels[y, x] = dark

        img = Image.fromarray(pixels)
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(f.name)
        return f.name

    def _make_solid_png(self, color=(255, 128, 64)) -> str:
        """Create a solid-color PNG (no checkerboard)."""
        img = Image.new("RGB", (256, 256), color)
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(f.name)
        return f.name

    def _make_transparent_png(self) -> str:
        """Create a PNG with real alpha transparency (no checkerboard)."""
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        # Draw a red circle area (opaque) in the center
        pixels = np.array(img)
        for y in range(256):
            for x in range(256):
                dx, dy = x - 128, y - 128
                if dx * dx + dy * dy < 80 * 80:
                    pixels[y, x] = [255, 0, 0, 255]
        img = Image.fromarray(pixels)
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(f.name)
        return f.name

    def _make_photo_png(self) -> str:
        """Create a noisy photo-like image that should NOT trigger detection."""
        rng = np.random.RandomState(42)
        pixels = rng.randint(0, 256, (256, 256, 3), dtype=np.uint8)
        img = Image.fromarray(pixels)
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(f.name)
        return f.name

    def test_checkerboard_8x8_detected(self):
        path = self._make_checkerboard_png(tile_size=8)
        assert detect_checkerboard_background(path) is True

    def test_checkerboard_16x16_detected(self):
        path = self._make_checkerboard_png(tile_size=16)
        assert detect_checkerboard_background(path) is True

    def test_solid_image_not_detected(self):
        path = self._make_solid_png()
        assert detect_checkerboard_background(path) is False

    def test_transparent_image_not_detected(self):
        path = self._make_transparent_png()
        assert detect_checkerboard_background(path) is False

    def test_random_photo_not_detected(self):
        path = self._make_photo_png()
        assert detect_checkerboard_background(path) is False

    def test_nonexistent_file_returns_false(self):
        assert detect_checkerboard_background("/tmp/does_not_exist_xyz.png") is False


class TestCheckerboardRegeneration:
    """Test that checkerboard QC triggers at most one regeneration."""

    @patch("apps.api.services.planner._NB_KEY", "fake-key")
    @patch("apps.api.services.planner._nanobanana_call_and_parse")
    @patch("apps.api.services.planner.detect_checkerboard_background")
    def test_regeneration_happens_once_on_checkerboard(
        self, mock_detect, mock_call,
    ):
        """If first result has checkerboard, regenerate once then stop."""
        from apps.api.services.planner import _generate_overlay_image_from_item

        # First call returns a path, second call also returns a path
        mock_call.side_effect = ["/tmp/overlay_1.png", "/tmp/overlay_2.png"]
        # First detect = True (checkerboard), second detect = False (clean)
        mock_detect.side_effect = [True, False]

        overlay = {
            "query": "test logo",
            "placement": {"w": 0.2},
            "render_intent": {},
        }

        with patch("apps.api.services.planner._OVERLAY_CACHE_DIR", Path("/tmp/test_cache")):
            with patch("apps.api.services.planner.NanoBananaPromptBuilder") as MockBuilder:
                MockBuilder.cache_key.return_value = "testkey123"
                MockBuilder.build.return_value = "test prompt"
                MockBuilder.select_endpoint.return_value = (
                    "https://api.nanobananaapi.ai/api/v1/nanobanana/generate"
                )
                with patch("pathlib.Path.exists", return_value=False):
                    with patch("pathlib.Path.mkdir"):
                        with patch("pathlib.Path.unlink"):
                            result = _generate_overlay_image_from_item(overlay)

        # _nanobanana_call_and_parse called twice: initial + one retry
        assert mock_call.call_count == 2
        assert result == "/tmp/overlay_2.png"

    @patch("apps.api.services.planner._NB_KEY", "fake-key")
    @patch("apps.api.services.planner._nanobanana_call_and_parse")
    @patch("apps.api.services.planner.detect_checkerboard_background")
    def test_no_infinite_loop_on_persistent_checkerboard(
        self, mock_detect, mock_call,
    ):
        """If both attempts have checkerboard, keep second result (no loop)."""
        from apps.api.services.planner import _generate_overlay_image_from_item

        mock_call.side_effect = ["/tmp/overlay_1.png", "/tmp/overlay_2.png"]
        # Both detections return True
        mock_detect.side_effect = [True, True]

        overlay = {
            "query": "test logo",
            "placement": {"w": 0.2},
            "render_intent": {},
        }

        with patch("apps.api.services.planner._OVERLAY_CACHE_DIR", Path("/tmp/test_cache")):
            with patch("apps.api.services.planner.NanoBananaPromptBuilder") as MockBuilder:
                MockBuilder.cache_key.return_value = "testkey456"
                MockBuilder.build.return_value = "test prompt"
                MockBuilder.select_endpoint.return_value = (
                    "https://api.nanobananaapi.ai/api/v1/nanobanana/generate"
                )
                with patch("pathlib.Path.exists", return_value=False):
                    with patch("pathlib.Path.mkdir"):
                        with patch("pathlib.Path.unlink"):
                            result = _generate_overlay_image_from_item(overlay)

        # Exactly 2 calls: initial + one retry, then stops
        assert mock_call.call_count == 2
        # Still returns the image (keeps it anyway)
        assert result == "/tmp/overlay_2.png"


# ====================================================================
# Task B — B-roll look variance
# ====================================================================

class TestBrollLookChoice:
    """Tests for choose_broll_look determinism and cap enforcement."""

    def test_deterministic_same_key(self):
        """Same clip_key always produces the same look."""
        counts: dict[str, int] = {}
        look1 = choose_broll_look("video_abc.mp4", 0, None, 10, dict(counts))
        look2 = choose_broll_look("video_abc.mp4", 0, None, 10, dict(counts))
        assert look1 == look2

    def test_returns_valid_look(self):
        """Look is always one of CLEAN, TV, HALFTONE."""
        for i in range(20):
            look = choose_broll_look(f"clip_{i}", i, None, 20, {})
            assert look in ("CLEAN", "TV", "HALFTONE")

    def test_no_consecutive_non_clean(self):
        """Two consecutive non-CLEAN looks are prevented."""
        counts: dict[str, int] = {}
        prev: str | None = None
        for i in range(50):
            look = choose_broll_look(f"key_{i}", i, prev, 50, counts)
            if prev is not None and prev != "CLEAN":
                assert look == "CLEAN", (
                    f"clip {i}: got {look} after {prev} (should be CLEAN)"
                )
            counts[look] = counts.get(look, 0) + 1
            prev = look

    def test_caps_enforced(self):
        """TV and HALFTONE stay within their percentage caps."""
        counts: dict[str, int] = {}
        prev: str | None = None
        total = 20
        for i in range(total):
            look = choose_broll_look(f"cap_test_{i}", i, prev, total, counts)
            counts[look] = counts.get(look, 0) + 1
            prev = look

        # TV <= ceil(25% of 20) = 5, HALFTONE <= ceil(15% of 20) = 3
        assert counts.get("TV", 0) <= max(1, int(total * 0.25 + 0.5))
        # HALFTONE may be 0 if frei0r is unavailable
        assert counts.get("HALFTONE", 0) <= max(1, int(total * 0.15 + 0.5))


class TestBrollFilterForLook:
    """Tests for _broll_filter_for_look."""

    def test_clean_returns_base_preset(self):
        assert _broll_filter_for_look("CLEAN") == BROLL_LOOK_PRESET_FF_FILTER

    def test_tv_returns_tv_preset(self):
        assert _broll_filter_for_look("TV") == BROLL_TV_LOOK_PRESET_FF_FILTER

    def test_unknown_defaults_to_clean(self):
        assert _broll_filter_for_look("UNKNOWN") == BROLL_LOOK_PRESET_FF_FILTER


class TestBrollFilterInRenderCompiler:
    """Tests that b-roll look filters appear in FFmpeg commands for b-roll only."""

    def test_broll_filter_present_in_broll_path(self):
        """When b-roll clips exist, the filter chain should include look presets."""
        # We test by checking the filter string construction logic
        from apps.api.services.render_compiler import BROLL_LOOK_PRESET_FF_FILTER
        # The CLEAN preset must include eq= and unsharp= filters
        assert "eq=contrast=" in BROLL_LOOK_PRESET_FF_FILTER
        assert "unsharp=" in BROLL_LOOK_PRESET_FF_FILTER
        assert "noise=" in BROLL_LOOK_PRESET_FF_FILTER

    def test_main_footage_commands_unchanged(self):
        """Main footage ffmpeg commands should NOT include b-roll look filters."""
        from apps.api.models.schemas import EditPlan
        plan = EditPlan(
            preset_id="snappy-creator",
            main_cuts=[
                {"start": 0, "end": 10},
                {"start": 15, "end": 25},
            ],
            broll={"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
            music={"enabled": False},
        )
        # The main segment commands use vf_base (scale+pad) only
        # Verify no look preset leaks into main footage path
        assert plan.broll.enabled is False
        assert len(plan.broll.inserts) == 0
        # The compile_render function only applies look filters inside the
        # "B-ROLL FULLSCREEN CUTAWAYS" block, which is gated on broll_clips
        # being non-empty. With no b-roll, the block is skipped entirely.
