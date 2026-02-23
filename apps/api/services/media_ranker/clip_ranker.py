"""OpenCLIP-based image and video ranking for Pexels candidates."""

import asyncio
import io
import logging
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from apps.api.config import (
    CLIP_ENABLED,
    CLIP_MODEL,
    CLIP_PRETRAINED,
    CLIP_DEVICE,
    CLIP_FRAMES_PER_VIDEO,
    CLIP_MAX_CONCURRENT_DOWNLOADS,
    CLIP_MAX_CONCURRENT_VIDEO_EXTRACTS,
    CLIP_TARGET_ASPECT,
)
from apps.api.services.media_ranker.http_utils import download_bytes, download_to_file

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Singleton CLIP model (lazy-loaded, thread-safe)
# --------------------------------------------------------------------------- #
_model_lock = threading.Lock()
_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None


def _ensure_model():
    """Lazy-load the CLIP model exactly once per process."""
    global _clip_model, _clip_preprocess, _clip_tokenizer
    if _clip_model is not None:
        return

    with _model_lock:
        if _clip_model is not None:
            return  # Another thread loaded while we waited

        import open_clip
        import torch

        logger.info(
            "Loading OpenCLIP model=%s pretrained=%s device=%s",
            CLIP_MODEL, CLIP_PRETRAINED, CLIP_DEVICE,
        )
        model, _, preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_PRETRAINED, device=CLIP_DEVICE,
        )
        model.eval()
        tokenizer = open_clip.get_tokenizer(CLIP_MODEL)
        _clip_model = model
        _clip_preprocess = preprocess
        _clip_tokenizer = tokenizer
        logger.info("OpenCLIP model loaded")


# --------------------------------------------------------------------------- #
# Prompt ensembles
# --------------------------------------------------------------------------- #
_POSITIVE_TEMPLATES = [
    "a photo clearly depicting {Q}",
    "a close-up photo of {Q}",
    "{Q} in focus, centered subject",
    "high-detail photo of {Q}",
    "{Q} logo, close-up",
    "{Q} on a screen, close-up",
    "{Q} on a phone screen",
    "{Q} on a laptop screen",
    "{Q} product photo, close-up",
    "editorial photo of {Q}",
    "high-end commercial photo of {Q}",
    "cinematic lighting photo of {Q}",
]

_NEGATIVE_PROMPTS = [
    "generic stock photo",
    "corporate stock photo",
    "staged business meeting stock photo",
    "stock photo handshake",
    "stock photo office meeting",
    "overly posed stock photo",
    "unrelated photo",
    "background texture",
    "abstract background",
    "random landscape",
]

_GENERIC_STOCK_KEYWORDS = frozenset([
    "stock", "generic", "corporate", "teamwork", "business", "meeting",
    "handshake", "smiling", "office", "collaboration", "professional",
    "portrait", "workspace",
])


# --------------------------------------------------------------------------- #
# Embedding helpers
# --------------------------------------------------------------------------- #

def _embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of text strings. Returns (N, 512) float32 array."""
    import torch

    _ensure_model()
    tokens = _clip_tokenizer(texts).to(CLIP_DEVICE)
    with torch.no_grad():
        feats = _clip_model.encode_text(tokens)
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy().astype(np.float32)


def _embed_image(img: Image.Image) -> np.ndarray:
    """Embed a single PIL Image. Returns (512,) float32 array."""
    import torch

    _ensure_model()
    tensor = _clip_preprocess(img).unsqueeze(0).to(CLIP_DEVICE)
    with torch.no_grad():
        feats = _clip_model.encode_image(tensor)
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy().astype(np.float32).squeeze(0)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def _cosine_similarities(vec: np.ndarray, mat: np.ndarray) -> np.ndarray:
    """Cosine similarities between *vec* (D,) and rows of *mat* (N, D)."""
    return mat @ vec


def _build_prompt_embeddings(query: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (pos_embeddings, neg_embeddings) for the given query."""
    pos_texts = [t.replace("{Q}", query) for t in _POSITIVE_TEMPLATES]
    neg_texts = list(_NEGATIVE_PROMPTS)
    pos_emb = _embed_texts(pos_texts)
    neg_emb = _embed_texts(neg_texts)
    return pos_emb, neg_emb


