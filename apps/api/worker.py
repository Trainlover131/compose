"""Background job worker for video processing pipeline."""

import json
import logging
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


def process_job(job_id: str):
    """Main job processing pipeline: transcribe → plan → fetch assets → render."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job not found: {job_id}")
            return

        job.status = "processing"
        job.progress_step = "transcribing"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Get the source video path
        source_path = storage.get_path(job.original_file_path)
        if not Path(source_path).exists():
            raise FileNotFoundError(f"Source video not found: {source_path}")

        # Step 1: Transcribe + analyze
        logger.info(f"[{job_id}] Transcribing...")
        result = analyze_video(source_path)
        transcript = result["transcript"]
        analysis = result["analysis"]

        job.transcript_json = transcript
        job.analysis_json = analysis
        job.progress_step = "planning"
        db.commit()

        # Step 2: Generate edit plan
        logger.info(f"[{job_id}] Planning edit...")
        edit_plan = plan_edit(
            transcript=transcript,
            analysis=analysis,
            prompt=job.prompt,
            preset_id=job.preset_id,
            video_duration=job.duration_sec,
        )

        job.edit_plan_json = edit_plan.model_dump()
        job.progress_step = "fetching_broll"
        db.commit()

        # Step 3: Fetch b-roll assets
        if edit_plan.broll.enabled and edit_plan.broll.inserts:
            logger.info(f"[{job_id}] Fetching b-roll...")
            inserts_data = [i.model_dump() for i in edit_plan.broll.inserts]
            updated_inserts = fetch_broll_for_plan(inserts_data)
            # Update plan with asset paths
            plan_data = edit_plan.model_dump()
            plan_data["broll"]["inserts"] = updated_inserts
            edit_plan = EditPlan.model_validate(plan_data)
            job.edit_plan_json = edit_plan.model_dump()
            db.commit()

        # Step 4: Render
        job.progress_step = "rendering"
        db.commit()

        logger.info(f"[{job_id}] Rendering...")
        output_key = f"outputs/{job_id}/v1.mp4"
        output_path = storage.get_path(output_key)

        compile_render(
            edit_plan=edit_plan,
            source_video=source_path,
            transcript=transcript,
            output_path=output_path,
        )

        # Store output
        output_url = storage.get_url(output_key)

        job.status = "done"
        job.progress_step = "done"
        job.output_file_path = output_key
        job.output_url = output_url
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"[{job_id}] Job complete: {output_url}")

    except Exception as e:
        logger.error(f"[{job_id}] Job failed: {e}")
        logger.error(traceback.format_exc())
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = "error"
                job.progress_step = "error"
                job.error = str(e)
                job.error_trace = traceback.format_exc()
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def process_revision(job_id: str, revision_id: str):
    """Process a revision: generate patch → apply → re-render."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        revision = db.query(Revision).filter(Revision.id == revision_id).first()
        if not job or not revision:
            logger.error(f"Job or revision not found: {job_id}/{revision_id}")
            return

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

        logger.info(f"[{job_id}/r{revision.revision_number}] Revision complete")

    except Exception as e:
        logger.error(f"[{job_id}/{revision_id}] Revision failed: {e}")
        logger.error(traceback.format_exc())
        try:
            revision = db.query(Revision).filter(Revision.id == revision_id).first()
            if revision:
                revision.status = "error"
                revision.error = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
