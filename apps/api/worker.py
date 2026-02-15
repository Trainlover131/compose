"""Background job worker for video processing pipeline."""

import json
import logging
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from apps.api.config import LOCAL_STORAGE_PATH
from apps.api.models.database import Job, Revision, SessionLocal
from apps.api.models.schemas import EditPlan
from apps.api.services.patcher import apply_edit
from apps.api.services.pexels import fetch_broll_for_plan
from apps.api.services.planner import plan_edit
from apps.api.services.render_compiler import compile_render
from apps.api.services.storage import storage
from apps.api.services.transcribe import analyze_video

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(module)s","message":"%(message)s"}',
)


def _log_stage(job_id: str, stage: str, event: str, elapsed_ms: int = 0, error: str = ""):
    """Emit structured JSON log for pipeline stage transitions."""
    entry = {
        "job_id": job_id,
        "stage": stage,
        "event": event,
        "elapsed_ms": elapsed_ms,
    }
    if error:
        entry["error"] = error[:500]
    logger.info(json.dumps(entry))


def _set_progress(db, job: Job, step: str):
    """Set progress_step and commit immediately so the poller sees it."""
    job.progress_step = step
    job.updated_at = datetime.now(timezone.utc)
    db.commit()


def _fail_job(db, job_id: str, error_msg: str, error_trace: str = ""):
    """Mark a job as error with a user-safe message. Always commits."""
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job and job.status not in ("done", "error"):
            job.status = "error"
            job.progress_step = "error"
            job.error = error_msg[:1000]
            job.error_trace = error_trace[:5000]
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as inner:
        logger.error(f"[{job_id}] Failed to mark job as error: {inner}")
        try:
            db.rollback()
        except Exception:
            pass


def process_job(job_id: str):
    """Main job processing pipeline: transcribe -> plan -> fetch assets -> render."""
    db = SessionLocal()
    pipeline_start = time.monotonic()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job not found: {job_id}")
            return

        _log_stage(job_id, "pipeline", "start")

        job.status = "processing"
        _set_progress(db, job, "transcribing")

        # Get the source video path
        source_path = storage.get_path(job.original_file_path)
        if not Path(source_path).exists():
            raise FileNotFoundError(f"Source video not found: {source_path}")

        # Step 1: Transcribe + analyze
        stage_start = time.monotonic()
        _log_stage(job_id, "transcribe", "start")
        result = analyze_video(source_path)
        transcript = result["transcript"]
        analysis = result["analysis"]
        elapsed = int((time.monotonic() - stage_start) * 1000)
        _log_stage(job_id, "transcribe", "done", elapsed_ms=elapsed)

        job.transcript_json = transcript
        job.analysis_json = analysis
        _set_progress(db, job, "planning")

        # Step 2: Generate edit plan
        stage_start = time.monotonic()
        _log_stage(job_id, "plan", "start")
        edit_plan = plan_edit(
            transcript=transcript,
            analysis=analysis,
            prompt=job.prompt,
            preset_id=job.preset_id,
            video_duration=job.duration_sec,
        )
        elapsed = int((time.monotonic() - stage_start) * 1000)
        _log_stage(job_id, "plan", "done", elapsed_ms=elapsed)

        job.edit_plan_json = edit_plan.model_dump()
        _set_progress(db, job, "fetching_broll")

        # Step 3: Fetch b-roll assets
        if edit_plan.broll.enabled and edit_plan.broll.inserts:
            stage_start = time.monotonic()
            _log_stage(job_id, "broll", "start")
            inserts_data = [i.model_dump() for i in edit_plan.broll.inserts]
            updated_inserts = fetch_broll_for_plan(inserts_data)
            # Update plan with asset paths
            plan_data = edit_plan.model_dump()
            plan_data["broll"]["inserts"] = updated_inserts
            edit_plan = EditPlan.model_validate(plan_data)
            job.edit_plan_json = edit_plan.model_dump()
            db.commit()
            elapsed = int((time.monotonic() - stage_start) * 1000)
            _log_stage(job_id, "broll", "done", elapsed_ms=elapsed)
        else:
            _log_stage(job_id, "broll", "skipped")

        # Step 4: Render
        _set_progress(db, job, "rendering")

        stage_start = time.monotonic()
        _log_stage(job_id, "render", "start")
        output_key = f"outputs/{job_id}/v1.mp4"
        output_path = storage.get_path(output_key)

        compile_render(
            edit_plan=edit_plan,
            source_video=source_path,
            transcript=transcript,
            output_path=output_path,
        )
        elapsed = int((time.monotonic() - stage_start) * 1000)
        _log_stage(job_id, "render", "done", elapsed_ms=elapsed)

        # Store output
        output_url = storage.get_url(output_key)

        job.status = "done"
        job.progress_step = "done"
        job.output_file_path = output_key
        job.output_url = output_url
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        total_elapsed = int((time.monotonic() - pipeline_start) * 1000)
        _log_stage(job_id, "pipeline", "done", elapsed_ms=total_elapsed)

    except Exception as e:
        total_elapsed = int((time.monotonic() - pipeline_start) * 1000)
        error_msg = str(e)[:1000]
        tb = traceback.format_exc()
        _log_stage(job_id, "pipeline", "error", elapsed_ms=total_elapsed, error=error_msg)
        logger.error(f"[{job_id}] Job failed: {e}")
        logger.error(tb)

        # Rollback any pending transaction before writing error state
        try:
            db.rollback()
        except Exception:
            pass

        _fail_job(db, job_id, f"Processing failed: {error_msg}", tb)
    finally:
        db.close()


