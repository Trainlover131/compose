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
    BROLL_HEAVY_HALFTONE_FALLBACK_FF_FILTER,
    choose_broll_look,
    _broll_filter_for_look,
    _resolve_broll_look,
    _sanitize_custom_filter_chain,
    _get_heavy_halftone_filter,
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
    """Tests for choose_broll_look determinism and default 80/20 distribution."""

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_deterministic_same_key(self, _mock_heavy):
        """Same clip_key always produces the same look."""
        counts: dict[str, int] = {}
        look1 = choose_broll_look("video_abc.mp4", 0, None, 10, dict(counts))
        look2 = choose_broll_look("video_abc.mp4", 0, None, 10, dict(counts))
        assert look1 == look2

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_returns_valid_look(self, _mock_heavy):
        """Default look is always one of HEAVY or HEAVY_HALFTONE."""
        for i in range(20):
            look = choose_broll_look(f"clip_{i}", i, None, 20, {})
            assert look in ("HEAVY", "HEAVY_HALFTONE"), f"Unexpected look: {look}"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_default_80_20_distribution(self, _mock_heavy):
        """Default distribution: ~80% HEAVY, ~20% HEAVY_HALFTONE (deterministic)."""
        counts: dict[str, int] = {}
        total = 50
        prev: str | None = None
        for i in range(total):
            look = choose_broll_look(f"dist_test_{i}", i, prev, total, counts)
            counts[look] = counts.get(look, 0) + 1
            prev = look

        heavy_pct = counts.get("HEAVY", 0) / total * 100
        halftone_pct = counts.get("HEAVY_HALFTONE", 0) / total * 100

        # Allow ±10% tolerance
        assert 70 <= heavy_pct <= 90, f"HEAVY={heavy_pct:.0f}% (expected ~80%)"
        assert 10 <= halftone_pct <= 30, f"HEAVY_HALFTONE={halftone_pct:.0f}% (expected ~20%)"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_multiple_clips_get_heavy(self, _mock_heavy):
        """More than one clip must get HEAVY (not just one)."""
        counts: dict[str, int] = {}
        prev: str | None = None
        for i in range(10):
            look = choose_broll_look(f"multi_{i}", i, prev, 10, counts)
            counts[look] = counts.get(look, 0) + 1
            prev = look
        assert counts.get("HEAVY", 0) > 1, "Expected multiple HEAVY clips"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_user_specified_clean_all_clean(self, _mock_heavy):
        """When user specifies CLEAN, 100% of clips use CLEAN."""
        for i in range(20):
            look = choose_broll_look(f"user_clean_{i}", i, None, 20, {}, user_look="CLEAN")
            assert look == "CLEAN", f"clip {i}: expected CLEAN, got {look}"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_user_specified_tv_all_tv(self, _mock_heavy):
        """When user specifies TV, 100% of clips use TV."""
        for i in range(10):
            look = choose_broll_look(f"user_tv_{i}", i, None, 10, {}, user_look="TV")
            assert look == "TV"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_user_alias_newsprint_resolves_to_heavy_halftone(self, _mock_heavy):
        """User alias 'newsprint' should resolve to HEAVY_HALFTONE."""
        look = choose_broll_look("alias_test", 0, None, 5, {}, user_look="newsprint")
        assert look == "HEAVY_HALFTONE"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_user_unknown_look_returns_custom(self, _mock_heavy):
        """Unknown user look string returns CUSTOM."""
        look = choose_broll_look("custom_test", 0, None, 5, {}, user_look="dreamy blur glow")
        assert look == "CUSTOM"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=False)
    def test_heavy_falls_back_to_clean_when_filters_missing(self, _mock_heavy):
        """When heavy filters unavailable, HEAVY falls back to CLEAN."""
        # Force a key that would normally be HEAVY (bucket < 80)
        # Since 80% of keys hash to HEAVY, just try several
        found_clean = False
        for i in range(20):
            look = choose_broll_look(f"fallback_{i}", i, None, 20, {})
            if look == "CLEAN":
                found_clean = True
                break
        assert found_clean, "Expected at least one CLEAN fallback when heavy filters missing"


