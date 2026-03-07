# SupaCut Foundation Audit: Compose vs KimuVideo

**Date**: 2026-03-07
**Auditor**: Claude (automated code audit)
**Scope**: Determine which repo is the better foundation for SupaCut, an AI-native video editor.

---

## 1. What Each Repo Actually Does (Code-Verified)

### Compose (`Trainlover131/compose`)

**Compose is a prompt-to-edited-video pipeline for short-form content.** You upload a talking-head clip, type a prompt, and it outputs a finished 9:16 MP4 with smart cuts, captions, music, and stock b-roll.

**Real implemented functionality (code-verified):**
- Full transcription pipeline via faster-whisper with word-level timestamps (`apps/api/services/transcribe.py:94-151`)
- Audio energy analysis: silence detection, emphasis moments, energy curve (`apps/api/services/transcribe.py:14-91`)
- AI edit planning via Claude Haiku — generates `EditPlan` JSON with main_cuts, punch_ins, captions, music, b-roll (`apps/api/services/planner.py`)
- Two-phase LLM flow: Pass 1 (Claude Haiku for cuts/captions/music) + VisualDirector (Gemini multimodal for overlays/b-roll) (`apps/api/services/planner.py:1-7`)
- B-roll fetching from Pexels API with CLIP-based ranking (`apps/api/services/pexels.py:108-158`)
- FFmpeg render compiler — deterministic FFmpeg command generation from EditPlan (`apps/api/services/render_compiler.py`)
- Multiple b-roll film look presets: DEFAULT_FILM, CLEAN, TV, HEAVY, HALFTONE (`apps/api/services/render_compiler.py:41-134`)
- Custom Haiku-generated color grades for b-roll (`apps/api/services/render_compiler.py:218-249`)
- ASS subtitle generation for captions with karaoke, pause emphasis, invert styles (`apps/api/models/schemas.py:125-158`)
- Chat-based revision system — patch edits via natural language (`apps/api/services/patcher.py:40-91`)
- Remotion motion graphics inserts: KPI counter, line chart, quote highlight, steps list, profile card, code card, custom scene (`apps/remotion/src/Root.tsx`)
- Remotion insert validation and rendering to MP4 (`apps/api/services/remotion_validator.py`, `apps/api/services/remotion_renderer.py`)
- Overlay QC with checkerboard detection (`apps/api/services/overlay_qc.py`)
- Image overlay system with Nanobanana AI and Logo.dev integration (`apps/api/services/planner.py`, `apps/api/integrations/logo_dev.py`)
- Storage abstraction: local disk or Cloudflare R2 (`apps/api/services/storage.py`)
- PostgreSQL database with SQLAlchemy ORM (`apps/api/models/database.py`)
- Redis + RQ job queue (falls back to in-thread processing) (`apps/api/routes/jobs.py:35-46`)
- Background job processing pipeline: transcribe → plan → fetch b-roll → render Remotion → FFmpeg compile (`apps/api/worker.py:152-283`)
- Revision pipeline: patch → re-fetch b-roll → re-render (`apps/api/worker.py:286-391`)
- Presigned upload support for direct-to-R2 uploads (`apps/api/routes/uploads.py`)
- Style presets system (`apps/api/models/presets.py`)
- Job watchdog/timeout system (`apps/api/routes/jobs.py:85-117`)
- Railway deployment configs (`railway.toml`, `railway.worker.toml`, `Dockerfile`)
- Docker Compose infra (`infra/docker-compose.yml`)
- Next.js frontend with upload, preset selector, progress stepper, preview, chat edit, revision list (`apps/web/src/`)

**README claims that match code**: All major claims verified. Demo mode, environment variables, API endpoints all match actual implementation.

### KimuVideo (`Trainlover131/kimuvideo`)

**KimuVideo is a browser-based multi-track video editor (NLE) with Remotion-powered rendering.** It's a traditional timeline editor with drag-and-drop, multi-track editing, transitions, text overlays, and an AI chat assistant.

