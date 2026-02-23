"""HTTP utilities for media_ranker: download with timeout, retry, streaming."""

import logging
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

from apps.api.config import CLIP_HTTP_TIMEOUT_S, CLIP_HTTP_RETRY

logger = logging.getLogger(__name__)


def download_to_file(
    url: str,
    dest: Path,
    *,
    timeout_s: float = 0.0,
    retries: int = -1,
    headers: Optional[dict] = None,
) -> bool:
    """Stream-download *url* to *dest*. Returns True on success.

    Writes to a temp file first and renames on success to avoid partial files.
    Uses CLIP_HTTP_TIMEOUT_S / CLIP_HTTP_RETRY from config as defaults.
    """
    if timeout_s <= 0:
        timeout_s = CLIP_HTTP_TIMEOUT_S
    if retries < 0:
        retries = CLIP_HTTP_RETRY

    dest.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1 + retries):
        tmp_path: Optional[Path] = None
        try:
            with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
                with client.stream("GET", url, headers=headers or {}) as resp:
                    resp.raise_for_status()
                    fd = tempfile.NamedTemporaryFile(
                        dir=str(dest.parent), suffix=dest.suffix, delete=False,
                    )
                    tmp_path = Path(fd.name)
                    try:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            fd.write(chunk)
                    finally:
                        fd.close()

            tmp_path.rename(dest)
            return True

        except Exception as exc:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            if attempt < retries:
                logger.debug(
                    "download retry %d/%d for %s: %s",
                    attempt + 1, retries, url[:80], exc,
                )
                time.sleep(0.5)
            else:
                logger.warning(
                    "download failed after %d attempts for %s: %s",
                    attempt + 1, url[:80], exc,
                )
    return False


def download_bytes(
    url: str,
    *,
    timeout_s: float = 0.0,
    retries: int = -1,
    headers: Optional[dict] = None,
) -> Optional[bytes]:
    """Download *url* into memory. Returns bytes or None on failure."""
    if timeout_s <= 0:
        timeout_s = CLIP_HTTP_TIMEOUT_S
    if retries < 0:
        retries = CLIP_HTTP_RETRY

    for attempt in range(1 + retries):
        try:
            with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
                resp = client.get(url, headers=headers or {})
                resp.raise_for_status()
                return resp.content
        except Exception as exc:
            if attempt < retries:
                time.sleep(0.5)
            else:
                logger.warning(
                    "download_bytes failed for %s: %s", url[:80], exc,
                )
    return None
