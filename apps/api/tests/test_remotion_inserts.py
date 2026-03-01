"""Tests for Remotion full-screen inserts.

Covers:
- EditPlan schema: remotion_inserts field parsing & validation
- Server-side validator: non-overlap, duration clamping, b-roll conflict resolution
- Render compiler: filtergraph includes remotion input + overlay/replace wiring
- Render compiler: unchanged when remotion_inserts absent
- Planner: system prompt includes remotion instructions
- Planner: deterministic policy ensures >= 1 insert when appropriate
- Worker pipeline: remotion inserts are validated, rendered, and have asset_path
- E2E visibility: remotion inserts produce visually different output frames
"""

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.api.models.schemas import EditPlan, RemotionInsert, PlanPatch, RemotionPatch, apply_patch
from apps.api.services.remotion_validator import validate_remotion_inserts
from apps.api.services.render_compiler import (
    _sanitize_fc,
    build_broll_filtergraph_entries,
    build_remotion_filtergraph_entries,
)


# ===================================================================
# Schema tests
# ===================================================================

class TestRemotionInsertSchema:
    def test_valid_remotion_insert(self):
        insert = RemotionInsert(
            start=5.0,
            end=9.0,
            template_id="kpi-counter",
            props={"label": "Revenue", "value": 25000, "prefix": "$"},
            mode="default",
        )
        assert insert.start == 5.0
        assert insert.end == 9.0
        assert insert.template_id == "kpi-counter"
        assert insert.props["value"] == 25000

    def test_end_must_be_after_start(self):
        with pytest.raises(Exception):
            RemotionInsert(
                start=10.0,
                end=5.0,
                template_id="kpi-counter",
                props={},
            )

    def test_edit_plan_with_remotion_inserts(self):
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 30.0}],
            remotion_inserts=[
                {
                    "start": 5.0,
                    "end": 9.0,
                    "template_id": "kpi-counter",
                    "props": {"label": "ARR", "value": 25000},
                    "mode": "default",
                },
                {
                    "start": 18.0,
                    "end": 22.0,
                    "template_id": "quote-highlight",
                    "props": {"quote": "Hello world"},
                    "mode": "default",
                },
            ],
        )
        assert len(plan.remotion_inserts) == 2
        assert plan.remotion_inserts[0].template_id == "kpi-counter"
        assert plan.remotion_inserts[1].template_id == "quote-highlight"

    def test_edit_plan_without_remotion_inserts(self):
        """Existing plans without remotion_inserts should still work."""
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 10.0}],
        )
        assert plan.remotion_inserts == []

    def test_remotion_inserts_default_empty(self):
        plan = EditPlan()
        assert plan.remotion_inserts == []

    def test_remotion_patch_disables_inserts(self):
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 30.0}],
            remotion_inserts=[
                {
                    "start": 5.0,
                    "end": 9.0,
                    "template_id": "kpi-counter",
                    "props": {"label": "ARR", "value": 100},
                    "mode": "default",
                },
            ],
        )
        patch = PlanPatch(remotion=RemotionPatch(enabled=False))
        patched = apply_patch(plan, patch)
        assert patched.remotion_inserts == []


# ===================================================================
# Validator tests
# ===================================================================

