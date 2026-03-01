FROM python:3.12-slim

# Install FFmpeg + ASS deps + faster-whisper native runtime deps
# Keep minimal system fonts only (dejavu, liberation, noto-core, noto-emoji)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libass-dev \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-noto-core \
    fonts-noto-color-emoji \
    curl \
    libgomp1 \
    libstdc++6 \
    frei0r-plugins \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Custom fonts from assets/fonts/ (Playfair Display, etc.)
RUN mkdir -p /usr/local/share/fonts/custom
COPY assets/fonts/ /usr/local/share/fonts/custom/
RUN fc-cache -f -v

WORKDIR /app

# Install Python dependencies first (layer caching)
# --extra-index-url in requirements.txt pulls CPU-only torch wheels
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Fail fast during build if key deps can't import
RUN python -c "from faster_whisper import WhisperModel; print('faster-whisper import OK')"
RUN python -c "import open_clip; print('open_clip import OK')"

# Copy application code + assets
COPY apps/ /app/apps/
COPY assets/ /app/assets/

# Create local storage directory
RUN mkdir -p /data/storage

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE ${PORT}

# Exec form — apps/api/main.py __main__ block reads $PORT at runtime
CMD ["python", "-m", "apps.api.main"]
