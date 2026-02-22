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
    BROLL_HEAVY_FILM_FF_FILTER,
    choose_broll_look,
    _broll_filter_for_look,
    build_broll_filtergraph_entries,
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

    def test_heavy_returns_heavy_preset(self):
        assert _broll_filter_for_look("HEAVY") == BROLL_HEAVY_FILM_FF_FILTER

    def test_unknown_defaults_to_clean(self):
        assert _broll_filter_for_look("UNKNOWN") == BROLL_LOOK_PRESET_FF_FILTER


class TestBrollFiltergraphWiring:
    """Tests that b-roll look filters are ACTUALLY wired into the final filtergraph.

    These tests call build_broll_filtergraph_entries() — the same function
    used by compile_render() — and assert on the produced filter_complex
    strings.  If anyone removes or bypasses the look filter, these FAIL.
    """

    def _two_clip_setup(self) -> list[dict]:
        """Two b-roll clips for testing."""
        return [
            {"path": "/tmp/broll_a.mp4", "start": 5.0, "end": 8.0},
            {"path": "/tmp/broll_b.mp4", "start": 15.0, "end": 18.0},
        ]

    # ---- 1. Every b-roll clip has an input label, a look filter, and an output ----
    def test_each_clip_has_raw_look_out_labels(self):
        """Each b-roll clip must produce [b{i}_raw], [b{i}_look], [b{i}_out]."""
        from apps.api.services.render_compiler import build_broll_filtergraph_entries
        clips = self._two_clip_setup()
        filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")
        joined = ";".join(filters)

        for i in range(len(clips)):
            assert f"[b{i}_raw]" in joined, f"Missing [b{i}_raw] label"
            assert f"[b{i}_look]" in joined, f"Missing [b{i}_look] label"
            assert f"[b{i}_out]" in joined, f"Missing [b{i}_out] label"

    # ---- 2. The look filter appears between _raw and _look labels ----
    def test_look_filter_between_raw_and_look_labels(self):
        """The look preset string must be sandwiched: [b{i}_raw]<filter>[b{i}_look]."""
        from apps.api.services.render_compiler import (
            build_broll_filtergraph_entries,
            BROLL_LOOK_PRESET_FF_FILTER,
            BROLL_TV_LOOK_PRESET_FF_FILTER,
        )
        clips = self._two_clip_setup()
        filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        for i in range(len(clips)):
            # Find the filter line that produces [b{i}_look]
            look_lines = [f for f in filters if f.endswith(f"[b{i}_look]")]
            assert len(look_lines) == 1, f"Expected exactly one _look producer for clip {i}"
            line = look_lines[0]
            # It must start with [b{i}_raw] and contain a known preset
            assert line.startswith(f"[b{i}_raw]"), (
                f"Look filter for clip {i} does not consume [b{i}_raw]: {line}"
            )
            # Must contain at least one preset's core filter
            has_preset = (
                BROLL_LOOK_PRESET_FF_FILTER in line
                or BROLL_TV_LOOK_PRESET_FF_FILTER in line
            )
            assert has_preset, f"Look filter for clip {i} has no known preset: {line}"

    # ---- 3. Overlay/composite step uses _look labels, NOT _raw ----
    def test_composite_uses_look_labels_not_raw(self):
        """The overlay step must reference [b{i}_look], never [b{i}_raw]."""
        from apps.api.services.render_compiler import build_broll_filtergraph_entries
        clips = self._two_clip_setup()
        filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        for i in range(len(clips)):
            # Find the overlay line that ENDS with [b{i}_out] (the producer)
            overlay_lines = [f for f in filters if "overlay=" in f and f.endswith(f"[b{i}_out]")]
            assert len(overlay_lines) == 1, f"Expected one overlay line for clip {i}"
            line = overlay_lines[0]
            assert f"[b{i}_look]" in line, (
                f"Overlay for clip {i} must use [b{i}_look]: {line}"
            )
            assert f"[b{i}_raw]overlay" not in line, (
                f"Overlay for clip {i} must NOT use raw label: {line}"
            )

    # ---- 4. No b-roll => zero b-roll filter lines ----
    def test_no_broll_produces_empty_filters(self):
        """With zero b-roll clips, no filter lines are produced."""
        from apps.api.services.render_compiler import build_broll_filtergraph_entries
        filters, last, idx = build_broll_filtergraph_entries([], 1, "[0:v]")
        assert filters == []
        assert last == "[0:v]"
        assert idx == 1

    # ---- 5. Main footage base filter is NOT in b-roll entries ----
    def test_main_footage_filter_not_in_broll(self):
        """B-roll filtergraph must NOT contain main-footage scaling/padding filters."""
        from apps.api.services.render_compiler import build_broll_filtergraph_entries
        clips = self._two_clip_setup()
        filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")
        joined = ";".join(filters)

        # Main footage uses pad= for letterboxing; b-roll uses crop= for fill
        assert "pad=1080:1920" not in joined, "Main footage pad filter leaked into b-roll"
        # Main footage uses force_original_aspect_ratio=decrease; b-roll uses increase
        assert "force_original_aspect_ratio=decrease" not in joined

    # ---- 6. The filter chain is ordered: raw → look → overlay ----
    def test_filter_chain_order(self):
        """For each clip, the three stages appear in the correct order."""
        from apps.api.services.render_compiler import build_broll_filtergraph_entries
        clips = [{"path": "/tmp/b.mp4", "start": 3.0, "end": 5.0}]
        filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        # Find indices of the three stages
        raw_idx = next(j for j, f in enumerate(filters) if "[b0_raw]" in f and "trim=" in f)
        look_idx = next(j for j, f in enumerate(filters) if f.endswith("[b0_look]"))
        overlay_idx = next(j for j, f in enumerate(filters) if "overlay=" in f and "[b0_out]" in f)

        assert raw_idx < look_idx < overlay_idx, (
            f"Wrong order: raw@{raw_idx} look@{look_idx} overlay@{overlay_idx}"
        )

    # ---- 7. Single-clip regression: overlay references [b0_look] not [b0_raw] ----
    def test_single_clip_regression(self):
        """Regression: the composite must reference _look, not _raw."""
        from apps.api.services.render_compiler import build_broll_filtergraph_entries
        clips = [{"path": "/tmp/only.mp4", "start": 2.0, "end": 4.0}]
        filters, last, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")
        joined = ";".join(filters)

        # The overlay line must have [b0_look]overlay=...
        assert "[b0_look]overlay=" in joined
        # And must NOT have [b0_raw]overlay=...
        assert "[b0_raw]overlay=" not in joined
        # Final label chains to [b0_out]
        assert last == "[b0_out]"

    # ---- 8. Snapshot: main-footage vf_base is exactly scale+pad (unchanged) ----
    def test_main_footage_vf_base_unchanged(self):
        """The main-footage base filter string is exactly the expected scale+pad."""
        # This is the string used in compile_render for fit_mode="fit"
        expected_vf = (
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
        )
        # We import compile_render source and check the string is present
        import inspect
        from apps.api.services.render_compiler import compile_render
        src = inspect.getsource(compile_render)
        assert expected_vf in src, "Main footage vf_base has been modified"