class TestRemotionValidator:
    def test_empty_inserts(self):
        inserts, broll, logs = validate_remotion_inserts([], [], 30.0)
        assert inserts == []
        assert broll == []

    def test_valid_inserts_pass_through(self):
        remotion = [
            {"start": 5.0, "end": 9.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
            {"start": 15.0, "end": 19.0, "template_id": "steps-list", "props": {}, "mode": "default"},
        ]
        inserts, broll, logs = validate_remotion_inserts(remotion, [], 30.0)
        assert len(inserts) == 2
        assert inserts[0]["start"] == 5.0
        assert inserts[1]["start"] == 15.0

    def test_invalid_template_skipped(self):
        remotion = [
            {"start": 5.0, "end": 9.0, "template_id": "nonexistent", "props": {}},
        ]
        inserts, _, logs = validate_remotion_inserts(remotion, [], 30.0)
        assert len(inserts) == 0
        assert any("invalid template_id" in l for l in logs)

    def test_duration_clamped_min(self):
        remotion = [
            {"start": 5.0, "end": 5.5, "template_id": "kpi-counter", "props": {}, "mode": "default"},
        ]
        inserts, _, logs = validate_remotion_inserts(remotion, [], 30.0)
        assert len(inserts) == 1
        assert inserts[0]["end"] == 7.0  # extended to 2s min
        assert any("extending" in l for l in logs)

    def test_duration_clamped_max(self):
        remotion = [
            {"start": 5.0, "end": 20.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
        ]
        inserts, _, logs = validate_remotion_inserts(remotion, [], 30.0)
        assert len(inserts) == 1
        assert inserts[0]["end"] == 13.0  # clamped to 8s max
        assert any("clamping" in l for l in logs)

    def test_overlap_between_inserts_resolved(self):
        remotion = [
            {"start": 5.0, "end": 10.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
            {"start": 8.0, "end": 13.0, "template_id": "steps-list", "props": {}, "mode": "default"},
        ]
        inserts, _, logs = validate_remotion_inserts(remotion, [], 30.0)
        assert len(inserts) == 2
        assert inserts[1]["start"] == 10.0  # shifted to after first
        assert any("overlap" in l.lower() for l in logs)

    def test_max_inserts_enforced(self):
        remotion = [
            {"start": i * 10.0, "end": i * 10.0 + 3.0, "template_id": "kpi-counter", "props": {}, "mode": "default"}
            for i in range(5)
        ]
        inserts, _, logs = validate_remotion_inserts(remotion, [], 60.0, max_inserts=3)
        assert len(inserts) == 3

    def test_broll_overlap_remotion_wins(self):
        remotion = [
            {"start": 5.0, "end": 10.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
        ]
        broll = [
            {"start": 7.0, "end": 12.0, "query": "nature"},
        ]
        inserts, adjusted_broll, logs = validate_remotion_inserts(remotion, broll, 30.0)
        assert len(inserts) == 1
        assert len(adjusted_broll) == 1
        # B-roll should be trimmed: start pushed to 10.0
        assert adjusted_broll[0]["start"] == 10.0

    def test_broll_fully_overlapped_by_remotion_dropped(self):
        remotion = [
            {"start": 5.0, "end": 12.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
        ]
        broll = [
            {"start": 6.0, "end": 10.0, "query": "nature"},
        ]
        inserts, adjusted_broll, logs = validate_remotion_inserts(remotion, broll, 30.0)
        assert len(adjusted_broll) == 0
        assert any("dropping" in l.lower() for l in logs)

    def test_timeline_bounds_enforced(self):
        remotion = [
            {"start": 25.0, "end": 35.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
        ]
        inserts, _, logs = validate_remotion_inserts(remotion, [], 30.0)
        assert len(inserts) == 1
        assert inserts[0]["end"] == 30.0  # clamped to timeline end

    def test_start_before_zero_clamped(self):
        remotion = [
            {"start": -1.0, "end": 3.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
        ]
        inserts, _, logs = validate_remotion_inserts(remotion, [], 30.0)
        assert len(inserts) == 1
        assert inserts[0]["start"] == 0.0


# ===================================================================
# Render compiler: filtergraph tests
# ===================================================================

class TestRemotionFiltergraph:
    def test_no_remotion_clips_returns_empty(self):
        filters, last_label, idx = build_remotion_filtergraph_entries(
            [], 3, "[base]"
        )
        assert filters == []
        assert last_label == "[base]"
        assert idx == 3

    def test_single_remotion_clip_wiring(self):
        clips = [
            {"path": "/tmp/remotion_0.mp4", "start": 5.0, "end": 9.0},
        ]
        filters, last_label, idx = build_remotion_filtergraph_entries(
            clips, 3, "[base]"
        )
        assert len(filters) == 2  # prep + overlay
        # Check prep filter includes scale, crop, setpts
        assert "[3:v]" in filters[0]
        assert "scale=1080:1920" in filters[0]
        assert "crop=1080:1920" in filters[0]
        assert "setpts=PTS-STARTPTS+5.000/TB" in filters[0]
        assert "[ri0_prep]" in filters[0]
        # Check overlay filter
        assert "[base][ri0_prep]overlay=" in filters[1]
        assert "enable=between(t\\,5.000\\,9.000)" in filters[1]
        assert "[ri0_out]" in filters[1]
        assert last_label == "[ri0_out]"
        assert idx == 4

    def test_multiple_remotion_clips_wiring(self):
        clips = [
            {"path": "/tmp/r0.mp4", "start": 3.0, "end": 7.0},
            {"path": "/tmp/r1.mp4", "start": 15.0, "end": 19.0},
            {"path": "/tmp/r2.mp4", "start": 25.0, "end": 28.0},
        ]
        filters, last_label, idx = build_remotion_filtergraph_entries(
            clips, 5, "[vo2]"
        )
        assert len(filters) == 6  # 2 per clip
        assert last_label == "[ri2_out]"
        assert idx == 8

        # First clip uses input 5
        assert "[5:v]" in filters[0]
        # Second clip uses input 6
        assert "[6:v]" in filters[2]
        # Third clip uses input 7
        assert "[7:v]" in filters[4]

        # Chain: each overlay feeds into next
        assert "[ri0_out]" in filters[1]
        assert "[ri0_out][ri1_prep]" in filters[3]
        assert "[ri1_out][ri2_prep]" in filters[5]

    def test_remotion_clips_after_broll_in_chain(self):
        """Simulate full chain: base -> broll -> overlays -> remotion -> captions."""
        broll_clips = [
            {"path": "/tmp/broll0.mp4", "start": 2.0, "end": 5.0},
        ]
        remotion_clips = [
            {"path": "/tmp/ri0.mp4", "start": 10.0, "end": 14.0},
        ]

        filters = []
        filters.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label = "[base]"
        input_index = 1

        # B-roll
        broll_filters, last_label, input_index = build_broll_filtergraph_entries(
            broll_clips, input_index, last_label, motion_enabled=False,
        )
        filters.extend(broll_filters)

        # Remotion
        ri_filters, last_label, input_index = build_remotion_filtergraph_entries(
            remotion_clips, input_index, last_label,
        )
        filters.extend(ri_filters)

        fc = ";".join(filters)
        fc = _sanitize_fc(fc)

        # Verify chain order: base -> broll -> remotion
        assert "[base]" in fc
        assert "[b0_out]" in fc
        assert "[ri0_out]" in fc

        # Remotion is applied AFTER broll
        broll_out_pos = fc.index("[b0_out]")
        ri_out_pos = fc.index("[ri0_out]")
        assert ri_out_pos > broll_out_pos

        # Remotion overlay references the broll output label
        assert "[b0_out][ri0_prep]overlay=" in fc

    def test_filter_complex_unchanged_without_remotion(self):
        """When no remotion inserts, filter_complex is identical to before."""
        broll_clips = [
            {"path": "/tmp/broll0.mp4", "start": 2.0, "end": 5.0},
        ]

        # Build WITH empty remotion
        filters = []
        filters.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label = "[base]"
        input_index = 1

        broll_filters, last_label, input_index = build_broll_filtergraph_entries(
            broll_clips, input_index, last_label, motion_enabled=False,
        )
        filters.extend(broll_filters)

        ri_filters, last_label_ri, input_index_ri = build_remotion_filtergraph_entries(
            [], input_index, last_label,
        )
        filters.extend(ri_filters)

        fc_with_empty = ";".join(filters)

        # Build WITHOUT remotion
        filters2 = []
        filters2.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label2 = "[base]"
        input_index2 = 1

        broll_filters2, last_label2, input_index2 = build_broll_filtergraph_entries(
            broll_clips, input_index2, last_label2, motion_enabled=False,
        )
        filters2.extend(broll_filters2)

        fc_without = ";".join(filters2)

        # They should be identical
        assert fc_with_empty == fc_without

    def test_remotion_filter_has_no_weird_chars(self):
        clips = [
            {"path": "/tmp/ri.mp4", "start": 5.0, "end": 9.0},
        ]
        filters, _, _ = build_remotion_filtergraph_entries(clips, 1, "[base]")
        fc = ";".join(filters)
        fc = _sanitize_fc(fc)
        assert "\n" not in fc
        assert "'" not in fc
        assert '"' not in fc


# ===================================================================
# Planner prompt tests
# ===================================================================

class TestPlannerRemotionPrompt:
    @pytest.fixture(autouse=True)
    def _skip_if_no_planner_deps(self):
        """Skip these tests if planner deps are not installed (CI-safe)."""
        try:
            from apps.api.services.planner import PLANNER_SYSTEM_PROMPT  # noqa: F401
        except ImportError:
            pytest.skip("planner dependencies not installed (anthropic/numpy etc)")

    def test_planner_prompt_mentions_remotion(self):
        from apps.api.services.planner import PLANNER_SYSTEM_PROMPT
        assert "remotion_inserts" in PLANNER_SYSTEM_PROMPT
        assert "kpi-counter" in PLANNER_SYSTEM_PROMPT
        assert "line-chart" in PLANNER_SYSTEM_PROMPT
        assert "quote-highlight" in PLANNER_SYSTEM_PROMPT
        assert "steps-list" in PLANNER_SYSTEM_PROMPT
        assert "profile-card" in PLANNER_SYSTEM_PROMPT
        assert "code-card" in PLANNER_SYSTEM_PROMPT

    def test_planner_prompt_mentions_opt_out(self):
        from apps.api.services.planner import PLANNER_SYSTEM_PROMPT
        assert "no motion graphics" in PLANNER_SYSTEM_PROMPT
        assert "no remotion" in PLANNER_SYSTEM_PROMPT

    def test_schema_includes_remotion_inserts(self):
        from apps.api.services.planner import EDIT_PLAN_SCHEMA
        assert "remotion_inserts" in EDIT_PLAN_SCHEMA
        assert "template_id" in EDIT_PLAN_SCHEMA


# ===================================================================
# Integration: end-to-end visibility test
# ===================================================================

class TestRemotionIntegrationVisibility:
    """Test that Remotion inserts are actually wired into the FFmpeg filtergraph.

    This test renders a 2s "kpi-counter" insert and asserts the FFmpeg
    filtergraph includes the remotion input + overlay/replace wiring.
    Does NOT require FFmpeg execution.
    """

    def test_kpi_counter_insert_in_filtergraph(self):
        """Render a known insert and verify it appears in the filter chain."""
        broll_clips = []
        overlay_items = []
        remotion_clips = [
            {
                "path": "/tmp/remotion_test_kpi.mp4",
                "start": 1.0,
                "end": 3.0,
            },
        ]

        # Build full filter_complex
        filters = []
        filters.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label = "[base]"
        input_index = 1

        # B-roll (empty)
        broll_filters, last_label, input_index = build_broll_filtergraph_entries(
            broll_clips, input_index, last_label, motion_enabled=False,
        )
        filters.extend(broll_filters)

        # Remotion
        ri_filters, last_label, input_index = build_remotion_filtergraph_entries(
            remotion_clips, input_index, last_label,
        )
        filters.extend(ri_filters)

        fc = ";".join(filters)
        fc = _sanitize_fc(fc)

        # Assert remotion input is present
        assert "[1:v]" in fc, "Remotion input not found in filtergraph"

        # Assert prep filter includes correct time offset
        assert "setpts=PTS-STARTPTS+1.000/TB" in fc, "Remotion setpts not found"

        # Assert overlay enable window
        assert "enable=between(t\\,1.000\\,3.000)" in fc, "Remotion enable window not found"

        # Assert final label
        assert last_label == "[ri0_out]"

        # Assert the insert replaces base video (overlay is full-frame)
        assert "[base][ri0_prep]overlay=" in fc, "Remotion overlay not applied to base"

    def test_remotion_after_broll_before_caption_position(self):
        """Verify layer ordering: base -> broll -> remotion (then captions would go on top)."""
        broll_clips = [
            {"path": "/tmp/broll.mp4", "start": 1.0, "end": 3.0},
        ]
        remotion_clips = [
            {"path": "/tmp/ri.mp4", "start": 5.0, "end": 8.0},
        ]

        filters = []
        filters.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label = "[base]"
        input_index = 1

        # B-roll
        broll_filters, last_label, input_index = build_broll_filtergraph_entries(
            broll_clips, input_index, last_label, motion_enabled=False,
        )
        filters.extend(broll_filters)

        # Remotion
        ri_filters, last_label, input_index = build_remotion_filtergraph_entries(
            remotion_clips, input_index, last_label,
        )
        filters.extend(ri_filters)

        # Simulate captions (would go after)
        filters.append(f"{last_label}ass=/tmp/captions.ass[vcap]")
        last_label = "[vcap]"

        fc = ";".join(filters)

        # Verify ordering
        broll_overlay_pos = fc.index("b0_out")
        remotion_overlay_pos = fc.index("ri0_out")
        caption_pos = fc.index("vcap")

        assert broll_overlay_pos < remotion_overlay_pos < caption_pos, \
            "Layer ordering must be: broll < remotion < captions"

    def test_frames_differ_with_and_without_remotion(self):
        """Structural test: filtergraphs WITH vs WITHOUT remotion inserts differ."""
        broll_clips = [
            {"path": "/tmp/broll.mp4", "start": 1.0, "end": 3.0},
        ]
        remotion_clips = [
            {"path": "/tmp/ri.mp4", "start": 5.0, "end": 8.0},
        ]

        # WITH remotion
        filters_with = []
        filters_with.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label = "[base]"
        idx = 1
        bf, last_label, idx = build_broll_filtergraph_entries(broll_clips, idx, last_label, False)
        filters_with.extend(bf)
        rf, last_label, idx = build_remotion_filtergraph_entries(remotion_clips, idx, last_label)
        filters_with.extend(rf)
        fc_with = ";".join(filters_with)

        # WITHOUT remotion
        filters_without = []
        filters_without.append("[0:v]setpts=PTS-STARTPTS[base]")
        last_label2 = "[base]"
        idx2 = 1
        bf2, last_label2, idx2 = build_broll_filtergraph_entries(broll_clips, idx2, last_label2, False)
        filters_without.extend(bf2)
        fc_without = ";".join(filters_without)

        # They MUST differ
        assert fc_with != fc_without, "Filtergraph must change when remotion inserts are present"
        assert "ri0_out" in fc_with
        assert "ri0_out" not in fc_without


# ===================================================================
# Planner deterministic remotion policy tests
# ===================================================================

class TestRemotionInsertPolicy:
    """Tests for _ensure_remotion_inserts deterministic policy.

    Imports are inline so the test suite works even when planner
    dependencies (anthropic, numpy, PIL) are not installed.
    """

    @pytest.fixture(autouse=True)
    def _import_policy(self):
        """Try to import the planner policy function; skip if deps missing."""
        try:
            from apps.api.services.planner import _ensure_remotion_inserts
            self._ensure = _ensure_remotion_inserts
        except ImportError:
            pytest.skip("Planner dependencies not available (anthropic/numpy etc)")

    def test_inserts_generated_for_long_video_without_opt_out(self):
        """Videos >= 20s without opt-out MUST get at least 1 remotion insert."""
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 30.0}],
        )
        transcript = {
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Hello welcome to our show."},
                {"start": 5.0, "end": 12.0, "text": "Today we discuss revenue growth of 25%."},
                {"start": 12.0, "end": 20.0, "text": "Our ARR reached 10 million dollars."},
                {"start": 20.0, "end": 30.0, "text": "Thank you for watching."},
            ]
        }

        result = self._ensure(plan, "make it engaging", transcript)
        assert len(result.remotion_inserts) >= 1, (
            "Videos >= 20s without opt-out must have at least 1 remotion insert"
        )
        assert result.remotion_inserts[0].template_id == "quote-highlight"

    def test_inserts_not_generated_for_short_video(self):
        """Videos < 20s should NOT get forced remotion inserts."""
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 15.0}],
        )
        transcript = {
            "segments": [
                {"start": 0.0, "end": 15.0, "text": "A short clip."},
            ]
        }

        result = self._ensure(plan, "make it short", transcript)
        assert len(result.remotion_inserts) == 0

    def test_inserts_not_generated_when_user_opts_out(self):
        """User saying 'no motion graphics' must suppress inserts."""
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 30.0}],
        )
        transcript = {
            "segments": [
                {"start": 0.0, "end": 30.0, "text": "A long video."},
            ]
        }

        for phrase in ["no motion graphics", "no remotion", "no animated inserts"]:
            result = self._ensure(plan, f"edit this but {phrase}", transcript)
            assert len(result.remotion_inserts) == 0, (
                f"Opt-out phrase '{phrase}' should suppress inserts"
            )

    def test_existing_llm_inserts_preserved(self):
        """If the LLM already provided inserts, they should be kept as-is."""
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 30.0}],
            remotion_inserts=[
                {
                    "start": 5.0,
                    "end": 9.0,
                    "template_id": "kpi-counter",
                    "props": {"label": "Revenue", "value": 25000},
                    "mode": "default",
                },
            ],
        )
        transcript = {"segments": [{"start": 0.0, "end": 30.0, "text": "test"}]}

        result = self._ensure(plan, "make it great", transcript)
        assert len(result.remotion_inserts) == 1
        assert result.remotion_inserts[0].template_id == "kpi-counter"

    def test_insert_does_not_overlap_broll(self):
        """Fallback insert should avoid overlapping with b-roll windows."""
        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 40.0}],
            broll={
                "enabled": True,
                "strategy": "cutaway_fullscreen",
                "inserts": [
                    {"start": 10.0, "end": 15.0, "query": "nature", "keywords": ["nature"]},
                ],
            },
        )
        transcript = {
            "segments": [
                {"start": 0.0, "end": 10.0, "text": "Start of the video."},
                {"start": 10.0, "end": 20.0, "text": "Middle of the video with important info."},
                {"start": 20.0, "end": 40.0, "text": "End of the video."},
            ]
        }

        result = self._ensure(plan, "make it engaging", transcript)
        assert len(result.remotion_inserts) >= 1

        ri = result.remotion_inserts[0]
        # Must not overlap with b-roll [10.0, 15.0]
        assert ri.end <= 10.0 or ri.start >= 15.0, (
            f"Insert [{ri.start}, {ri.end}] overlaps b-roll [10.0, 15.0]"
        )