def process_revision(job_id: str, revision_id: str):
    """Process a revision: generate patch -> apply -> re-render."""
    db = SessionLocal()
    rev_start = time.monotonic()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        revision = db.query(Revision).filter(Revision.id == revision_id).first()
        if not job or not revision:
            logger.error(f"Job or revision not found: {job_id}/{revision_id}")
            return

        _log_stage(job_id, f"revision-{revision.revision_number}", "start")

        revision.status = "processing"
        db.commit()

        source_path = storage.get_path(job.original_file_path)

        # Get the latest edit plan (from previous revision or original)
        if revision.revision_number > 1:
            prev_rev = (
                db.query(Revision)
                .filter(
                    Revision.job_id == job_id,
                    Revision.revision_number == revision.revision_number - 1,
                )
                .first()
            )
            if prev_rev and prev_rev.edit_plan_json:
                current_plan = EditPlan.model_validate(prev_rev.edit_plan_json)
            else:
                current_plan = EditPlan.model_validate(job.edit_plan_json)
        else:
            current_plan = EditPlan.model_validate(job.edit_plan_json)

        # Generate patch and new plan
        logger.info(f"[{job_id}/r{revision.revision_number}] Applying edit: {revision.instruction}")
        patch, new_plan = apply_edit(current_plan, revision.instruction)

        revision.patch_json = patch.model_dump(exclude_none=True)
        revision.edit_plan_json = new_plan.model_dump()
        db.commit()

        # Fetch b-roll if needed
        if new_plan.broll.enabled and new_plan.broll.inserts:
            inserts_data = [i.model_dump() for i in new_plan.broll.inserts]
            needs_fetch = [i for i in inserts_data if not i.get("asset_path")]
            if needs_fetch:
                updated = fetch_broll_for_plan(needs_fetch)
                plan_data = new_plan.model_dump()
                # Merge fetched assets back
                for orig, upd in zip(needs_fetch, updated):
                    if upd.get("asset_path"):
                        orig["asset_path"] = upd["asset_path"]
                new_plan = EditPlan.model_validate(plan_data)

        # Re-render
        output_key = f"outputs/{job_id}/v{revision.revision_number + 1}.mp4"
        output_path = storage.get_path(output_key)

        compile_render(
            edit_plan=new_plan,
            source_video=source_path,
            transcript=job.transcript_json,
            output_path=output_path,
        )

        output_url = storage.get_url(output_key)

        revision.status = "done"
        revision.output_file_path = output_key
        revision.output_url = output_url
        db.commit()

        elapsed = int((time.monotonic() - rev_start) * 1000)
        _log_stage(job_id, f"revision-{revision.revision_number}", "done", elapsed_ms=elapsed)

    except Exception as e:
        elapsed = int((time.monotonic() - rev_start) * 1000)
        error_msg = str(e)[:1000]
        _log_stage(job_id, f"revision-{revision_id}", "error", elapsed_ms=elapsed, error=error_msg)
        logger.error(f"[{job_id}/{revision_id}] Revision failed: {e}")
        logger.error(traceback.format_exc())

        try:
            db.rollback()
        except Exception:
            pass

        try:
            revision = db.query(Revision).filter(Revision.id == revision_id).first()
            if revision:
                revision.status = "error"
                revision.error = f"Revision failed: {error_msg}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