def _score_image_embedding(
    img_emb: np.ndarray,
    pos_emb: np.ndarray,
    neg_emb: np.ndarray,
) -> tuple[float, float, float]:
    """Return (pos_score, neg_score, clip_score) for one image embedding."""
    pos_sims = _cosine_similarities(img_emb, pos_emb)
    neg_sims = _cosine_similarities(img_emb, neg_emb)
    pos_score = float(np.max(pos_sims))
    neg_score = float(np.max(neg_sims))
    clip_score = 1.0 * pos_score - 0.6 * neg_score
    return pos_score, neg_score, clip_score


def _target_is_vertical() -> bool:
    """Check if CLIP_TARGET_ASPECT is vertical (e.g. 9:16)."""
    parts = CLIP_TARGET_ASPECT.split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) < int(parts[1])
        except ValueError:
            pass
    return True


def _metadata_text(candidate: dict) -> str:
    """Concatenate metadata fields into a single lowercase string."""
    parts = []
    for key in ("alt", "tags", "page_url", "download_url", "photographer"):
        val = candidate.get(key, "")
        if val:
            parts.append(str(val).lower())
    return " ".join(parts)


def _heuristic_adjustments(
    candidate: dict,
    query: str,
    clip_score: float,
) -> tuple[float, float]:
    """Return (heuristic_bonus, final_score)."""
    bonus = 0.0

    # +0.05 if metadata contains query tokens
    meta = _metadata_text(candidate)
    query_tokens = set(re.sub(r"[^\w\s]", "", query.lower()).split())
    if query_tokens and any(tok in meta for tok in query_tokens):
        bonus += 0.05

    # +0.05 if orientation matches target vertical
    if _target_is_vertical():
        w = candidate.get("width", 0) or 0
        h = candidate.get("height", 0) or 0
        if h > w:
            bonus += 0.05

    # -0.07 generic-stock metadata penalty
    if any(kw in meta for kw in _GENERIC_STOCK_KEYWORDS):
        bonus -= 0.07

    return bonus, clip_score + bonus


# --------------------------------------------------------------------------- #
# Image ranking
# --------------------------------------------------------------------------- #

def rank_image_candidates(
    candidates: list[dict],
    query: str,
    k: int = 1,
) -> list[dict]:
    """Rank image candidates by CLIP score + heuristics.

    Downloads each candidate image, embeds, scores, and returns top-*k*
    sorted by final_score descending. Each candidate gets diagnostic fields:
        clip_score, pos_score, neg_score, heuristic_score, final_score, variant_used
    """
    if not CLIP_ENABLED or not candidates:
        return candidates[:k]

    _ensure_model()
    pos_emb, neg_emb = _build_prompt_embeddings(query)

    dl_sem = threading.Semaphore(CLIP_MAX_CONCURRENT_DOWNLOADS)
    results: list[dict] = []

    def _score_one(cand: dict) -> Optional[dict]:
        dl_sem.acquire()
        try:
            img_bytes = download_bytes(cand["download_url"])
            if not img_bytes:
                return None
            try:
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            except Exception:
                return None
            img_emb = _embed_image(img)
            pos_s, neg_s, clip_s = _score_image_embedding(img_emb, pos_emb, neg_emb)
            h_bonus, final_s = _heuristic_adjustments(cand, query, clip_s)
            scored = dict(cand)
            scored.update({
                "pos_score": round(pos_s, 4),
                "neg_score": round(neg_s, 4),
                "clip_score": round(clip_s, 4),
                "heuristic_score": round(h_bonus, 4),
                "final_score": round(final_s, 4),
                "variant_used": cand.get("_variant", ""),
            })
            return scored
        except Exception as exc:
            logger.debug("CLIP image scoring failed for id=%s: %s", cand.get("id"), exc)
            return None
        finally:
            dl_sem.release()

    threads: list[threading.Thread] = []
    scored_lock = threading.Lock()

    def _worker(c: dict):
        r = _score_one(c)
        if r:
            with scored_lock:
                results.append(r)

    for cand in candidates:
        t = threading.Thread(target=_worker, args=(cand,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=30)

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:k]


# --------------------------------------------------------------------------- #
# Video ranking  (extract frames -> embed -> score)
# --------------------------------------------------------------------------- #

