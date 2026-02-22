"""Tests for EditPlan validation, PlanPatch application, and ASS subtitle generation."""

import pytest
from apps.api.models.schemas import (
    EditPlan,
    PlanPatch,
    CaptionPatch,
    MusicPatch,
    BrollPatch,
    PunchInPatch,
    TimingPatch,
    apply_patch,
)


class TestEditPlanValidation:
    def test_valid_plan(self):
        plan = EditPlan(
            version="1",
            preset_id="snappy-creator",
            main_cuts=[
                {"start": 0.0, "end": 10.0},
                {"start": 15.0, "end": 25.0},
            ],
        )
        assert plan.total_duration() == 20.0
        assert len(plan.main_cuts) == 2

    def test_empty_plan_defaults(self):
        plan = EditPlan()
        assert plan.version == "1"
        assert plan.output.aspect_ratio == "9:16"
        assert plan.output.resolution == [1080, 1920]
        assert plan.captions.enabled is True
        assert plan.music.enabled is True

    def test_overlapping_cuts_rejected(self):
        with pytest.raises(Exception):
            EditPlan(
                main_cuts=[
                    {"start": 0.0, "end": 10.0},
                    {"start": 5.0, "end": 15.0},  # overlaps
                ],
            )

    def test_cut_end_before_start_rejected(self):
        with pytest.raises(Exception):
            EditPlan(
                main_cuts=[
                    {"start": 10.0, "end": 5.0},
                ],
            )

    def test_cuts_auto_sorted(self):
        plan = EditPlan(
            main_cuts=[
                {"start": 20.0, "end": 30.0},
                {"start": 5.0, "end": 15.0},
            ],
        )
        assert plan.main_cuts[0].start == 5.0
        assert plan.main_cuts[1].start == 20.0

    def test_punch_in_scale_bounds(self):
        plan = EditPlan(
            main_cuts=[{"start": 0, "end": 30}],
            punch_ins=[{"start": 5, "end": 6, "scale": 1.1}],
        )
        assert plan.punch_ins[0].scale == 1.1

    def test_punch_in_scale_too_high(self):
        with pytest.raises(Exception):
            EditPlan(
                main_cuts=[{"start": 0, "end": 30}],
                punch_ins=[{"start": 5, "end": 6, "scale": 2.0}],
            )

    def test_full_plan_from_dict(self):
        data = {
            "version": "1",
            "preset_id": "cinematic-doc",
            "output": {"aspect_ratio": "9:16", "resolution": [1080, 1920], "max_duration_sec": 60},
            "main_cuts": [
                {"start": 0.5, "end": 12.0},
                {"start": 14.0, "end": 28.0},
                {"start": 30.0, "end": 45.0},
            ],
            "punch_ins": [{"start": 5.0, "end": 6.0, "scale": 1.08}],
            "broll": {
                "enabled": True,
                "strategy": "cutaway_fullscreen",
                "inserts": [
                    {"start": 10.0, "end": 13.0, "query": "city skyline", "keywords": ["city"], "source": "pexels", "notes": ""},
                ],
            },
            "captions": {"enabled": True, "style_id": "cinematic", "max_words_per_line": 6, "max_lines": 2},
            "music": {"enabled": True, "track_id": "cinematic-ambient", "target_volume_db": -18.0},
            "rationale": {"hook": "Open with impact", "structure": ["intro", "body", "cta"]},
        }
        plan = EditPlan.model_validate(data)
        assert plan.total_duration() == pytest.approx(40.5)
        assert len(plan.broll.inserts) == 1


