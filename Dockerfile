FROM python:3.12-slim

# System deps: ffmpeg, fonts, chromium + runtime libs
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
    ca-certificates \
    gnupg \
    chromium \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcb1 \
    libx11-6 \
  && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV PUPPETEER_SKIP_DOWNLOAD=true

# Install modern Node.js (includes npm+npx)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get update && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

# (Optional) sanity check during build
RUN node -v && npm -v && npx -v

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

# Install Remotion workspace deps (required for npx/remotion renders)
WORKDIR /app/apps/remotion
RUN npm install --omit=dev
WORKDIR /app

# Create local storage directory
RUN mkdir -p /data/storage

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE ${PORT}

# Exec form — apps/api/main.py __main__ block reads $PORT at runtime
CMD ["python", "-m", "apps.api.main"]