class TestBrollFilterForLook:
    """Tests for _broll_filter_for_look."""

    def test_clean_returns_base_preset(self):
        assert _broll_filter_for_look("CLEAN") == BROLL_LOOK_PRESET_FF_FILTER

    def test_tv_returns_tv_preset(self):
        assert _broll_filter_for_look("TV") == BROLL_TV_LOOK_PRESET_FF_FILTER

    def test_heavy_returns_heavy_preset(self):
        assert _broll_filter_for_look("HEAVY") == BROLL_HEAVY_FILM_FF_FILTER

    @patch("apps.api.services.render_compiler._probe_frei0r_halftone", return_value=None)
    def test_heavy_halftone_returns_fallback_when_no_frei0r(self, _mock):
        """HEAVY_HALFTONE returns FFmpeg-only fallback when frei0r unavailable."""
        result = _broll_filter_for_look("HEAVY_HALFTONE")
        assert result == BROLL_HEAVY_HALFTONE_FALLBACK_FF_FILTER

    @patch("apps.api.services.render_compiler._probe_frei0r_halftone", return_value="halftone")
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=True)
    def test_heavy_halftone_returns_frei0r_when_available(self, _mock_frei0r, _mock_ht):
        """HEAVY_HALFTONE returns frei0r chain when halftone filter is available."""
        result = _broll_filter_for_look("HEAVY_HALFTONE")
        assert "frei0r=" in result
        assert "halftone" in result

    def test_unknown_defaults_to_clean(self):
        assert _broll_filter_for_look("UNKNOWN") == BROLL_LOOK_PRESET_FF_FILTER


class TestBrollLookAliases:
    """Tests for _resolve_broll_look alias resolution."""

    def test_heavy_film_alias(self):
        assert _resolve_broll_look("HEAVY_FILM") == "HEAVY"

    def test_vhs_alias(self):
        assert _resolve_broll_look("VHS") == "HEAVY"

    def test_newsprint_alias(self):
        assert _resolve_broll_look("NEWSPRINT") == "HEAVY_HALFTONE"

    def test_comic_print_alias(self):
        assert _resolve_broll_look("COMIC_PRINT") == "HEAVY_HALFTONE"

    def test_halftone_heavy_alias(self):
        assert _resolve_broll_look("HALFTONE_HEAVY") == "HEAVY_HALFTONE"

    def test_canonical_heavy(self):
        assert _resolve_broll_look("HEAVY") == "HEAVY"

    def test_canonical_clean(self):
        assert _resolve_broll_look("CLEAN") == "CLEAN"

    def test_unknown_returns_custom(self):
        assert _resolve_broll_look("dreamy blur glow") == "CUSTOM"

    def test_case_insensitive(self):
        assert _resolve_broll_look("newsprint") == "HEAVY_HALFTONE"
        assert _resolve_broll_look("Vhs") == "HEAVY"


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

    # ---- 2. The look filter appears between _raw and _look labels (CLEAN mode) ----
    def test_look_filter_between_raw_and_look_labels(self):
        """With CLEAN look, preset string is sandwiched: [b{i}_raw]<filter>[b{i}_look]."""
        from apps.api.services.render_compiler import (
            build_broll_filtergraph_entries,
            BROLL_LOOK_PRESET_FF_FILTER,
        )
        clips = self._two_clip_setup()
        # Force CLEAN to test linear filter wiring
        filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]", user_look="CLEAN")

        for i in range(len(clips)):
            # Find the filter line that produces [b{i}_look]
            look_lines = [f for f in filters if f.endswith(f"[b{i}_look]")]
            assert len(look_lines) == 1, f"Expected exactly one _look producer for clip {i}"
            line = look_lines[0]
            # It must start with [b{i}_raw] and contain CLEAN preset
            assert line.startswith(f"[b{i}_raw]"), (
                f"Look filter for clip {i} does not consume [b{i}_raw]: {line}"
            )
            assert BROLL_LOOK_PRESET_FF_FILTER in line, (
                f"Look filter for clip {i} has no CLEAN preset: {line}"
            )

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


