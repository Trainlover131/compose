"""Pexels API client for b-roll video search and download."""

import hashlib
import logging
import os
import subprocess
from pathlib import Path

import httpx

from apps.api.config import PEXELS_API_KEY, LOCAL_STORAGE_PATH, is_pexels_available

logger = logging.getLogger(__name__)

PEXELS_API_BASE = "https://api.pexels.com"
BROLL_CACHE_DIR = LOCAL_STORAGE_PATH / "broll_cache"


def search_videos(query: str, per_page: int = 5, orientation: str = "portrait") -> list[dict]:
    """Search Pexels for stock videos."""
    if not is_pexels_available():
        logger.warning("Pexels API key not configured, skipping b-roll search")
        return []

    try:
        headers = {"Authorization": PEXELS_API_KEY}
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": orientation,
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"{PEXELS_API_BASE}/videos/search",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        videos = []
        for video in data.get("videos", []):
            # Find the best HD file
            best_file = None
            for vf in video.get("video_files", []):
                if vf.get("quality") == "hd" and vf.get("width", 0) >= 720:
                    best_file = vf
                    break
            if not best_file:
                # Fallback to any file
                files = video.get("video_files", [])
                if files:
                    best_file = files[0]

            if best_file:
                videos.append({
                    "pexels_id": video["id"],
                    "url": best_file["link"],
                    "width": best_file.get("width", 0),
                    "height": best_file.get("height", 0),
                    "duration": video.get("duration", 0),
                    "photographer": video.get("user", {}).get("name", "Unknown"),
                    "pexels_url": video.get("url", ""),
                })

        logger.info(f"Pexels search '{query}': found {len(videos)} videos")
        return videos

    except Exception as e:
        logger.error(f"Pexels search failed for '{query}': {e}")
        return []


def download_video(url: str, target_duration: float = 10.0) -> str | None:
    """Download a Pexels video and cache it locally. Returns local file path."""
    BROLL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    cached_path = BROLL_CACHE_DIR / f"{url_hash}.mp4"

    if cached_path.exists():
        logger.info(f"B-roll cache hit: {cached_path}")
        return str(cached_path)

    try:
        logger.info(f"Downloading b-roll: {url[:80]}...")
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            raw_path = BROLL_CACHE_DIR / f"{url_hash}_raw.mp4"
            raw_path.write_bytes(resp.content)

        # Trim to target duration and convert to 9:16 if needed
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw_path),
            "-t", str(target_duration),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-an",  # No audio for b-roll
            str(cached_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        raw_path.unlink(missing_ok=True)

        if result.returncode == 0:
            logger.info(f"B-roll downloaded and processed: {cached_path}")
            return str(cached_path)
        else:
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            stderr_tail = stderr_text[-2000:] if len(stderr_text) > 2000 else stderr_text
            logger.error(
                f"B-roll ffmpeg failed (rc={result.returncode})\n"
                f"  cmd: {' '.join(cmd)}\n"
                f"  stderr: {stderr_tail}"
            )
            return None

    except Exception as e:
        logger.error(f"B-roll download failed: {e}")
        return None


def fetch_broll_for_plan(broll_inserts: list[dict]) -> list[dict]:
    """Fetch b-roll clips for all inserts in the edit plan.

    Returns updated inserts with asset_path filled in.
    """
    if not is_pexels_available():
        logger.warning("Pexels not available, skipping b-roll fetch")
        return broll_inserts

    updated = []
    for insert in broll_inserts:
        query = insert.get("query", "")
        duration = insert.get("end", 0) - insert.get("start", 0)
        if duration <= 0:
            duration = 3.0

        results = search_videos(query, per_page=3, orientation="portrait")
        if results:
            # Pick the first result
            video = results[0]
            local_path = download_video(video["url"], target_duration=duration)
            if local_path:
                insert["asset_path"] = local_path
                insert["attribution"] = (
                    f"Video by {video['photographer']} from Pexels: {video['pexels_url']}"
                )

        updated.append(insert)

    fetched = sum(1 for i in updated if i.get("asset_path"))
    logger.info(f"B-roll fetch complete: {fetched}/{len(updated)} clips downloaded")
    return updated
