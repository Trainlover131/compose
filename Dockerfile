FROM python:3.12-slim

# Install FFmpeg and system dependencies for rendering + ASS subtitles
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libass-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application code + assets
COPY apps/ /app/apps/
COPY assets/ /app/assets/

# Create local storage directory
RUN mkdir -p /data/storage

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Railway injects PORT; default to 8000 for local dev
ENV PORT=8000

EXPOSE ${PORT}

# Railway health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Use shell form so $PORT is expanded at runtime
CMD uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT}
