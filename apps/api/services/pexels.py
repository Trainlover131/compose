"""Pexels API client for b-roll video search and download."""

import hashlib
import logging
import os
from pathlib import Path

import httpx

from apps.api.config import (
    PEXELS_API_KEY, LOCAL_STORAGE_PATH, is_pexels_available,
    CLIP_ENABLED, CLIP_CANDIDATES_PER_VARIANT,
)

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

def _clip_ranked_broll_search(query: str) -> list[dict]:
    """Search Pexels videos across query variants and rank with CLIP.

    Returns ranked candidates (media_ranker format) or empty list on failure.
    """
    try:
        from apps.api.services.media_ranker.query_variants import variants
        from apps.api.services.media_ranker.pexels_client import (
            search_videos as mr_search_videos,
        )
        from apps.api.services.media_ranker.clip_ranker import rank_video_candidates

        qvars = variants(query)
        seen_ids: set[int] = set()
        pool: list[dict] = []

        for v in qvars:
            results = mr_search_videos(v, per_page=CLIP_CANDIDATES_PER_VARIANT)
            for c in results:
                cid = c.get("id")
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    c["_variant"] = v
                    pool.append(c)

        logger.info(
            "B-roll CLIP search: query=%s variants=%d pool=%d",
            query[:60], len(qvars), len(pool),
        )

        if not pool:
            return []

        ranked = rank_video_candidates(pool, query=query, k=1)

        if ranked:
            top = ranked[0]
            logger.info(
                "B-roll CLIP top1: id=%s pos=%.4f neg=%.4f clip=%.4f "
                "heur=%.4f final=%.4f",
                top.get("id"),
                top.get("pos_score", 0), top.get("neg_score", 0),
                top.get("clip_score", 0), top.get("heuristic_score", 0),
                top.get("final_score", 0),
            )

        return ranked

    except Exception as exc:
        logger.warning("CLIP b-roll ranking failed (non-fatal): %s", exc)
        return []


def fetch_broll_for_plan(broll_inserts: list[dict]) -> list[dict]:
    """Fetch b-roll clips for all inserts in the edit plan.

    When CLIP_ENABLED, uses query variants + OpenCLIP ranking to select
    the best Pexels video. Falls back to the original first-result approach
    if CLIP fails.

    Returns updated inserts with asset_path filled in.
    IMPORTANT: Never modifies insert timing (start/end).
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

        video_url = None
        attribution_photographer = "Unknown"
        attribution_page = ""
        asset_meta = None

        # Try CLIP-ranked search first
        if CLIP_ENABLED and query:
            ranked = _clip_ranked_broll_search(query)
            if ranked:
                top = ranked[0]
                # The media_ranker candidate uses "preview_url" for the video mp4
                video_url = top.get("preview_url")
                attribution_photographer = top.get("photographer", "Unknown")
                attribution_page = top.get("page_url", "")
                asset_meta = {
                    "id": top.get("id"),
                    "url": top.get("page_url", ""),
                }

        # Fallback: original simple search
        if not video_url:
            results = search_videos(query, per_page=3, orientation="portrait")
            if results:
                video = results[0]
                video_url = video["url"]
                attribution_photographer = video["photographer"]
                attribution_page = video["pexels_url"]

        if video_url:
            local_path = download_video(video_url, target_duration=duration)
            if local_path:
                insert["asset_path"] = local_path
                insert["attribution"] = (
                    f"Video by {attribution_photographer} from Pexels: "
                    f"{attribution_page}"
                )
                if asset_meta:
                    insert["asset_meta"] = asset_meta

        updated.append(insert)

    fetched = sum(1 for i in updated if i.get("asset_path"))
    logger.info(f"B-roll fetch complete: {fetched}/{len(updated)} clips downloaded")
    return updated
