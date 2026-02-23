"""Unit tests for filter_complex construction in render_compiler.

Tests that filter_complex strings are free of stray quotes, newlines,
and other characters that would cause FFmpeg to error.  No FFmpeg
execution is required.
"""

import pytest

from apps.api.services.render_compiler import (
    _sanitize_fc,
    build_broll_filtergraph_entries,
    compile_motion_for_broll,
    compile_motion_for_overlay,
)


# ---------------------------------------------------------------------------
# _sanitize_fc
# ---------------------------------------------------------------------------

class TestSanitizeFc:
    def test_strips_trailing_single_quote(self):
        fc = "[vo1]ass=/tmp/captions.ass[vcap]'"
        assert _sanitize_fc(fc) == "[vo1]ass=/tmp/captions.ass[vcap]"

    def test_strips_wrapping_single_quotes(self):
        fc = "'[0:v]setpts=PTS-STARTPTS[base]'"
        assert _sanitize_fc(fc) == "[0:v]setpts=PTS-STARTPTS[base]"

    def test_strips_wrapping_double_quotes(self):
        fc = '"[0:v]setpts=PTS-STARTPTS[base]"'
        assert _sanitize_fc(fc) == "[0:v]setpts=PTS-STARTPTS[base]"

    def test_strips_trailing_unmatched_double_quote(self):
        fc = '[vo1]ass=/tmp/captions.ass[vcap]"'
        assert _sanitize_fc(fc) == "[vo1]ass=/tmp/captions.ass[vcap]"

    def test_strips_whitespace(self):
        fc = "  [0:v]null[out]  "
        assert _sanitize_fc(fc) == "[0:v]null[out]"

    def test_noop_on_clean_string(self):
        fc = "[0:v]setpts=PTS-STARTPTS[base];[base]ass=/tmp/c.ass[vcap]"
        assert _sanitize_fc(fc) == fc

    def test_preserves_internal_escaped_commas(self):
        fc = r"[0:v]crop=w=iw/(1+0.020*min(max((t-1.000)/2.000000\,0)\,1)):h=ih[out]"
        assert _sanitize_fc(fc) == fc

    def test_preserves_internal_single_quotes_in_balanced(self):
        """If fc starts and ends with ' it's treated as wrapping quotes."""
        fc = "'foo'"
        assert _sanitize_fc(fc) == "foo"


# ---------------------------------------------------------------------------
# Full filter_complex construction (motion vs no-motion)
# ---------------------------------------------------------------------------

def _build_full_fc(
    broll_clips: list[dict],
    overlay_items: list[dict],
    ass_path: str,
    motion_enabled: bool,
) -> str:
    """Simulate the filter_complex construction from compile_render.

    This mirrors the exact logic in compile_render's layer pass, constructing
    the same filter strings.  Used for testing without running FFmpeg.
    """
    filters = []

    # Base normalization (both motion and retry paths should do this)
    filters.append("[0:v]setpts=PTS-STARTPTS[base]")
    last_label = "[base]"
    input_index = 1

    # B-roll
    broll_filters, last_label, input_index = build_broll_filtergraph_entries(
        broll_clips, input_index, last_label, motion_enabled=motion_enabled,
    )
    filters.extend(broll_filters)

    # Overlays
    for j, oi in enumerate(overlay_items):
        ov_idx = input_index
        input_index += 1
        out = f"vo{j}"
        w_px = max(1, int(1080 * oi["w"]))
        x_px = int(1080 * oi["x"])
        y_px = int(1920 * oi["y"])
        prep = f"ov{j}"

        prep_tail, x_expr, y_expr = compile_motion_for_overlay(
            oi=oi,
            motion_enabled=motion_enabled,
            start=float(oi["start"]),
            end=float(oi["end"]),
            x0=x_px,
            y0=y_px,
            w_px=w_px,
        )

        filters.append(
            f"[{ov_idx}:v]scale={w_px}:-1,format=rgba,"
            f"setpts=PTS-STARTPTS{prep_tail}[{prep}]"
        )
        filters.append(
            f"{last_label}[{prep}]overlay="
            f"x={x_expr}:y={y_expr}:"
            f"enable=between(t\\,{oi['start']:.3f}\\,{oi['end']:.3f})[{out}]"
        )
        last_label = f"[{out}]"

    # Captions
    if ass_path:
        cap_out = "vcap"
        filters.append(f"{last_label}ass={ass_path}[{cap_out}]")
        last_label = f"[{cap_out}]"

    fc = ";".join(filters) if filters else "null"
    return _sanitize_fc(fc)


