"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
MUSIC_DIR = ASSETS_DIR / "music"

# Storage
STORAGE_MODE = os.getenv("STORAGE_MODE", "local")
LOCAL_STORAGE_PATH = Path(os.getenv("LOCAL_STORAGE_PATH", "/data/storage"))

# R2 / S3
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "compose-media")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "")

# CORS
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]

# APIs
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://compose:compose@localhost:5432/compose"
)

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Whisper
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# Limits
MAX_INPUT_DURATION_SEC = 240
MAX_UPLOAD_SIZE_MB = 500
MAX_BROLL_CLIPS = 6
MAX_RENDER_TIMEOUT_SEC = 480  # 8 minutes

# Demo mode: auto-detect based on API keys
DEMO_MODE = not ANTHROPIC_API_KEY


def is_r2_available() -> bool:
    return (
        STORAGE_MODE == "r2"
        and bool(R2_ACCESS_KEY_ID)
        and bool(R2_SECRET_ACCESS_KEY)
        and bool(R2_ENDPOINT_URL)
    )


def is_pexels_available() -> bool:
    return bool(PEXELS_API_KEY)