**Real implemented functionality (code-verified):**
- Multi-track timeline with drag-and-drop (`app/hooks/useTimeline.ts` — ~1800 lines)
- Timeline state management: tracks, scrubbers, transitions, undo/redo (`app/hooks/useTimeline.ts`, `app/lib/timeline.store.ts`)
- Scrubber types: video, image, audio, text, grouped_scrubber (`app/components/timeline/types.ts:2-5`)
- Video trim support (`trimBefore`, `trimAfter` in frames) (`app/components/timeline/types.ts:65-66`)
- Transition system: fade, wipe, slide, flip, iris with spring/linear timing (`app/video-compositions/VideoPlayer.tsx:195-220`)
- Real-time preview via Remotion Player (`app/video-compositions/VideoPlayer.tsx:469-544`)
- Server-side rendering via Remotion `renderMedia` (`app/videorender/videorender.ts:257-333`)
- Media upload (single + bulk) via Express/multer to local disk (`app/videorender/videorender.ts:102-156`)
- Media file management: list, clone, delete (`app/videorender/videorender.ts:74-241`)
- Text editor with font, color, size, alignment, weight, template (normal/glassy) (`app/components/media/TextEditor.tsx`)
- AI chat assistant "Ask Kimu" powered by Gemini 2.5 Flash (`backend/main.py:41-80`)
- LLM tool functions: add scrubber, move scrubber, delete scrubbers, resize, zoom, play/pause, text editing, etc. (`app/utils/llm-handler.ts` — 720 lines)
- Google OAuth authentication via Better Auth (`app/lib/auth.server.ts`)
- PostgreSQL project storage (`app/lib/projects.repo.ts`)
- Project state persistence to JSON files (`app/lib/timeline.store.ts`)
- Docker Compose with nginx, frontend, backend, FastAPI services (`docker-compose.yml`)
- Dimension controls for composition size (`app/components/timeline/DimensionControls.tsx`)
- Media bin with upload progress tracking (`app/components/timeline/MediaBin.tsx`)
- Zoom controls (0.25x–4x) (`app/hooks/useTimeline.ts`)
- Ruler/scrubber position tracking (`app/hooks/useRuler.ts`)

**README claims vs reality:**
- "Advanced Multi-Track Editing" — **REAL**: Multi-track timeline with transitions is fully implemented
- "Real-Time Preview" — **REAL**: Remotion Player provides real-time preview
- "Fast Export" — **REAL**: Server-side Remotion rendering implemented
- "Vibe AI Assistant" — **PARTIALLY REAL**: Gemini chat is implemented but limited to basic timeline operations (add/move/delete scrubbers). No AI-driven creative editing.
- "Smart Media Library" — **MOSTLY UI**: Basic media bin exists, no tagging/sentiment/smart features
- "Cloud-Synced Projects" — **PARTIALLY REAL**: Projects saved to Postgres, timeline state to JSON files, but no real-time sync

---

## 2. Architecture Comparison

| Layer | Compose | KimuVideo |
|-------|---------|-----------|
| **Frontend** | Next.js 14, TypeScript, TailwindCSS | React Router v7, TypeScript, TailwindCSS, shadcn/ui |
| **Backend** | FastAPI (Python 3.12), PostgreSQL, Redis+RQ | Express.js (Node/TS) + FastAPI (Python), PostgreSQL |
| **Render Pipeline** | FFmpeg (CPU) via subprocess + Remotion CLI for motion graphics | Remotion `renderMedia` (server-side, Node.js) |
| **AI Service** | Claude Haiku (edit planning, patching, color grades) + Gemini (visual director) | Gemini 2.5 Flash (chat-based timeline ops) |
| **Auth** | None | Google OAuth via Better Auth |
| **DB** | PostgreSQL (SQLAlchemy ORM) | PostgreSQL (raw `pg` Pool) |
| **Storage** | Local disk / Cloudflare R2 (S3-compatible) | Local disk (`out/` directory) + JSON files |
| **Deployment** | Railway (Dockerfile) + Vercel (frontend) | Docker Compose (nginx + frontend + backend + FastAPI) |

---

## 3. Full Flow Trace

### Compose Flow

1. **Media Upload**: `POST /api/jobs` → multipart file or JSON with presigned R2 key → saved to `originals/{job_id}/{filename}` via storage abstraction (`apps/api/routes/jobs.py:120-238`)
2. **Pipeline**: Job queued to Redis/RQ (or in-thread) → `process_job()` in `apps/api/worker.py:152`
3. **Transcription**: faster-whisper with word-level timestamps + audio energy analysis → stored in `job.transcript_json` and `job.analysis_json`
4. **AI Planning**: Claude Haiku generates `EditPlan` JSON (main_cuts, punch_ins, captions, music, b-roll queries) from transcript + energy + prompt + preset → stored in `job.edit_plan_json`
5. **Visual Director**: Gemini multimodal plans overlays + b-roll in original timeline, then maps to final timeline
6. **B-roll Fetch**: Pexels API search → CLIP ranking → download to `broll_cache/`
7. **Remotion Inserts**: Validate → render via Remotion CLI → MP4 files
8. **FFmpeg Render**: `compile_render()` builds deterministic FFmpeg filtergraph: main cuts + punch-in zooms + b-roll compositing + caption ASS overlay + music mix → final MP4
9. **Output**: Saved to `outputs/{job_id}/v1.mp4` via storage, URL returned to frontend
10. **Revision**: `POST /api/jobs/{id}/edits` → Claude Haiku generates `PlanPatch` → apply to EditPlan → re-render

