FROM python:3.12-slim

# Install FFmpeg and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libass-dev \
    fonts-liberation \
    frei0r-plugins \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application code
COPY apps/ /app/apps/
COPY assets/ /app/assets/

# Create storage directory
RUN mkdir -p /data/storage

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE ${PORT}

# Shell form so $PORT is expanded at runtime
CMD uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT}