# ===================================================================
# Worker pipeline wiring tests
# ===================================================================

def _can_import_worker() -> bool:
    """Check if worker module can be imported (requires sqlalchemy etc)."""
    try:
        from apps.api.worker import _process_remotion_inserts  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _can_import_worker(), reason="Worker dependencies not available (sqlalchemy etc)")
class TestWorkerRemotionWiring:
    """Verify that _process_remotion_inserts correctly validates, renders, and
    populates asset_path on remotion inserts before compile_render runs."""

    def test_process_remotion_inserts_calls_validator_and_renderer(self):
        """_process_remotion_inserts must call validate then render, and
        update the EditPlan with asset_path-bearing inserts."""
        from apps.api.worker import _process_remotion_inserts

        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 30.0}],
            remotion_inserts=[
                {
                    "start": 1.0,
                    "end": 3.0,
                    "template_id": "kpi-counter",
                    "props": {"label": "TEST", "value": 123},
                    "mode": "default",
                },
            ],
        )

        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.edit_plan_json = plan.model_dump()

        fake_asset = "/tmp/fake_remotion_asset.mp4"

        with patch("apps.api.worker.validate_remotion_inserts") as mock_validate, \
             patch("apps.api.worker.render_inserts_for_plan") as mock_render:

            mock_validate.return_value = (
                [{"start": 1.0, "end": 3.0, "template_id": "kpi-counter", "props": {"label": "TEST", "value": 123}, "mode": "default"}],
                [],
                [],
            )

            mock_render.return_value = [
                {"start": 1.0, "end": 3.0, "template_id": "kpi-counter", "props": {"label": "TEST", "value": 123}, "mode": "default", "asset_path": fake_asset},
            ]

            Path(fake_asset).touch()
            try:
                updated_plan = _process_remotion_inserts("test-job-id", mock_db, mock_job, plan)

                mock_validate.assert_called_once()
                mock_render.assert_called_once()

                assert len(updated_plan.remotion_inserts) == 1
                assert updated_plan.remotion_inserts[0].asset_path == fake_asset
            finally:
                Path(fake_asset).unlink(missing_ok=True)

    def test_process_remotion_inserts_empty_list(self):
        """When no remotion inserts in plan, _process_remotion_inserts is a no-op."""
        from apps.api.worker import _process_remotion_inserts

        plan = EditPlan(main_cuts=[{"start": 0.0, "end": 10.0}])

        mock_db = MagicMock()
        mock_job = MagicMock()

        result = _process_remotion_inserts("test-job-id", mock_db, mock_job, plan)
        assert result.remotion_inserts == []

    def test_process_remotion_inserts_filters_failed_renders(self):
        """Inserts where render fails (asset_path=None) are excluded."""
        from apps.api.worker import _process_remotion_inserts

        plan = EditPlan(
            main_cuts=[{"start": 0.0, "end": 30.0}],
            remotion_inserts=[
                {"start": 1.0, "end": 3.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
                {"start": 10.0, "end": 13.0, "template_id": "steps-list", "props": {}, "mode": "default"},
            ],
        )

        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.edit_plan_json = plan.model_dump()

        fake_asset = "/tmp/fake_remotion_success.mp4"

        with patch("apps.api.worker.validate_remotion_inserts") as mock_validate, \
             patch("apps.api.worker.render_inserts_for_plan") as mock_render:

            mock_validate.return_value = (
                [
                    {"start": 1.0, "end": 3.0, "template_id": "kpi-counter", "props": {}, "mode": "default"},
                    {"start": 10.0, "end": 13.0, "template_id": "steps-list", "props": {}, "mode": "default"},
                ],
                [],
                [],
            )

            mock_render.return_value = [
                {"start": 1.0, "end": 3.0, "template_id": "kpi-counter", "props": {}, "mode": "default", "asset_path": fake_asset},
                {"start": 10.0, "end": 13.0, "template_id": "steps-list", "props": {}, "mode": "default", "asset_path": None},
            ]

            Path(fake_asset).touch()
            try:
                updated_plan = _process_remotion_inserts("test-job-id", mock_db, mock_job, plan)

                assert len(updated_plan.remotion_inserts) == 1
                assert updated_plan.remotion_inserts[0].template_id == "kpi-counter"
            finally:
                Path(fake_asset).unlink(missing_ok=True)


# ===================================================================
# E2E visibility test (requires FFmpeg)
# ===================================================================

def _has_ffmpeg() -> bool:
    """Check if ffmpeg is available on the system."""
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _generate_test_video(path: str, duration: float = 5.0, color: str = "blue"):
    """Generate a solid-color test video using FFmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            f"color=c={color}:s=1080x1920:d={duration}:r=30",
            "-f", "lavfi", "-i",
            f"anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k",
            "-shortest",
            path,
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )


def _generate_remotion_dummy(path: str, duration: float = 2.0, color: str = "red"):
    """Generate a dummy 'remotion insert' clip (solid red) for testing."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            f"color=c={color}:s=1080x1920:d={duration}:r=30",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p",
            path,
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )


