# Compose - Architecture

## Overview

Compose is a prompt-to-edited-video web application for short-form content. Users upload a talking-head clip (60-120s), type a prompt, choose a style preset, and the system outputs a finished 9:16 MP4 with smart cuts, captions, music, and stock b-roll.

## System Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐
│  Next.js UI │────▶│  FastAPI API  │────▶│  Postgres  │
│  (port 3000)│     │  (port 8000)  │     │  (jobs DB) │
└─────────────┘     └──────┬───────┘     └───────────┘
                           │
                    ┌──────▼───────┐     ┌───────────┐
                    │  RQ Worker   │────▶│   Redis    │
                    │  (background)│     │  (queue)   │
                    └──────┬───────┘     └───────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Whisper  │ │  Claude  │ │  FFmpeg  │
        │ (local)  │ │  Haiku   │ │ renderer │
        └──────────┘ └──────────┘ └──────────┘
```

## Job Lifecycle

1. **QUEUED**: Job created, file uploaded to storage
2. **PROCESSING**:
   - `transcribing`: faster-whisper generates word-level transcript + audio energy analysis
   - `planning`: Claude Haiku generates EditPlan JSON from transcript + prompt + preset
   - `fetching_broll`: Pexels API searches and downloads b-roll clips
   - `rendering`: FFmpeg pipeline executes (cut, zoom, caption, music, encode)
3. **DONE**: Output MP4 available for download
4. **ERROR**: Failure captured with error trace in DB

## Modules

### Transcribe (`services/transcribe.py`)
- Uses `faster-whisper` with configurable model size (default: `base`)
- Outputs word-level timestamps for caption alignment
- Computes audio energy curve for silence/emphasis detection
- Falls back to demo transcript when Whisper is unavailable

### Planner (`services/planner.py`)
- Sends compressed transcript + analysis + prompt + preset config to Claude Haiku
- Receives strictly validated EditPlan JSON
- Auto-retries once on invalid JSON with "fix JSON" prompt
- Falls back to rule-based planner in demo mode (no API key)

### Pexels (`services/pexels.py`)
- Searches Pexels for portrait-oriented stock video
- Downloads and caches by URL hash (avoids re-downloads)
- Processes clips to 9:16 via FFmpeg crop
- Caps at 6 clips per job; gracefully degrades on failure

### Render Compiler (`services/render_compiler.py`)
- Converts EditPlan → deterministic FFmpeg commands
- Pipeline: trim segments → concat → punch-in zoom → burn ASS captions → mix music → final encode
- ASS subtitle generation with timeline mapping (original → final timestamps)
- Output: H.264 CRF 21, AAC 128k, 1080x1920, faststart

### Patcher (`services/patcher.py`)
- Chat-based edits via Claude Haiku (or rule-based fallback)
- Generates minimal PlanPatch JSON (only changes what's needed)
- Applies patch to previous EditPlan → creates new revision
- Re-renders only the changed plan

### Storage (`services/storage.py`)
- Abstraction layer: local disk or Cloudflare R2 (S3-compatible)
- Auto-falls back to local if R2 credentials missing
- Handles originals, b-roll cache, and output files

## Data Models

### EditPlan (Pydantic)
- `main_cuts`: non-overlapping time ranges from original video
- `punch_ins`: zoom segments with scale 1.0-1.5
- `broll`: cutaway fullscreen inserts with Pexels queries
- `captions`: ASS style configuration
- `music`: built-in track selection + volume
- `rationale`: planner's explanation

### PlanPatch
- Minimal diff applied to EditPlan for chat-based edits
- Supports: captions, music, broll, punch_ins, output, timing_adjustments
- Rule: only change what's explicitly requested

## Style Presets

5 built-in presets control planner + renderer behavior:
1. **Snappy Creator**: fast cuts, frequent punch-ins, energetic
2. **Cinematic Doc**: slower, subtle zooms, fewer cuts
3. **Podcast Clipper**: clean captions, strong silence removal
4. **Luxury Real Estate**: smooth pacing, elegant
5. **Study/Explainer**: structured, minimal effects

## Scaling Plan

### Current (MVP)
- Single worker queue processing jobs sequentially
- CPU-only FFmpeg rendering
- Local storage in dev

### Future
- **More workers**: Scale horizontally with multiple RQ workers
- **GPU rendering**: NVENC for faster H.264 encoding
- **Distributed storage**: Full R2/S3 integration for production
- **Job priority**: Separate queues for initial render vs. revisions
- **Caching**: Cache transcriptions and b-roll per content hash
- **Webhook notifications**: Push job status to client via WebSocket
