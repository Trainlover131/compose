"""Job API routes."""

import json
import logging
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from apps.api.config import MAX_INPUT_DURATION_SEC, MAX_UPLOAD_SIZE_MB, REDIS_URL
from apps.api.models.database import Job, Revision, get_db
from apps.api.models.schemas import (
    EditRequest,
    EditResponse,
    JobCreateResponse,
    JobResponse,
    RevisionResponse,
    RevisionSummary,
)
from apps.api.services.storage import storage
from apps.api.worker import process_job, process_revision

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Watchdog: jobs processing longer than this are marked as timed out
JOB_TIMEOUT_MINUTES = 10


def get_queue():
    """Try to connect to Redis and return a RQ queue. Returns None if unavailable."""
    try:
        from redis import Redis
        from rq import Queue

        redis_conn = Redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
        redis_conn.ping()
        return Queue("compose-jobs", connection=redis_conn)
    except Exception as e:
        logger.warning(f"Redis not available, will process synchronously: {e}")
        return None


def _run_in_thread(target, args, job_id: str):
    """Run a pipeline function in a daemon thread with top-level exception safety.

    If the thread's target raises, we catch it here and mark the job as error,
    preventing jobs from being stuck in 'processing' forever.
    """

    def _safe_wrapper():
        try:
            target(*args)
        except Exception as e:
            logger.error(f"[{job_id}] Thread crashed: {e}")
            # The worker's own except block should handle this,
            # but as a last resort, try to mark the job as error.
            try:
                from apps.api.models.database import SessionLocal

                db = SessionLocal()
                try:
                    job = db.query(Job).filter(Job.id == job_id).first()
                    if job and job.status not in ("done", "error"):
                        job.status = "error"
                        job.progress_step = "error"
                        job.error = f"Worker crashed: {str(e)[:500]}"
                        job.updated_at = datetime.now(timezone.utc)
                        db.commit()
                finally:
                    db.close()
            except Exception:
                pass

    t = threading.Thread(target=_safe_wrapper, daemon=True)
    t.start()
    logger.info(f"Job {job_id} processing in background thread")


def _check_watchdog(job: Job, db: Session):
    """If a job has been processing for too long, mark it as timed out.

    Called from the GET /api/jobs/{id} endpoint so stale jobs are detected
    on the next poll without requiring a separate watchdog process.
    """
    if job.status not in ("queued", "processing"):
        return

    if not job.updated_at:
        return

    now = datetime.now(timezone.utc)
    # Ensure updated_at is timezone-aware for comparison
    updated = job.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)

    age = now - updated
    if age > timedelta(minutes=JOB_TIMEOUT_MINUTES):
        logger.warning(
            f"[{job.id}] Watchdog timeout: job stuck in '{job.status}/{job.progress_step}' "
            f"for {age.total_seconds():.0f}s, marking as error"
        )
        job.status = "error"
        job.progress_step = "error"
        job.error = (
            f"Timed out (server): job was stuck in '{job.progress_step}' "
            f"for over {JOB_TIMEOUT_MINUTES} minutes. This usually means the worker "
            f"crashed or the server restarted. Please try again."
        )
        job.updated_at = now
        db.commit()


