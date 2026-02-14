# Compose

**Prompt-to-edited-video for short-form content.**

Upload a talking-head clip, describe the vibe, and get a finished 9:16 MP4 with smart cuts, captions, music, and stock b-roll.

## Quick Start

### Prerequisites

- Docker & Docker Compose
- (Optional) API keys for full features

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env with your API keys (optional for demo mode)
```

### 2. Run with Docker Compose

```bash
make dev
# or: docker compose -f infra/docker-compose.yml up --build
```

- **Web UI**: http://localhost:3000
- **API**: http://localhost:8000
- **API docs**: http://localhost:8000/docs

### 3. Run a test job

1. Open http://localhost:3000
2. Upload an MP4 video (60-120 seconds)
3. Type a prompt like "Make this punchy and engaging"
4. Select a style preset
5. Click **Generate**
6. Wait for processing (Transcribing → Planning → Rendering)
7. Download the result

## Demo Mode

Runs without API keys with limited features:

- **No Anthropic key**: Uses rule-based planner (silence trimming, emphasis zoom)
- **No Pexels key**: Skips b-roll inserts
- Music from built-in pack still works
- Captions still generated from transcript

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | No* | Claude Haiku for AI edit planning |
| `PEXELS_API_KEY` | No* | Pexels stock video for b-roll |
| `STORAGE_MODE` | No | `local` (default) or `r2` |
| `R2_ACCESS_KEY_ID` | If R2 | Cloudflare R2 access key |
| `R2_SECRET_ACCESS_KEY` | If R2 | Cloudflare R2 secret key |
| `R2_ENDPOINT_URL` | If R2 | Cloudflare R2 endpoint |
| `R2_BUCKET_NAME` | If R2 | R2 bucket name |
| `WHISPER_MODEL` | No | Whisper model size: `base` (default), `small`, `medium` |
| `DATABASE_URL` | No | PostgreSQL connection string |
| `REDIS_URL` | No | Redis connection string |

*Demo mode activates automatically when keys are missing.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs` | Upload video + create job |
| `GET` | `/api/jobs/{id}` | Get job status |
| `POST` | `/api/jobs/{id}/edits` | Request chat-based edit |
| `GET` | `/api/jobs/{id}/edits/{rev_id}` | Get revision status |
| `GET` | `/api/presets` | List style presets |
| `GET` | `/api/admin/jobs` | Admin: list all jobs |
| `GET` | `/api/files/{path}` | Serve local storage files |

## Tech Stack

- **Frontend**: Next.js 14, TypeScript, TailwindCSS
- **Backend**: FastAPI (Python), PostgreSQL, Redis + RQ
- **AI**: Claude Haiku (Anthropic), faster-whisper (local)
- **Media**: FFmpeg (CPU), ASS subtitles
- **Storage**: Cloudflare R2 / local disk
- **Assets**: Pexels API (b-roll), built-in music pack

## Project Structure

```
compose/
├── apps/
│   ├── web/                 # Next.js frontend
│   │   ├── src/
│   │   │   ├── app/         # App Router pages
│   │   │   ├── components/  # UI components
│   │   │   ├── hooks/       # React hooks
│   │   │   └── lib/         # API client
│   │   └── Dockerfile
│   └── api/                 # FastAPI backend
│       ├── models/          # DB models + Pydantic schemas
│       ├── routes/          # API routes
│       ├── services/        # Business logic
│       │   ├── transcribe.py
│       │   ├── planner.py
│       │   ├── pexels.py
│       │   ├── patcher.py
│       │   ├── render_compiler.py
│       │   └── storage.py
│       ├── worker.py        # Background job processor
│       ├── tests/           # Unit tests
│       └── Dockerfile
├── assets/
│   └── music/              # Built-in royalty-free tracks
├── infra/
│   └── docker-compose.yml
├── docs/
│   └── ARCHITECTURE.md
├── Makefile
└── .env.example
```

## Make Commands

```bash
make dev     # Build and run all services
make build   # Build Docker images
make up      # Start services (detached)
make down    # Stop services
make logs    # View logs
make test    # Run unit tests
make fmt     # Format code
make lint    # Lint code
make clean   # Remove containers and volumes
```

## Running Tests

```bash
# With Docker
make test

# Local (requires Python deps)
cd apps/api && pip install -r requirements.txt && pytest tests/ -v
```

## Deploy to Railway

1. Create a new Railway project
2. Add services: PostgreSQL, Redis
3. Add the API service from `apps/api/`
4. Add the Web service from `apps/web/`
5. Set environment variables (API keys, DATABASE_URL, REDIS_URL)
6. Deploy

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for scaling guidance.

## Music Pack

The built-in music pack at `assets/music/` contains placeholder files. Replace them with actual royalty-free tracks:

| Track ID | Mood | Use Case |
|----------|------|----------|
| `upbeat-energy` | Energetic, fast | Snappy Creator |
| `cinematic-ambient` | Calm, atmospheric | Cinematic Doc |
| `clean-podcast` | Minimal, neutral | Podcast Clipper |
| `luxury-smooth` | Elegant, smooth | Luxury Real Estate |
| `study-lofi` | Focus, lo-fi | Study/Explainer |

Track format: MP3 or WAV, any length (auto-looped/trimmed to match video).