### KimuVideo Flow

1. **Media Upload**: `POST /upload` → multer saves to `out/` directory → returns URL (`app/videorender/videorender.ts:102-127`)
2. **Timeline State**: React state in `useTimeline` hook → tracks/scrubbers/transitions managed client-side → persisted to JSON files via server API
3. **Preview**: `<Player>` from `@remotion/player` renders `TimelineComposition` in real-time browser → scrubbers rendered as `<Video>`, `<Img>`, `<Audio>`, text `<div>`s with `<Sequence>` and `<TransitionSeries>` (`app/video-compositions/VideoPlayer.tsx:49-467`)
4. **Render/Export**: `POST /render` → server bundles Remotion entry → `renderMedia()` with H.264 codec → streams MP4 back → browser downloads (`app/videorender/videorender.ts:257-333`)
5. **AI Assistant**: User types in ChatBox → `POST /ai` to FastAPI backend → Gemini 2.5 Flash returns function call → frontend executes LLM handler function (add/move/delete scrubber, etc.) (`app/components/chat/ChatBox.tsx:194-361`, `backend/main.py:41-80`)

---

## 4. What's Missing for SupaCut

| Feature | Compose | KimuVideo | Gap for SupaCut |
|---------|---------|-----------|-----------------|
| **Transcript-based editing** | **IMPLEMENTED**: Word-level timestamps, silence detection, emphasis moments used for cut planning | **MISSING**: No transcription at all | Compose has this; KimuVideo needs it built from scratch |
| **AI edit planning** | **IMPLEMENTED**: Claude Haiku generates full EditPlan from transcript+prompt | **BASIC**: Gemini does simple timeline ops (add/move/delete) | Compose is far ahead; KimuVideo's AI is a chat toy |
| **Captions** | **IMPLEMENTED**: ASS subtitles with word-level karaoke, pause emphasis, invert blend, multiple styles | **MISSING**: No caption system | Compose has production captions; KimuVideo has nothing |
| **B-roll insertion** | **IMPLEMENTED**: Pexels search + CLIP ranking + download + FFmpeg compositing with film looks | **MISSING**: No b-roll concept | Compose has full pipeline; KimuVideo has nothing |
| **Motion graphics** | **IMPLEMENTED**: 8 Remotion templates (KPI, charts, quotes, code, etc.) rendered to MP4 and composited | **BASIC**: Remotion used for timeline rendering, but no motion graphics templates | Compose has a template system; KimuVideo uses Remotion differently |
| **Revision engine** | **IMPLEMENTED**: Chat-based PlanPatch system with re-render | **MISSING**: No revision concept | Compose has it |
| **Production rendering** | **IMPLEMENTED**: FFmpeg with deterministic filtergraphs, configurable timeouts, error handling | **BASIC**: Remotion renderMedia works but single-output, limited config | Compose is production-ready; KimuVideo is prototype-grade |
| **Multi-track timeline UI** | **MISSING**: No timeline UI — wizard/upload flow only | **IMPLEMENTED**: Full multi-track with drag-drop, transitions, trim, zoom, undo/redo | KimuVideo is far ahead; Compose has no NLE |
| **Real-time preview** | **MISSING**: No preview — only final rendered output | **IMPLEMENTED**: Remotion Player with real-time playback | KimuVideo has this |
| **Auth** | **MISSING** | **IMPLEMENTED**: Google OAuth, sessions, per-user projects | KimuVideo has this |
| **Transitions** | **MISSING** | **IMPLEMENTED**: fade, wipe, slide, flip, iris | KimuVideo has this |
| **Text overlays (manual)** | **MISSING** from frontend (only AI-driven) | **IMPLEMENTED**: Full text editor with styling | KimuVideo has this |

---

## 5. Verdict: Which Repo is More Advanced for SupaCut?

### COMPOSE IS SIGNIFICANTLY MORE ADVANCED FOR SUPACUT.

**Reasoning:**
- SupaCut's core value proposition is **AI-native editing** (transcript-based, AI planning, auto captions, auto b-roll). Compose has **all of this implemented and working**.
- KimuVideo is a **traditional NLE** — great for manual editing but has zero AI editing pipeline, zero transcription, zero auto-captioning, zero b-roll automation.
- Building Compose's AI pipeline from scratch in KimuVideo would take months. Adding a timeline UI to Compose (or extracting KimuVideo's) is far less work.
- Compose's backend (FastAPI + PostgreSQL + Redis + FFmpeg + Whisper + Claude + Gemini + Pexels + Remotion) is production-architected with job queues, watchdogs, error handling, storage abstraction, and Railway deployment.

**Score:**
- **Compose**: 8/10 for SupaCut foundation (missing: NLE timeline UI, real-time preview, auth)
- **KimuVideo**: 4/10 for SupaCut foundation (has: NLE UI, preview, auth. Missing: entire AI pipeline)

