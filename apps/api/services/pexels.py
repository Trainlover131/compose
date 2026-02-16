"""Pexels API client for b-roll video search and download."""

import hashlib
import logging
import os
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
    """Download a Pexels video and cache it locally. Returns raw mp4 path.

    No transcoding is done here; trim/scale/crop happens in the render pipeline.
    """
    BROLL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    raw_path = BROLL_CACHE_DIR / f"{url_hash}_raw.mp4"

    if raw_path.exists():
        logger.info(f"B-roll cache hit: {raw_path}")
        return str(raw_path)

    try:
        logger.info(f"Downloading b-roll: {url[:80]}...")

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(raw_path, "wb") as f:
                    for chunk in resp.iter_bytes():
                        if chunk:
                            f.write(chunk)

        logger.info(f"B-roll downloaded: {raw_path} ({raw_path.stat().st_size} bytes)")
        return str(raw_path)

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