def _extract_video_frames(
    video_path: Path,
    n_frames: int = CLIP_FRAMES_PER_VIDEO,
    max_width: int = 320,
) -> list[Path]:
    """Extract *n_frames* at 15%, 50%, 85% from *video_path* using ffprobe+ffmpeg.

    Returns list of frame file paths. Caller must delete them.
    """
    # Get duration via ffprobe
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(video_path)],
            capture_output=True, text=True, timeout=5,
        )
        import json
        dur = float(json.loads(probe.stdout).get("format", {}).get("duration", 0))
    except Exception:
        dur = 0.0

    if dur <= 0:
        return []

    positions = [0.15, 0.50, 0.85][:n_frames]
    frame_paths: list[Path] = []

    for frac in positions:
        ts = dur * frac
        out = Path(tempfile.mktemp(suffix=".jpg", dir="/tmp"))
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", f"{ts:.2f}",
                    "-i", str(video_path),
                    "-frames:v", "1",
                    "-vf", f"scale='min({max_width},iw)':-2",
                    "-q:v", "3",
                    str(out),
                ],
                capture_output=True, timeout=10,
            )
            if out.exists() and out.stat().st_size > 0:
                frame_paths.append(out)
            else:
                if out.exists():
                    out.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Frame extraction failed at %.2fs: %s", ts, exc)
            if out.exists():
                out.unlink(missing_ok=True)

    return frame_paths


def rank_video_candidates(
    candidates: list[dict],
    query: str,
    k: int = 1,
) -> list[dict]:
    """Rank video candidates by CLIP score + heuristics.

    Downloads preview mp4, extracts 3 frames, embeds, scores.
    Returns top-*k* sorted by final_score descending.
    """
    if not CLIP_ENABLED or not candidates:
        return candidates[:k]

    _ensure_model()
    pos_emb, neg_emb = _build_prompt_embeddings(query)

    dl_sem = threading.Semaphore(CLIP_MAX_CONCURRENT_DOWNLOADS)
    extract_sem = threading.Semaphore(CLIP_MAX_CONCURRENT_VIDEO_EXTRACTS)
    results: list[dict] = []
    scored_lock = threading.Lock()

    def _score_one(cand: dict) -> Optional[dict]:
        preview_url = cand.get("preview_url")
        if not preview_url:
            return None

        video_tmp = Path(tempfile.mktemp(suffix=".mp4", dir="/tmp"))
        frame_paths: list[Path] = []
        try:
            # Download preview
            dl_sem.acquire()
            try:
                ok = download_to_file(preview_url, video_tmp)
            finally:
                dl_sem.release()

            if not ok:
                return None

            # Extract frames
            extract_sem.acquire()
            try:
                frame_paths = _extract_video_frames(video_tmp)
            finally:
                extract_sem.release()

            if not frame_paths:
                return None

            # Embed frames and score
            frame_scores: list[tuple[float, float, float]] = []
            for fp in frame_paths:
                try:
                    img = Image.open(fp).convert("RGB")
                    img_emb = _embed_image(img)
                    frame_scores.append(
                        _score_image_embedding(img_emb, pos_emb, neg_emb)
                    )
                except Exception:
                    pass

            if not frame_scores:
                return None

            # Video score = max of frame scores
            best = max(frame_scores, key=lambda x: x[2])
            pos_s, neg_s, clip_s = best

            h_bonus, final_s = _heuristic_adjustments(cand, query, clip_s)

            scored = dict(cand)
            scored.update({
                "pos_score": round(pos_s, 4),
                "neg_score": round(neg_s, 4),
                "clip_score": round(clip_s, 4),
                "heuristic_score": round(h_bonus, 4),
                "final_score": round(final_s, 4),
                "variant_used": cand.get("_variant", ""),
            })
            return scored

        except Exception as exc:
            logger.debug("CLIP video scoring failed for id=%s: %s", cand.get("id"), exc)
            return None
        finally:
            # Cleanup temp files
            for fp in frame_paths:
                try:
                    fp.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                video_tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _worker(c: dict):
        r = _score_one(c)
        if r:
            with scored_lock:
                results.append(r)

    threads: list[threading.Thread] = []
    for cand in candidates:
        t = threading.Thread(target=_worker, args=(cand,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=60)

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:k]
