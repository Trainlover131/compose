"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from apps.api.config import ALLOWED_ORIGINS, LOCAL_STORAGE_PATH
from apps.api.routes.jobs import router as jobs_router
from apps.api.routes.presets import router as presets_router

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(module)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations on startup."""
    from apps.api.models.database import init_db

    logger.info("Initializing database tables...")
    init_db()
    logger.info("Database ready.")
    yield


app = FastAPI(
    title="Compose Video Editor API",
    version="0.1.0",
    description="Prompt-to-edited-video API for short-form content",
    lifespan=lifespan,
)

# CORS — reads ALLOWED_ORIGINS env var (comma-separated), defaults to ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(jobs_router)
app.include_router(presets_router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "compose-api", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/files/{path:path}")
async def serve_file(path: str):
    """Serve files from local storage."""
    file_path = LOCAL_STORAGE_PATH / path
    if not file_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(
        str(file_path),
        media_type="video/mp4" if path.endswith(".mp4") else "application/octet-stream",
    )


@app.get("/api/admin/jobs")
async def admin_jobs():
    """Simple admin endpoint to view all jobs."""
    from apps.api.models.database import SessionLocal, Job

    db = SessionLocal()
    try:
        jobs = db.query(Job).order_by(Job.created_at.desc()).limit(50).all()
        return [
            {
                "id": j.id,
                "status": j.status,
                "progress_step": j.progress_step,
                "preset_id": j.preset_id,
                "duration_sec": j.duration_sec,
                "error": j.error[:200] if j.error else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ]
    finally:
        db.close()