def _assert_fc_clean(fc: str) -> None:
    """Assert filter_complex string has no stray quotes or newlines."""
    assert not fc.endswith("'"), f"fc ends with single quote: {repr(fc[-80:])}"
    assert not fc.endswith('"'), f"fc ends with double quote: {repr(fc[-80:])}"
    assert not fc.startswith("'"), f"fc starts with single quote: {repr(fc[:80])}"
    assert not fc.startswith('"'), f"fc starts with double quote: {repr(fc[:80])}"
    assert "\n" not in fc, f"fc contains newline: {repr(fc[:200])}"
    assert "\r" not in fc, f"fc contains carriage return: {repr(fc[:200])}"


# Sample test data
_BROLL_CLIPS = [
    {"path": "/tmp/broll_0.mp4", "start": 3.0, "end": 6.0},
    {"path": "/tmp/broll_1.mp4", "start": 8.0, "end": 11.0},
]
_OVERLAY_ITEMS = [
    {"path": "/tmp/ov0.png", "start": 0.5, "end": 3.0,
     "x": 0.82, "y": 0.12, "w": 0.18, "fade_in": 0.12, "fade_out": 0.12},
    {"path": "/tmp/ov1.png", "start": 5.0, "end": 7.5,
     "x": 0.05, "y": 0.70, "w": 0.25, "fade_in": 0.12, "fade_out": 0.12},
]
_ASS_PATH = "/tmp/compose_render_test/captions.ass"


class TestFilterComplexConstruction:
    def test_motion_enabled_no_trailing_quotes(self):
        fc = _build_full_fc(_BROLL_CLIPS, _OVERLAY_ITEMS, _ASS_PATH, motion_enabled=True)
        _assert_fc_clean(fc)

    def test_motion_disabled_no_trailing_quotes(self):
        fc = _build_full_fc(_BROLL_CLIPS, _OVERLAY_ITEMS, _ASS_PATH, motion_enabled=False)
        _assert_fc_clean(fc)

    def test_captions_only_motion_enabled(self):
        fc = _build_full_fc([], [], _ASS_PATH, motion_enabled=True)
        _assert_fc_clean(fc)
        assert "ass=" in fc

    def test_captions_only_motion_disabled(self):
        fc = _build_full_fc([], [], _ASS_PATH, motion_enabled=False)
        _assert_fc_clean(fc)
        assert "ass=" in fc

    def test_overlays_and_captions_no_broll(self):
        fc = _build_full_fc([], _OVERLAY_ITEMS, _ASS_PATH, motion_enabled=True)
        _assert_fc_clean(fc)
        assert "[vcap]" in fc

    def test_broll_only_no_captions(self):
        fc = _build_full_fc(_BROLL_CLIPS, [], "", motion_enabled=True)
        _assert_fc_clean(fc)

    def test_all_layers(self):
        fc = _build_full_fc(_BROLL_CLIPS, _OVERLAY_ITEMS, _ASS_PATH, motion_enabled=True)
        _assert_fc_clean(fc)
        assert "[base]" in fc
        assert "b0_look" in fc
        assert "vo0" in fc
        assert "[vcap]" in fc

    def test_retry_path_has_base_label(self):
        """Retry (no-motion) path must also start with [base] normalization."""
        fc = _build_full_fc(_BROLL_CLIPS, _OVERLAY_ITEMS, _ASS_PATH, motion_enabled=False)
        assert fc.startswith("[0:v]setpts=PTS-STARTPTS[base]"), (
            f"Retry path missing base normalization: {repr(fc[:120])}"
        )