class TestHeavyFilmPreset:
    """Tests for the HEAVY film + motion b-roll preset."""

    def test_heavy_preset_contains_all_components(self):
        """HEAVY preset string must include all 7 required effect components."""
        # 1) VHS softness: boxblur + unsharp
        assert "boxblur=" in BROLL_HEAVY_FILM_FF_FILTER
        assert "unsharp=" in BROLL_HEAVY_FILM_FF_FILTER
        # 2) Grain: noise filter
        assert "noise=" in BROLL_HEAVY_FILM_FF_FILTER
        assert "c0s=" in BROLL_HEAVY_FILM_FF_FILTER
        # 3) Flicker: eq with brightness modulated by sin
        assert "sin(" in BROLL_HEAVY_FILM_FF_FILTER
        assert "eval=frame" in BROLL_HEAVY_FILM_FF_FILTER
        # 4) Scanlines: drawgrid
        assert "drawgrid=" in BROLL_HEAVY_FILM_FF_FILTER
        # 5) Chroma bleed: rgbashift
        assert "rgbashift=" in BROLL_HEAVY_FILM_FF_FILTER
        # 6) Halation: tested separately (split/blur/blend in filtergraph)
        # 7) Zoom/pan: tested separately (zoompan in filtergraph)

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=False)
    def test_heavy_filtergraph_has_halation_stages(self, _mock_frei0r, _mock_heavy):
        """HEAVY clips must produce split/blur/blend stages for halation."""
        clips = [{"path": "/tmp/heavy_test.mp4", "start": 4.0, "end": 7.0}]

        with patch(
            "apps.api.services.render_compiler.choose_broll_look", return_value="HEAVY"
        ):
            filters, last, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        joined = ";".join(filters)

        # Halation stages: split, gblur, blend
        assert "split[" in joined, "Missing split for halation"
        assert "gblur=" in joined, "Missing gblur for halation"
        assert "blend=" in joined, "Missing blend for halation"
        assert "all_mode=screen" in joined, "Blend must use screen mode"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=False)
    def test_heavy_filtergraph_has_zoompan_motion(self, _mock_frei0r, _mock_heavy):
        """HEAVY clips must include zoompan for micro push-in motion."""
        clips = [{"path": "/tmp/heavy_motion.mp4", "start": 2.0, "end": 5.0}]

        with patch(
            "apps.api.services.render_compiler.choose_broll_look", return_value="HEAVY"
        ):
            filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        joined = ";".join(filters)

        assert "zoompan=" in joined, "Missing zoompan for micro motion"
        assert "s=1080x1920" in joined, "Zoompan must preserve resolution"
        assert "d=1" in joined, "Zoompan d=1 required to preserve frame count"

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=False)
    def test_heavy_wiring_still_uses_look_label(self, _mock_frei0r, _mock_heavy):
        """HEAVY clips must still produce [b{i}_look] and use it in overlay."""
        clips = [{"path": "/tmp/heavy_wire.mp4", "start": 3.0, "end": 6.0}]

        with patch(
            "apps.api.services.render_compiler.choose_broll_look", return_value="HEAVY"
        ):
            filters, last, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        joined = ";".join(filters)

        # Must still have the standard labels
        assert "[b0_raw]" in joined
        assert "[b0_look]" in joined
        assert "[b0_out]" in joined
        # Overlay must use [b0_look], not any intermediate label
        overlay_lines = [f for f in filters if "overlay=" in f and f.endswith("[b0_out]")]
        assert len(overlay_lines) == 1
        assert "[b0_look]" in overlay_lines[0]

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=False)
    def test_heavy_base_filter_present(self, _mock_frei0r, _mock_heavy):
        """HEAVY clips must apply the base BROLL_HEAVY_FILM_FF_FILTER."""
        clips = [{"path": "/tmp/heavy_base.mp4", "start": 1.0, "end": 3.0}]

        with patch(
            "apps.api.services.render_compiler.choose_broll_look", return_value="HEAVY"
        ):
            filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        joined = ";".join(filters)

        # The base filter must appear in the chain
        assert BROLL_HEAVY_FILM_FF_FILTER in joined, (
            "HEAVY base filter missing from filtergraph"
        )

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=False)
    def test_heavy_does_not_affect_overlay_images(self, _mock_frei0r, _mock_heavy):
        """HEAVY look filter must NOT appear in overlay image filter lines."""
        clips = [{"path": "/tmp/heavy_only.mp4", "start": 5.0, "end": 8.0}]

        with patch(
            "apps.api.services.render_compiler.choose_broll_look", return_value="HEAVY"
        ):
            filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        joined = ";".join(filters)
        # No overlay image labels (ov0, vo0 etc.) should appear
        assert "ov0" not in joined
        assert "vo0" not in joined
        # No format=rgba (overlay image prep) should appear
        assert "format=rgba" not in joined

    def test_heavy_preset_vhs_softness_values(self):
        """VHS softness must have specific boxblur + unsharp parameters."""
        assert "boxblur=2:1" in BROLL_HEAVY_FILM_FF_FILTER
        assert "unsharp=5:5:1.2" in BROLL_HEAVY_FILM_FF_FILTER

    def test_heavy_preset_grain_strength(self):
        """Grain noise must be heavier than TV preset (c0s >= 12)."""
        import re
        heavy_match = re.search(r"c0s=(\d+)", BROLL_HEAVY_FILM_FF_FILTER)
        tv_match = re.search(r"c0s=(\d+)", BROLL_TV_LOOK_PRESET_FF_FILTER)
        assert heavy_match and tv_match
        assert int(heavy_match.group(1)) > int(tv_match.group(1))

    def test_heavy_preset_chroma_shift_bounded(self):
        """Chroma shift must be modest (abs(rh) <= 5, abs(bh) <= 5)."""
        import re
        rh = re.search(r"rh=(-?\d+)", BROLL_HEAVY_FILM_FF_FILTER)
        bh = re.search(r"bh=(-?\d+)", BROLL_HEAVY_FILM_FF_FILTER)
        assert rh and bh
        assert abs(int(rh.group(1))) <= 5
        assert abs(int(bh.group(1))) <= 5