@router.post("/jobs", response_model=JobCreateResponse)
async def create_job(request: Request, db: Session = Depends(get_db)):
    """Create a new editing job.

    Accepts two modes:
      - **Multipart** (Content-Type: multipart/form-data): upload file + form fields.
        Used for small files or when R2 is not configured.
      - **JSON** (Content-Type: application/json): { file_key, prompt, preset_id, duration_sec }.
        Used after the browser has uploaded directly to R2 via a presigned URL.
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        return await _create_job_from_key(request, db)
    return await _create_job_from_upload(request, db)


async def _create_job_from_upload(request: Request, db: Session) -> JobCreateResponse:
    """Original multipart upload path — API receives the file bytes."""
    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "filename"):
        raise HTTPException(400, "No file provided")

    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".mov", ".webm", ".mkv"}:
        raise HTTPException(400, f"Unsupported file type: {ext}. Use MP4 or MOV.")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(400, f"File too large: {size_mb:.1f}MB (max {MAX_UPLOAD_SIZE_MB}MB)")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    duration = _get_video_duration(tmp_path)
    if duration > MAX_INPUT_DURATION_SEC:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(
            400,
            f"Video too long: {duration:.0f}s (max {MAX_INPUT_DURATION_SEC}s)",
        )

    job_id = str(uuid.uuid4())
    file_key = f"originals/{job_id}/{file.filename}"
    storage.save_file(tmp_path, file_key)
    Path(tmp_path).unlink(missing_ok=True)

    prompt = form.get("prompt", "Make this into an engaging short-form video")
    preset_id = form.get("preset_id", "snappy-creator")
    if isinstance(prompt, bytes):
        prompt = prompt.decode()
    if isinstance(preset_id, bytes):
        preset_id = preset_id.decode()

    return _persist_and_enqueue(db, job_id, file_key, file.filename, prompt, preset_id, duration)


async def _create_job_from_key(request: Request, db: Session) -> JobCreateResponse:
    """JSON mode — file was already uploaded to R2 via presigned URL."""
    body = await request.json()

    file_key = body.get("file_key")
    if not file_key or not isinstance(file_key, str):
        raise HTTPException(400, "file_key is required")

    # Derive filename from the key (originals/{uuid}/{filename})
    original_filename = file_key.rsplit("/", 1)[-1] if "/" in file_key else file_key

    ext = Path(original_filename).suffix.lower()
    if ext not in {".mp4", ".mov", ".webm", ".mkv"}:
        raise HTTPException(400, f"Unsupported file type: {ext}. Use MP4 or MOV.")

    prompt = body.get("prompt", "Make this into an engaging short-form video")
    preset_id = body.get("preset_id", "snappy-creator")
    duration_sec = float(body.get("duration_sec", 0))

    job_id = str(uuid.uuid4())
    logger.info(f"Job {job_id} created from presigned upload: key={file_key}")

    return _persist_and_enqueue(db, job_id, file_key, original_filename, prompt, preset_id, duration_sec)


def _persist_and_enqueue(
    db: Session,
    job_id: str,
    file_key: str,
    original_filename: str,
    prompt: str,
    preset_id: str,
    duration_sec: float,
) -> JobCreateResponse:
    """Create the Job row in the DB and enqueue or thread the worker."""
    job = Job(
        id=job_id,
        status="queued",
        progress_step="uploading",
        prompt=prompt,
        preset_id=preset_id,
        original_file_path=file_key,
        original_filename=original_filename,
        duration_sec=duration_sec,
    )
    db.add(job)
    db.commit()

    queue = get_queue()
    if queue:
        queue.enqueue(process_job, job_id, job_timeout=600)
        logger.info(f"Job {job_id} enqueued to Redis")
    else:
        _run_in_thread(process_job, (job_id,), job_id)

    return JobCreateResponse(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get job status and details."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    # Watchdog: detect stale jobs on every poll
    _check_watchdog(job, db)

    revisions = []
    for rev in job.revisions:
        revisions.append(
            RevisionSummary(
                revision_id=rev.id,
                revision_number=rev.revision_number,
                status=rev.status,
                output_url=rev.output_url or None,
                instruction=rev.instruction,
            )
        )

    return JobResponse(
        job_id=job.id,
        status=job.status,
        progress_step=job.progress_step,
        error=job.error or None,
        output_url=job.output_url or None,
        edit_plan=job.edit_plan_json if job.edit_plan_json else None,
        revisions=revisions,
        created_at=job.created_at.isoformat() if job.created_at else None,
        updated_at=job.updated_at.isoformat() if job.updated_at else None,
    )


@router.post("/jobs/{job_id}/edits", response_model=EditResponse)
async def create_edit(
    job_id: str,
    request: EditRequest,
    db: Session = Depends(get_db),
):
    """Request a chat-based edit on an existing job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "done":
        raise HTTPException(400, "Job must be completed before editing")

    # Determine revision number
    existing = db.query(Revision).filter(Revision.job_id == job_id).count()
    revision_number = existing + 1

    revision = Revision(
        id=str(uuid.uuid4()),
        job_id=job_id,
        revision_number=revision_number,
        instruction=request.instruction,
        status="queued",
    )
    db.add(revision)
    db.commit()

    # Enqueue revision job
    queue = get_queue()
    if queue:
        queue.enqueue(process_revision, job_id, revision.id, job_timeout=600)
    else:
        _run_in_thread(process_revision, (job_id, revision.id), job_id)

    return EditResponse(revision_id=revision.id, status="queued")


@router.get("/jobs/{job_id}/edits/{revision_id}", response_model=RevisionResponse)
async def get_revision(
    job_id: str,
    revision_id: str,
    db: Session = Depends(get_db),
):
    """Get revision status and output."""
    revision = (
        db.query(Revision)
        .filter(Revision.id == revision_id, Revision.job_id == job_id)
        .first()
    )
    if not revision:
        raise HTTPException(404, "Revision not found")

    return RevisionResponse(
        revision_id=revision.id,
        revision_number=revision.revision_number,
        status=revision.status,
        output_url=revision.output_url or None,
    )


def _get_video_duration(path: str) -> float:
    """Get video duration using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
    return 0.0
