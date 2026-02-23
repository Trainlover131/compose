"""Pexels API client for photo and video search (media_ranker)."""

import logging
from typing import Optional

import httpx

from apps.api.config import PEXELS_API_KEY, CLIP_HTTP_TIMEOUT_S

logger = logging.getLogger(__name__)

PEXELS_API_BASE = "https://api.pexels.com"


def _headers() -> dict[str, str]:
    return {"Authorization": PEXELS_API_KEY}


# --------------------------------------------------------------------------- #
# Photo search
# --------------------------------------------------------------------------- #

def search_photos(query: str, per_page: int = 6) -> list[dict]:
    """Search Pexels Photos API. Returns normalised candidate dicts.

    Each candidate has:
        id, width, height, alt, photographer, download_url, page_url, tags
    """
    if not PEXELS_API_KEY:
        return []

    try:
        with httpx.Client(timeout=max(CLIP_HTTP_TIMEOUT_S * 2, 5.0)) as client:
            resp = client.get(
                f"{PEXELS_API_BASE}/v1/search",
                headers=_headers(),
                params={"query": query, "per_page": per_page, "page": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        candidates: list[dict] = []
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            # Priority: portrait > large > medium > original
            download_url = (
                src.get("portrait")
                or src.get("large")
                or src.get("medium")
                or src.get("original")
            )
            if not download_url:
                continue

            candidates.append({
                "id": photo["id"],
                "width": photo.get("width", 0),
                "height": photo.get("height", 0),
                "alt": photo.get("alt", ""),
                "photographer": photo.get("photographer", ""),
                "photographer_url": photo.get("photographer_url", ""),
                "download_url": download_url,
                "page_url": photo.get("url", ""),
                "tags": "",  # Pexels Photos API doesn't return tags
            })

        return candidates

    except Exception as exc:
        logger.warning("Pexels photo search failed for '%s': %s", query[:60], exc)
        return []


# --------------------------------------------------------------------------- #
# Video search
# --------------------------------------------------------------------------- #

def _pick_video_file(
    video_files: list[dict],
    target_vertical: bool = True,
) -> Optional[str]:
    """Choose the best mp4 from *video_files* per the spec priority.

    1) file_type == "video/mp4", width/height not null
    2) prefer portrait (height > width) when target is 9:16
    3) prefer smallest mp4 >= 540px on shorter side
    4) fallback: smallest mp4 available
    """
    mp4s = [
        vf for vf in video_files
        if vf.get("file_type") == "video/mp4"
        and vf.get("width") is not None
        and vf.get("height") is not None
    ]
    if not mp4s:
        # Fallback: any mp4
        mp4s = [vf for vf in video_files if vf.get("file_type") == "video/mp4"]
    if not mp4s:
        return None

    def _sort_key(vf: dict) -> tuple:
        w = vf.get("width") or 9999
        h = vf.get("height") or 9999
        is_portrait = int(h > w)
        shorter = min(w, h)
        meets_min = int(shorter >= 540)
        # We want: portrait first (desc), meets_min first (desc), then smallest total
        return (-is_portrait if target_vertical else 0, -meets_min, w * h)

    mp4s.sort(key=_sort_key)
    return mp4s[0].get("link")


def search_videos(query: str, per_page: int = 6) -> list[dict]:
    """Search Pexels Videos API. Returns normalised candidate dicts.

    Each candidate has:
        id, width, height, duration, preview_url, page_url,
        photographer, tags, image (thumbnail)
    """
    if not PEXELS_API_KEY:
        return []

    try:
        with httpx.Client(timeout=max(CLIP_HTTP_TIMEOUT_S * 2, 5.0)) as client:
            resp = client.get(
                f"{PEXELS_API_BASE}/videos/search",
                headers=_headers(),
                params={"query": query, "per_page": per_page, "page": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        candidates: list[dict] = []
        for video in data.get("videos", []):
            preview_url = _pick_video_file(
                video.get("video_files", []), target_vertical=True,
            )
            if not preview_url:
                continue

            candidates.append({
                "id": video["id"],
                "width": video.get("width", 0),
                "height": video.get("height", 0),
                "duration": video.get("duration", 0),
                "preview_url": preview_url,
                "page_url": video.get("url", ""),
                "photographer": video.get("user", {}).get("name", ""),
                "photographer_url": video.get("user", {}).get("url", ""),
                "image": video.get("image", ""),
                "tags": "",
            })

        return candidates

    except Exception as exc:
        logger.warning("Pexels video search failed for '%s': %s", query[:60], exc)
        return []
