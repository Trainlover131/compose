"""Query variant generation for Pexels search diversification."""

import re
import unicodedata


def normalize_query(q: str) -> str:
    """Trim and collapse whitespace."""
    return re.sub(r"\s+", " ", q.strip())


def _strip_punctuation(s: str) -> str:
    """Remove all Unicode punctuation characters."""
    return "".join(
        ch for ch in s
        if not unicodedata.category(ch).startswith("P")
    )


def variants(q: str, max_variants: int = 4) -> list[str]:
    """Return up to *max_variants* query variants for Pexels search.

    Default 4 variants:
      1) q_norm  (trim + collapse spaces)
      2) punctuation stripped
      3) spaces removed
      4) spaces replaced with hyphen
    """
    q_norm = normalize_query(q)
    if not q_norm:
        return []

    seen: set[str] = set()
    result: list[str] = []

    def _add(v: str) -> None:
        v = v.strip()
        if v and v not in seen and len(result) < max_variants:
            seen.add(v)
            result.append(v)

    # 1) normalized
    _add(q_norm)
    # 2) punctuation stripped
    _add(_strip_punctuation(q_norm))
    # 3) spaces removed
    _add(q_norm.replace(" ", ""))
    # 4) spaces replaced with hyphen
    _add(q_norm.replace(" ", "-"))

    return result