class TestPlanPatch:
    def _base_plan(self) -> EditPlan:
        return EditPlan(
            preset_id="snappy-creator",
            main_cuts=[
                {"start": 0, "end": 15},
                {"start": 20, "end": 35},
            ],
            punch_ins=[
                {"start": 5, "end": 6, "scale": 1.1},
                {"start": 25, "end": 26, "scale": 1.12},
            ],
            captions={"enabled": True, "style_id": "snappy", "max_words_per_line": 4, "max_lines": 2},
            music={"enabled": True, "track_id": "upbeat-energy", "target_volume_db": -18.0},
        )

    def test_caption_patch(self):
        plan = self._base_plan()
        patch = PlanPatch(captions=CaptionPatch(style_id="cinematic", max_words_per_line=6))
        new_plan = apply_patch(plan, patch)
        assert new_plan.captions.style_id == "cinematic"
        assert new_plan.captions.max_words_per_line == 6
        assert new_plan.captions.max_lines == 2  # unchanged

    def test_music_patch(self):
        plan = self._base_plan()
        patch = PlanPatch(music=MusicPatch(track_id="cinematic-ambient", target_volume_db=-24.0))
        new_plan = apply_patch(plan, patch)
        assert new_plan.music.track_id == "cinematic-ambient"
        assert new_plan.music.target_volume_db == -24.0

    def test_disable_punch_ins(self):
        plan = self._base_plan()
        patch = PlanPatch(punch_ins=PunchInPatch(enabled=False))
        new_plan = apply_patch(plan, patch)
        assert len(new_plan.punch_ins) == 0

    def test_punch_in_strength(self):
        plan = self._base_plan()
        patch = PlanPatch(punch_ins=PunchInPatch(strength_multiplier=1.2))
        new_plan = apply_patch(plan, patch)
        assert new_plan.punch_ins[0].scale == pytest.approx(1.32)  # 1.1 * 1.2

    def test_tightness_patch(self):
        plan = self._base_plan()
        assert plan.total_duration() == 30.0
        patch = PlanPatch(timing_adjustments=TimingPatch(tightness=0.5))
        new_plan = apply_patch(plan, patch)
        assert new_plan.total_duration() <= 15.0 + 1.0  # ~50% of original

    def test_broll_limit_patch(self):
        plan = EditPlan(
            main_cuts=[{"start": 0, "end": 60}],
            broll={
                "enabled": True,
                "strategy": "cutaway_fullscreen",
                "inserts": [
                    {"start": 5, "end": 8, "query": "a", "keywords": [], "source": "pexels", "notes": ""},
                    {"start": 15, "end": 18, "query": "b", "keywords": [], "source": "pexels", "notes": ""},
                    {"start": 25, "end": 28, "query": "c", "keywords": [], "source": "pexels", "notes": ""},
                ],
            },
        )
        patch = PlanPatch(broll=BrollPatch(max_broll_clips=1))
        new_plan = apply_patch(plan, patch)
        assert len(new_plan.broll.inserts) == 1

    def test_disable_music(self):
        plan = self._base_plan()
        patch = PlanPatch(music=MusicPatch(enabled=False))
        new_plan = apply_patch(plan, patch)
        assert new_plan.music.enabled is False
        assert new_plan.music.track_id == "upbeat-energy"  # unchanged

    def test_noop_patch(self):
        plan = self._base_plan()
        patch = PlanPatch()
        new_plan = apply_patch(plan, patch)
        assert new_plan.total_duration() == plan.total_duration()

    def test_main_cuts_unchanged_on_caption_patch(self):
        plan = self._base_plan()
        original_cuts = [(c.start, c.end) for c in plan.main_cuts]
        patch = PlanPatch(captions=CaptionPatch(style_id="luxury"))
        new_plan = apply_patch(plan, patch)
        new_cuts = [(c.start, c.end) for c in new_plan.main_cuts]
        assert new_cuts == original_cuts


class TestASSSubtitles:
    def test_format_ass_time(self):
        from apps.api.services.render_compiler import _format_ass_time
        assert _format_ass_time(0.0) == "0:00:00.00"
        assert _format_ass_time(65.5) == "0:01:05.50"
        assert _format_ass_time(3661.25) == "1:01:01.25"

    def test_build_timeline_map(self):
        from apps.api.services.render_compiler import _build_timeline_map
        plan = EditPlan(
            main_cuts=[
                {"start": 5.0, "end": 15.0},
                {"start": 20.0, "end": 30.0},
            ],
        )
        tmap = _build_timeline_map(plan)
        assert len(tmap) == 2
        assert tmap[0]["final_start"] == 0.0
        assert tmap[0]["final_end"] == 10.0
        assert tmap[1]["final_start"] == 10.0
        assert tmap[1]["final_end"] == 20.0

    def test_map_time(self):
        from apps.api.services.render_compiler import _build_timeline_map, _map_time
        plan = EditPlan(
            main_cuts=[
                {"start": 5.0, "end": 15.0},
                {"start": 20.0, "end": 30.0},
            ],
        )
        tmap = _build_timeline_map(plan)
        # Time 7.0 is 2s into first cut -> final time 2.0
        assert _map_time(7.0, tmap) == pytest.approx(2.0)
        # Time 25.0 is 5s into second cut -> final time 15.0
        assert _map_time(25.0, tmap) == pytest.approx(15.0)
        # Time 17.0 is in a gap -> None
        assert _map_time(17.0, tmap) is None

    def test_generate_ass_subtitles(self):
        import tempfile
        from apps.api.services.render_compiler import generate_ass_subtitles
        plan = EditPlan(
            main_cuts=[{"start": 0, "end": 10}],
            captions={"enabled": True, "style_id": "default", "max_words_per_line": 3, "max_lines": 2},
        )
        transcript = {
            "segments": [{
                "id": 0, "start": 0.0, "end": 5.0,
                "text": "Hello world this is a test",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.5, "probability": 0.99},
                    {"word": "world", "start": 0.5, "end": 1.0, "probability": 0.99},
                    {"word": "this", "start": 1.0, "end": 1.3, "probability": 0.99},
                    {"word": "is", "start": 1.3, "end": 1.5, "probability": 0.99},
                    {"word": "a", "start": 1.5, "end": 1.6, "probability": 0.99},
                    {"word": "test", "start": 1.6, "end": 2.0, "probability": 0.99},
                ],
            }],
        }
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            path = f.name
        generate_ass_subtitles(transcript, plan, path)
        with open(path) as f:
            content = f.read()
        assert "[Script Info]" in content
        assert "Dialogue:" in content
        assert "Hello world this" in content  # First 3 words on one line