# ====================================================================
# Part C — HEAVY_HALFTONE preset
# ====================================================================

class TestHeavyHalftonePreset:
    """Tests for the HEAVY_HALFTONE (comic print / newsprint) preset."""

    def test_fallback_filter_is_non_empty(self):
        """HEAVY_HALFTONE FFmpeg-only fallback must be a non-empty filter chain."""
        assert len(BROLL_HEAVY_HALFTONE_FALLBACK_FF_FILTER) > 0

    def test_fallback_contains_core_components(self):
        """Fallback must include desaturation, contrast, sharpening, grain."""
        f = BROLL_HEAVY_HALFTONE_FALLBACK_FF_FILTER
        assert "eq=" in f, "Missing eq filter (contrast/brightness)"
        assert "hue=s=0" in f, "Missing grayscale conversion"
        assert "unsharp=" in f, "Missing edge sharpening"
        assert "noise=" in f, "Missing grain/texture"
        assert "vignette=" in f, "Missing vignette"

    def test_fallback_has_no_frei0r(self):
        """FFmpeg-only fallback must NOT reference frei0r."""
        assert "frei0r" not in BROLL_HEAVY_HALFTONE_FALLBACK_FF_FILTER

    @patch("apps.api.services.render_compiler._probe_frei0r_halftone", return_value="halftone")
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=True)
    def test_frei0r_chain_includes_frei0r_token(self, _mock_frei0r, _mock_ht):
        """When frei0r probe succeeds, the chain includes frei0r filter."""
        result = _get_heavy_halftone_filter()
        assert "frei0r=" in result
        assert "filter_name=halftone" in result

    @patch("apps.api.services.render_compiler._probe_frei0r_halftone", return_value=None)
    def test_no_frei0r_returns_native_only(self, _mock_ht):
        """When frei0r unavailable, returns only native FFmpeg filters."""
        result = _get_heavy_halftone_filter()
        assert "frei0r" not in result
        assert result == BROLL_HEAVY_HALFTONE_FALLBACK_FF_FILTER

    @patch("apps.api.services.render_compiler._probe_frei0r_halftone", return_value=None)
    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_heavy_halftone_wiring_proof(self, _mock_heavy, _mock_ht):
        """HEAVY_HALFTONE clips are properly wired: [b{i}_raw] -> ... -> [b{i}_look]."""
        clips = [
            {"path": "/tmp/ht_a.mp4", "start": 2.0, "end": 5.0},
            {"path": "/tmp/ht_b.mp4", "start": 8.0, "end": 11.0},
        ]

        with patch(
            "apps.api.services.render_compiler.choose_broll_look", return_value="HEAVY_HALFTONE"
        ):
            filters, _, _ = build_broll_filtergraph_entries(clips, 1, "[0:v]")

        joined = ";".join(filters)

        for i in range(len(clips)):
            assert f"[b{i}_raw]" in joined
            assert f"[b{i}_look]" in joined
            assert f"[b{i}_out]" in joined
            # Look filter line: [b{i}_raw]<filter>[b{i}_look]
            look_lines = [f for f in filters if f.endswith(f"[b{i}_look]")]
            assert len(look_lines) == 1
            line = look_lines[0]
            assert line.startswith(f"[b{i}_raw]")
            # Must contain fallback filter (since frei0r is mocked out)
            assert "hue=s=0" in line or "frei0r=" in line
            # Overlay uses [b{i}_look]
            overlay_lines = [f for f in filters if "overlay=" in f and f.endswith(f"[b{i}_out]")]
            assert len(overlay_lines) == 1
            assert f"[b{i}_look]" in overlay_lines[0]

    @patch("apps.api.services.render_compiler._probe_frei0r_halftone", return_value="pixeliz0r")
    @patch("apps.api.services.render_compiler._probe_frei0r", return_value=True)
    def test_frei0r_selects_from_candidate_list(self, _mock_frei0r, _mock_ht):
        """Probe selects from candidate allowlist (pixeliz0r is a valid candidate)."""
        result = _get_heavy_halftone_filter()
        assert "frei0r=filter_name=pixeliz0r" in result


# ====================================================================
# Part D — Custom b-roll looks
# ====================================================================

