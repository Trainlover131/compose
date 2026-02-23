"""Media ranker: Pexels search + OpenCLIP scoring for overlays and b-roll.

Sub-modules are imported lazily to avoid hard failures when optional
dependencies (httpx, torch, open_clip) are not installed in test envs.
"""

__all__ = [
    "normalize_query",
    "variants",
    "search_photos",
    "search_videos",
    "rank_image_candidates",
    "rank_video_candidates",
]


def __getattr__(name: str):
    if name in ("normalize_query", "variants"):
        from apps.api.services.media_ranker.query_variants import (
            normalize_query, variants,
        )
        return normalize_query if name == "normalize_query" else variants

    if name in ("search_photos", "search_videos"):
        from apps.api.services.media_ranker import pexels_client
        return getattr(pexels_client, name)

    if name in ("rank_image_candidates", "rank_video_candidates"):
        from apps.api.services.media_ranker import clip_ranker
        return getattr(clip_ranker, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