---

## 6. Repo Classification

| Repo | Classification | Rationale |
|------|---------------|-----------|
| **Compose** | **Good as a direct base** | Full AI video pipeline implemented. Add timeline UI and auth on top. |
| **KimuVideo** | **Good for selective extraction** | Extract: timeline UI components, Remotion preview/render setup, auth system, transition system. The AI chat and backend are not useful. |

---

## 7. Railway Deployment Plan (Compose)

Compose already has Railway configs. Here's the refined plan:

### Service 1: API Backend (main)
- **Source**: Root `Dockerfile` (already configured)
- **Config**: `railway.toml` → `builder = "DOCKERFILE"`
- **Env vars**: `DATABASE_URL` (auto), `ANTHROPIC_API_KEY`, `PEXELS_API_KEY`, `GEMINI_API_KEY`, `WHISPER_MODEL=base`, `STORAGE_MODE=r2`, `R2_*` vars, `ALLOWED_ORIGINS`
- **Health**: `GET /health` → 200

### Service 2: Worker (optional, for scale)
- **Config**: `railway.worker.toml`
- **Needs**: `REDIS_URL` (auto from Railway Redis plugin), same env vars as API
- **Purpose**: Process jobs via RQ instead of in-thread

### Service 3: PostgreSQL
- `railway add --plugin postgresql` → auto-sets `DATABASE_URL`

### Service 4: Redis (optional)
- `railway add --plugin redis` → auto-sets `REDIS_URL`
- Without Redis, jobs run in-thread (fine for MVP)

### Service 5: Frontend (Vercel)
- Deploy `apps/web/` to Vercel
- Set `NEXT_PUBLIC_API_URL` to Railway API URL

### Steps:
```bash
railway init
railway add --plugin postgresql
# Link GitHub repo, builder auto-detected
# Set env vars in dashboard
# Push to main → auto-deploy
```

---

## 8. Migration Plan: Merging SupaCut + Compose

### Phase 1: Adopt Compose as Base (Week 1)
1. Fork/clone Compose as the new SupaCut repo
2. Rename branding (Compose → SupaCut)
3. Deploy to Railway to verify pipeline works end-to-end
4. Run test: upload video → get edited output

### Phase 2: Extract from KimuVideo (Weeks 2-3)
1. **Timeline UI**: Port `app/hooks/useTimeline.ts`, `app/components/timeline/*`, `app/video-compositions/VideoPlayer.tsx` into Compose's `apps/web/`
2. **Auth**: Port Better Auth setup (`app/lib/auth.server.ts`, `app/lib/auth.client.ts`) or use Compose's own auth approach
3. **Remotion Preview**: Port `@remotion/player` integration for real-time preview
4. **Transitions**: Port `TransitionSeries` usage from KimuVideo
5. **Text Editor**: Port `app/components/media/TextEditor.tsx`

### Phase 3: Connect Timeline to AI Pipeline (Weeks 3-4)
1. Wire KimuVideo's timeline state → Compose's `EditPlan` schema
2. Allow users to either: (a) auto-generate from prompt, or (b) manually edit timeline
3. Map `EditPlan.main_cuts` ↔ timeline scrubber positions
4. Display transcript under timeline with word-level highlights
5. Let users click transcript words to set cut points

### Phase 4: Merge AI Features into Timeline (Weeks 4-6)
1. Show AI-generated captions as a caption track in timeline
2. Show b-roll inserts as scrubbers on a b-roll track
3. Show Remotion motion graphics as scrubbers
4. Allow manual adjustment of all AI-generated elements
5. Re-render on save with updated EditPlan

### Phase 5: Polish & Ship (Weeks 6-8)
1. Add auth/user system if not already from KimuVideo
2. Add project save/load
3. Add export quality presets
4. Deploy frontend to Vercel, backend to Railway
5. E2E testing

### Key Files to Port from KimuVideo:
- `app/hooks/useTimeline.ts` → timeline state management
- `app/components/timeline/` → all timeline UI components
- `app/video-compositions/VideoPlayer.tsx` → Remotion preview
- `app/video-compositions/DragDrop.tsx` → drag-drop in preview
- `app/components/timeline/types.ts` → type definitions
- `app/lib/auth.server.ts` → auth setup
- `app/components/media/TextEditor.tsx` → text editing
- `app/components/media/Transitions.tsx` → transition picker

### Key Files to Keep from Compose:
- `apps/api/` → entire backend (FastAPI, services, models, worker)
- `apps/remotion/` → motion graphics templates
- `assets/music/` → music pack
- `infra/` → Docker Compose
- `railway.toml` → Railway deployment
- `Dockerfile` → production Docker build
