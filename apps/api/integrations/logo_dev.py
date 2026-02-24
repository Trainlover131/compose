"""Logo.dev integration — search brand domains and download logo PNGs.

Usage flow:
  1. normalize_brand_query(text) -> cleaned brand name
  2. search_domain(brand) -> optional domain string
  3. logo_url_for_domain(domain) or logo_url_for_name(name) -> image URL
  4. fetch_logo_to_cache(brand, cache_dir) -> local Path or None
"""

import hashlib
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from apps.api.config import LOGO_DEV_SECRET_KEY, LOGO_DEV_PUBLISHABLE_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Brand query normalisation
# ---------------------------------------------------------------------------

def normalize_brand_query(text: str) -> str:
    """Normalise a brand name for Logo.dev lookup.

    - Preserves spaces (do NOT smash words together).
    - Strips trailing "logo" (case-insensitive).
    - Strips leading/trailing whitespace and collapses inner runs.
    - Does NOT invent abbreviations.
    """
    text = text.strip()
    # Remove trailing "logo" (with optional leading space)
    text = re.sub(r"\s+logo$", "", text, flags=re.IGNORECASE)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Domain search via Logo.dev Search API
# ---------------------------------------------------------------------------

def search_domain(brand_name: str) -> Optional[str]:
    """Search Logo.dev for the best-matching domain for *brand_name*.

    GET https://api.logo.dev/search?q={brand_name}&strategy=match
    Authorization: Bearer LOGO_DEV_SECRET_KEY

    Returns the first result's ``domain`` field, or None.
    """
    key = (LOGO_DEV_SECRET_KEY or "").strip()
    if not key:
        logger.warning("Logo.dev search skipped: LOGO_DEV_SECRET_KEY not set")
        return None

    encoded_q = urllib.parse.quote(brand_name)
    url = f"https://api.logo.dev/search?q={encoded_q}&strategy=match"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "compose-worker/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        logger.warning("Logo.dev search HTTP %s: %s (brand=%s)", exc.code, body, brand_name)
        return None
    except Exception as exc:
        logger.warning("Logo.dev search error: %s (brand=%s)", exc, brand_name)
        return None

    if isinstance(data, list) and data:
        domain = data[0].get("domain")
        if domain:
            logger.info("Logo.dev search brand=%s -> domain=%s", brand_name, domain)
            return str(domain)

    logger.info("Logo.dev search brand=%s -> no results", brand_name)
    return None


# ---------------------------------------------------------------------------
# Logo URL construction
# ---------------------------------------------------------------------------

def logo_url_for_domain(domain: str) -> str:
    """Build an img.logo.dev URL for a known *domain*.

    Example: https://img.logo.dev/google.com?token=…&format=png&size=256
    """
    token = (LOGO_DEV_PUBLISHABLE_KEY or "").strip()
    return (
        f"https://img.logo.dev/{domain}"
        f"?token={token}&format=png&size=256&theme=light&fallback=404"
    )


def logo_url_for_name(name: str) -> str:
    """Build an img.logo.dev *name-based* URL (fallback when domain is unknown).

    Example: https://img.logo.dev/name/Stanford%20University?token=…
    """
    token = (LOGO_DEV_PUBLISHABLE_KEY or "").strip()
    encoded = urllib.parse.quote(name)
    return (
        f"https://img.logo.dev/name/{encoded}"
        f"?token={token}&format=png&size=256&theme=light&fallback=404"
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_filename(brand_name: str) -> str:
    """Deterministic cache filename based on SHA-1 of the brand name."""
    h = hashlib.sha1(brand_name.encode()).hexdigest()
    return f"logo_dev_{h}.png"


# ---------------------------------------------------------------------------
# Download logo to local cache
# ---------------------------------------------------------------------------

def fetch_logo_to_cache(brand_name: str, cache_dir: Path) -> Optional[Path]:
    """Download a Logo.dev logo for *brand_name* and cache it on disk.

    Strategy:
      1. search_domain(brand) -> if domain found, use domain logo URL.
      2. If search yields nothing, fall back to name-based logo URL.
      3. Download PNG bytes, validate non-empty, write to cache_dir.

    Returns the Path to the cached file, or None on failure.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / _cache_filename(brand_name)

    # Return cached file if already downloaded
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Logo.dev cache hit: %s", dest)
        return dest

    cleaned = normalize_brand_query(brand_name)
    if not cleaned:
        return None

    # Step 1: try domain-based logo
    domain = search_domain(cleaned)
    if domain:
        logo_url = logo_url_for_domain(domain)
        result = _download_logo(logo_url, dest, cleaned, source="domain")
        if result:
            return result

    # Step 2: fallback to name-based logo
    logger.info("Logo.dev fallback name endpoint used brand=%s", cleaned)
    logo_url = logo_url_for_name(cleaned)
    result = _download_logo(logo_url, dest, cleaned, source="name")
    if result:
        return result

    return None


def _download_logo(url: str, dest: Path, brand: str, source: str) -> Optional[Path]:
    """Download a logo image from *url* to *dest*. Returns dest or None."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "image/png,image/*",
            "User-Agent": "compose-worker/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        logger.warning(
            "Logo.dev download HTTP %s for brand=%s source=%s url=%s",
            exc.code, brand, source, url,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Logo.dev download error: %s for brand=%s source=%s",
            exc, brand, source,
        )
        return None

    if not data or len(data) < 100:
        logger.warning(
            "Logo.dev download empty/tiny (%d bytes) brand=%s source=%s",
            len(data) if data else 0, brand, source,
        )
        return None

    dest.write_bytes(data)
    logger.info(
        "Logo.dev downloaded path=%s size_bytes=%d (brand=%s source=%s)",
        dest, len(data), brand, source,
    )
    return dest