class TestSanitizeCustomFilterChain:
    """Tests for _sanitize_custom_filter_chain."""

    def test_strips_labels(self):
        """Input/output labels like [0:v] are removed."""
        raw = "[0:v]eq=contrast=1.2[out]"
        result = _sanitize_custom_filter_chain(raw)
        assert "[" not in result
        assert "]" not in result
        assert "eq=contrast=1.2" in result

    def test_strips_semicolons(self):
        """Semicolons are removed to prevent filtergraph termination."""
        raw = "eq=contrast=1.2;boxblur=2:1"
        result = _sanitize_custom_filter_chain(raw)
        assert ";" not in result

    def test_blocks_movie_filter(self):
        """movie= filter is blocked (external file access)."""
        raw = "movie=/etc/passwd,eq=contrast=1.2"
        result = _sanitize_custom_filter_chain(raw)
        assert result == BROLL_LOOK_PRESET_FF_FILTER  # falls back to CLEAN

    def test_blocks_amovie_filter(self):
        """amovie= filter is blocked."""
        raw = "amovie=/tmp/audio.wav"
        result = _sanitize_custom_filter_chain(raw)
        assert result == BROLL_LOOK_PRESET_FF_FILTER

    def test_blocks_sendcmd(self):
        """sendcmd is blocked (command injection)."""
        raw = "sendcmd=0 eq brightness 1"
        result = _sanitize_custom_filter_chain(raw)
        assert result == BROLL_LOOK_PRESET_FF_FILTER

    def test_empty_input_falls_back(self):
        """Empty input falls back to CLEAN preset."""
        assert _sanitize_custom_filter_chain("") == BROLL_LOOK_PRESET_FF_FILTER
        assert _sanitize_custom_filter_chain("  ") == BROLL_LOOK_PRESET_FF_FILTER

    def test_valid_chain_passes_through(self):
        """A valid filter chain passes through unchanged."""
        raw = "eq=contrast=1.2,boxblur=2:1"
        result = _sanitize_custom_filter_chain(raw)
        assert result == raw


class TestCustomBrollLook:
    """Tests for arbitrary user-requested b-roll looks (Part D)."""

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    @patch("apps.api.services.render_compiler._generate_custom_broll_look",
           return_value="eq=contrast=1.2,boxblur=2:1")
    def test_custom_look_triggers_custom_path(self, _mock_gen, _mock_heavy):
        """Unknown look string triggers CUSTOM code path."""
        clips = [{"path": "/tmp/custom.mp4", "start": 1.0, "end": 3.0}]
        filters, _, _ = build_broll_filtergraph_entries(
            clips, 1, "[0:v]", user_look="dreamy blur glow",
        )
        joined = ";".join(filters)

        # The custom filter string must appear in the filtergraph
        assert "eq=contrast=1.2,boxblur=2:1" in joined

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    @patch("apps.api.services.render_compiler._generate_custom_broll_look",
           return_value="eq=contrast=1.2,boxblur=2:1")
    def test_custom_look_wiring_proof(self, _mock_gen, _mock_heavy):
        """Custom look clips are properly wired with standard labels."""
        clips = [{"path": "/tmp/custom_wire.mp4", "start": 2.0, "end": 5.0}]
        filters, _, _ = build_broll_filtergraph_entries(
            clips, 1, "[0:v]", user_look="vhs + scanlines + chroma bleed",
        )
        joined = ";".join(filters)

        # Standard wiring labels must be present
        assert "[b0_raw]" in joined
        assert "[b0_look]" in joined
        assert "[b0_out]" in joined
        # Look filter line connects raw -> look
        look_lines = [f for f in filters if f.endswith("[b0_look]")]
        assert len(look_lines) == 1
        assert look_lines[0].startswith("[b0_raw]")
        # Overlay uses [b0_look]
        overlay_lines = [f for f in filters if "overlay=" in f and f.endswith("[b0_out]")]
        assert len(overlay_lines) == 1
        assert "[b0_look]" in overlay_lines[0]

    @patch("apps.api.services.render_compiler._probe_heavy_filters", return_value=True)
    def test_known_preset_via_user_look_not_custom(self, _mock_heavy):
        """User look matching a known preset uses the preset, not custom path."""
        clips = [{"path": "/tmp/preset.mp4", "start": 1.0, "end": 3.0}]
        filters, _, _ = build_broll_filtergraph_entries(
            clips, 1, "[0:v]", user_look="CLEAN",
        )
        joined = ";".join(filters)

        # Should have CLEAN preset filter, not any custom generation
        assert BROLL_LOOK_PRESET_FF_FILTER in joined
