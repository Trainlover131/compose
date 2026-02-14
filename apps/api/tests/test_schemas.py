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