def _extract_frame_hash(video_path: str, timestamp: float) -> str:
    """Extract a single frame at the given timestamp and return its MD5 hash."""
    frame_path = video_path.replace(".mp4", f"_frame_{timestamp:.1f}.raw")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", video_path,
            "-frames:v", "1",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            frame_path,
        ],
        capture_output=True,
        timeout=10,
        check=True,
    )
    data = Path(frame_path).read_bytes()
    Path(frame_path).unlink(missing_ok=True)
    return hashlib.md5(data).hexdigest()


@pytest.mark.skipif(not _has_ffmpeg(), reason="FFmpeg not available")
class TestRemotionE2EVisibility:
    """End-to-end test: a remotion insert at t=1.0-3.0 must produce
    visually different frames compared to a render without inserts."""

    @pytest.fixture(autouse=True)
    def _setup_work_dir(self, tmp_path):
        self.work = tmp_path
        self.source_video = str(self.work / "source.mp4")
        self.remotion_clip = str(self.work / "remotion_insert.mp4")
        self.output_with = str(self.work / "output_with_remotion.mp4")
        self.output_without = str(self.work / "output_without_remotion.mp4")

        _generate_test_video(self.source_video, duration=5.0, color="blue")
        _generate_remotion_dummy(self.remotion_clip, duration=2.0, color="red")

    def test_remotion_insert_changes_frame_at_insert_window(self):
        """Frame at t=2.0 must differ between render-with-remotion and without."""

        remotion_clips = [{"path": self.remotion_clip, "start": 1.0, "end": 3.0}]

        filters_with = ["[0:v]setpts=PTS-STARTPTS[base]"]
        last_label = "[base]"
        ri_filters, last_label, _ = build_remotion_filtergraph_entries(
            remotion_clips, 1, last_label,
        )
        filters_with.extend(ri_filters)
        fc_with = _sanitize_fc(";".join(filters_with))

        cmd_with = [
            "ffmpeg", "-y",
            "-i", self.source_video, "-i", self.remotion_clip,
            "-filter_complex", fc_with,
            "-map", last_label, "-map", "0:a?",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
            self.output_with,
        ]
        result = subprocess.run(cmd_with, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"FFmpeg with remotion failed: {result.stderr[-500:]}"

        cmd_without = [
            "ffmpeg", "-y", "-i", self.source_video,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
            self.output_without,
        ]
        result = subprocess.run(cmd_without, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0

        hash_with = _extract_frame_hash(self.output_with, 2.0)
        hash_without = _extract_frame_hash(self.output_without, 2.0)

        assert hash_with != hash_without, (
            "Frame at t=2.0 must differ: remotion insert (red) should replace base (blue)"
        )