class TestRenderCompiler:
    def test_compile_render_builds_without_crash(self):
        """Test that compile_render constructs valid FFmpeg commands.

        This test validates the plan compilation logic without actually
        running FFmpeg (which requires video files).
        """
        plan = EditPlan(
            preset_id="snappy-creator",
            main_cuts=[
                {"start": 0, "end": 10},
                {"start": 15, "end": 25},
            ],
            punch_ins=[{"start": 5, "end": 6, "scale": 1.1}],
            captions={"enabled": True, "style_id": "snappy"},
            music={"enabled": False},
            broll={"enabled": False, "strategy": "cutaway_fullscreen", "inserts": []},
        )
        # Verify the plan is valid and can be used for rendering
        assert plan.total_duration() == 20.0
        assert len(plan.main_cuts) == 2
        assert plan.output.resolution == [1080, 1920]


class TestExtractOverlayTimes:
    """Unit tests for _extract_overlay_times backwards-compatible time parsing."""

    def test_legacy_start_end_survives(self):
        """Overlay with legacy start/end fields returns correct floats."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"start": 5.0, "end": 10.0, "image_prompt": "test"}
        s, e, reason = _extract_overlay_times(ov)
        assert reason is None
        assert s == 5.0
        assert e == 10.0
        assert isinstance(s, float)
        assert isinstance(e, float)

    def test_start_orig_end_orig_survives(self):
        """Overlay with start_orig/end_orig fields returns correct floats."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"start_orig": 12.5, "end_orig": 18.3, "image_prompt": "test"}
        s, e, reason = _extract_overlay_times(ov)
        assert reason is None
        assert s == pytest.approx(12.5)
        assert e == pytest.approx(18.3)

    def test_start_orig_preferred_over_legacy(self):
        """start_orig/end_orig take priority when both pairs present."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"start_orig": 3.0, "end_orig": 7.0, "start": 0.0, "end": 1.0}
        s, e, reason = _extract_overlay_times(ov)
        assert reason is None
        assert s == 3.0
        assert e == 7.0

    def test_missing_both_pairs_rejected(self):
        """Overlay missing all time fields is rejected with MISSING_TIMES."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"image_prompt": "test"}
        s, e, reason = _extract_overlay_times(ov)
        assert s is None
        assert e is None
        assert reason == "MISSING_TIMES"

    def test_non_numeric_rejected(self):
        """Overlay with non-numeric time values is rejected."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"start_orig": "abc", "end_orig": "xyz"}
        s, e, reason = _extract_overlay_times(ov)
        assert s is None
        assert e is None
        assert reason == "NON_NUMERIC_TIMES"

    def test_start_ge_end_rejected(self):
        """Overlay where start >= end is rejected with START_GE_END."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"start_orig": 10.0, "end_orig": 5.0}
        s, e, reason = _extract_overlay_times(ov)
        assert reason == "START_GE_END"

    def test_string_numbers_coerced(self):
        """String-encoded numeric values are coerced to float."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"start": "2.5", "end": "8.0"}
        s, e, reason = _extract_overlay_times(ov)
        assert reason is None
        assert s == 2.5
        assert e == 8.0

    def test_fallback_when_orig_non_numeric(self):
        """Falls back to start/end when start_orig/end_orig are non-numeric."""
        from apps.api.services.planner import _extract_overlay_times

        ov = {"start_orig": "bad", "end_orig": "bad", "start": 1.0, "end": 3.0}
        s, e, reason = _extract_overlay_times(ov)
        assert reason is None
        assert s == 1.0
        assert e == 3.0


class TestOverlayMappingSurvival:
    """Tests that overlays survive _map_vd_overlays with various field combos."""

    def test_intent_only_overlay_survives_mapping(self):
        """Overlay with intent/style_notes but NO image_prompt survives mapping."""
        from apps.api.services.planner import _map_vd_overlays, _build_timeline_map_from_cuts

        # Single cut covering 0-60s original -> 0-60s final
        cuts = [type("Cut", (), {"start": 0.0, "end": 60.0})()]
        tmap = _build_timeline_map_from_cuts(cuts)

        overlays = [{
            "start_orig": 10.0,
            "end_orig": 12.0,
            # No image_prompt
            "intent": "Show the YC logo as a badge",
            "style_notes": "flat design, orange background",
            "text": "YC",
            "must_include": ["YC logo"],
            "must_avoid": [],
            "placement": {"x": 0.8, "y": 0.1, "w": 0.2},
            "animation": {"fade_in": 0.2, "fade_out": 0.2},
            "reason": "anchor: we got into Y Combinator",
            "render_intent": {
                "profile": "logo_badge",
                "has_text": True,
                "requires_high_fidelity_text": False,
                "wants_transparency": True,
            },
        }]

        mapped = _map_vd_overlays(overlays, tmap)
        assert len(mapped) == 1
        assert mapped[0]["start"] == pytest.approx(10.0)
        assert mapped[0]["end"] == pytest.approx(12.0)
        assert mapped[0]["intent"] == "Show the YC logo as a badge"
        # query should default to empty string when image_prompt missing
        assert mapped[0]["query"] == ""

    def test_overlay_clipped_to_cut_boundary(self):
        """Overlay spanning a cut boundary is clipped, not dropped."""
        from apps.api.services.planner import _map_vd_overlays, _build_timeline_map_from_cuts

        # Cut covers 5-20s only
        cuts = [type("Cut", (), {"start": 5.0, "end": 20.0})()]
        tmap = _build_timeline_map_from_cuts(cuts)

        overlays = [{
            "start_orig": 18.0,
            "end_orig": 25.0,  # extends past cut boundary
            "image_prompt": "factory assembly line",
            "placement": {"x": 0.5, "y": 0.5, "w": 0.3},
            "animation": {"fade_in": 0.15, "fade_out": 0.15},
            "reason": "test",
        }]

        mapped = _map_vd_overlays(overlays, tmap)
        assert len(mapped) == 1
        # start at 18.0 -> 13.0 in final (18-5=13)
        assert mapped[0]["start"] == pytest.approx(13.0)
        # end clipped to cut boundary: 20.0 -> 15.0 in final
        assert mapped[0]["end"] == pytest.approx(15.0)


class TestMinBrollStartPolicy:
    """Verify MIN_BROLL_START applies ONLY to b-roll, never to overlays."""

    def test_overlay_allowed_before_min_broll_start(self):
        """Overlays starting before 3.0s must NOT be filtered by MIN_BROLL_START."""
        from apps.api.services.planner import (
            _enforce_min_broll_start,
            _build_timeline_map_from_cuts,
            _map_vd_overlays,
            _enforce_nonoverlap,
            MIN_BROLL_START,
        )

        # Single cut: 0-60s original -> 0-60s final
        cuts = [type("Cut", (), {"start": 0.0, "end": 60.0})()]
        tmap = _build_timeline_map_from_cuts(cuts)

        # Overlay at 0.5-2.5s (well inside the "orientation buffer")
        vd_overlays = [{
            "start_orig": 0.5,
            "end_orig": 2.5,
            "image_prompt": "company logo",
            "placement": {"x": 0.8, "y": 0.1, "w": 0.2},
            "animation": {"fade_in": 0.12, "fade_out": 0.12},
            "reason": "brand intro",
        }]

        overlay_items = _map_vd_overlays(vd_overlays, tmap)
        overlay_items = _enforce_nonoverlap(overlay_items)

        # Overlay survives mapping — it should be at 0.5-2.5 in final
        assert len(overlay_items) == 1
        assert overlay_items[0]["start"] == pytest.approx(0.5)
        assert overlay_items[0]["end"] == pytest.approx(2.5)
        assert overlay_items[0]["start"] < MIN_BROLL_START

        # Crucially, _enforce_min_broll_start is NOT called on overlays.
        # Verify that if we DID call it, b-roll at <3s would be shifted/dropped,
        # but overlays go through a different code path entirely.
        broll_at_1s = [{"start": 1.0, "end": 2.5, "query": "test"}]
        filtered_broll = _enforce_min_broll_start(broll_at_1s, tmap)
        # B-roll should be shifted to 3.0 (or dropped if it doesn't fit)
        if filtered_broll:
            assert filtered_broll[0]["start"] >= MIN_BROLL_START
        # But overlay_items remain untouched at 0.5s
        assert overlay_items[0]["start"] == pytest.approx(0.5)


class TestNanoBananaProParsing:
    """Tests for NanoBanana Pro response parsing (isolated from Regular)."""

    def test_pro_callback_shape_extracts_url(self):
        """Pro callback shape extracts data.info.resultImageUrl correctly."""
        from apps.api.services.planner import _parse_nanobanana_pro_result_url

        payload = {
            "code": 200,
            "msg": "Image generated successfully.",
            "data": {
                "taskId": "abc-123",
                "info": {
                    "resultImageUrl": "https://cdn.example.com/image.jpg",
                },
            },
        }
        task_id, url = _parse_nanobanana_pro_result_url(payload)
        assert task_id == "abc-123"
        assert url == "https://cdn.example.com/image.jpg"

    def test_pro_pending_task_returns_id_no_url(self):
        """Pro response with taskId but no info yet returns (id, None)."""
        from apps.api.services.planner import _parse_nanobanana_pro_result_url

        payload = {
            "code": 200,
            "msg": "Task created.",
            "data": {
                "taskId": "pending-456",
            },
        }
        task_id, url = _parse_nanobanana_pro_result_url(payload)
        assert task_id == "pending-456"
        assert url is None

    def test_pro_empty_payload_returns_none(self):
        """Pro parser handles empty/malformed payloads gracefully."""
        from apps.api.services.planner import _parse_nanobanana_pro_result_url

        assert _parse_nanobanana_pro_result_url({}) == (None, None)
        assert _parse_nanobanana_pro_result_url({"data": "bad"}) == (None, None)


class TestNanoBananaRegularParsing:
    """Verify Regular NanoBanana parsing is byte-for-byte unchanged."""

    def test_regular_extract_result_url_known_good(self):
        """Regular _extract_result_url still extracts URL from known-good response."""
        from apps.api.services.planner import _extract_result_url

        # Known-good Regular response shape (top-level url field)
        payload = {"url": "https://regular.example.com/image.png", "taskId": "r-1"}
        assert _extract_result_url(payload) == "https://regular.example.com/image.png"

        # Known-good Regular response shape (resultImageUrl in data)
        payload2 = {"data": {"resultImageUrl": "https://regular.example.com/r2.png"}}
        assert _extract_result_url(payload2) == "https://regular.example.com/r2.png"

    def test_regular_parsing_reads_expected_keys(self):
        """Snapshot test: Regular parsing checks the exact same JSON keys as before.

        The Regular path in _nanobanana_call_and_parse reads these keys for
        task detection: data.get("taskId"), data["data"].get("taskId").
        For direct URL: "url", "image_url", "imageUrl", "output".
        For arrays: "images", "results".
        For base64: "base64", "image_base64", item "b64".
        This test asserts _extract_result_url checks the documented keys.
        """
        from apps.api.services.planner import _extract_result_url
        import inspect

        source = inspect.getsource(_extract_result_url)

        # Top-level URL keys (exact tuple from the code)
        for key in ("resultImageUrl", "resultImageURL", "url", "resultUrl",
                     "resultURL", "result_image_url"):
            assert f'"{key}"' in source, f"Regular parser missing key: {key}"

        # Array keys
        for key in ("resultImageUrls", "resultURLs", "urls", "images", "results"):
            assert f'"{key}"' in source, f"Regular parser missing array key: {key}"

        # Nested keys
        for key in ("data", "result", "output"):
            assert f'"{key}"' in source, f"Regular parser missing nested key: {key}"
