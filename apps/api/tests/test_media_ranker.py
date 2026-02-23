"""Smoke tests for the media_ranker package.

Unit tests run without any API keys.
The smoke test at the bottom requires PEXELS_API_KEY and is skipped in CI.
"""

import os
import pytest

from apps.api.services.media_ranker.query_variants import normalize_query, variants


# --------------------------------------------------------------------------- #
# query_variants unit tests (no API needed)
# --------------------------------------------------------------------------- #

class TestNormalizeQuery:
    def test_trims_whitespace(self):
        assert normalize_query("  hello world  ") == "hello world"

    def test_collapses_spaces(self):
        assert normalize_query("hello   world") == "hello world"

    def test_empty(self):
        assert normalize_query("") == ""
        assert normalize_query("   ") == ""


class TestVariants:
    def test_four_variants_all_distinct(self):
        # Query with spaces AND punctuation yields all 4 distinct variants
        result = variants("chat-gpt app")
        assert len(result) == 4
        assert result[0] == "chat-gpt app"       # normalized
        assert result[1] == "chatgpt app"         # punct stripped
        assert result[2] == "chat-gptapp"         # spaces removed
        assert result[3] == "chat-gpt-app"        # spaces -> hyphen

    def test_variants_dedup_no_punctuation(self):
        # No punctuation => norm == punct_stripped, only 3 unique
        result = variants("chat gpt")
        assert len(result) == 3
        assert result[0] == "chat gpt"
        assert "chatgpt" in result
        assert "chat-gpt" in result

    def test_deduplication(self):
        # Single word produces fewer variants due to dedup
        result = variants("nvidia")
        assert len(result) >= 1
        assert result[0] == "nvidia"

    def test_punctuation_strip(self):
        result = variants("chat-gpt!")
        assert "chatgpt" in result

    def test_max_variants(self):
        result = variants("hello world", max_variants=2)
        assert len(result) <= 2

    def test_empty(self):
        assert variants("") == []
        assert variants("  ") == []


# --------------------------------------------------------------------------- #
# Smoke test — requires PEXELS_API_KEY + CLIP deps
# --------------------------------------------------------------------------- #

_HAS_PEXELS_KEY = bool(os.getenv("PEXELS_API_KEY", ""))


@pytest.mark.skipif(not _HAS_PEXELS_KEY, reason="PEXELS_API_KEY not set")
def test_smoke_pexels_photo_search_and_rank():
    """End-to-end: Pexels photo search + CLIP ranking for a sample query.

    Run with: PEXELS_API_KEY=<key> pytest apps/api/tests/test_media_ranker.py -k smoke -s
    """
    from apps.api.services.media_ranker.pexels_client import search_photos
    from apps.api.services.media_ranker.clip_ranker import rank_image_candidates

    query = "chat gpt phone screen"
    qvars = variants(query)

    pool = []
    seen = set()
    for v in qvars:
        for c in search_photos(v, per_page=6):
            if c["id"] not in seen:
                seen.add(c["id"])
                c["_variant"] = v
                pool.append(c)

    assert len(pool) > 0, "Pexels returned no photo candidates"

    ranked = rank_image_candidates(pool, query=query, k=3)
    assert len(ranked) > 0, "CLIP ranking returned no results"

    print(f"\n=== Smoke test: query='{query}' ===")
    print(f"Variants: {qvars}")
    print(f"Pool size: {len(pool)}")
    for i, r in enumerate(ranked):
        print(
            f"  #{i+1} id={r['id']} alt={r.get('alt', '')[:60]} "
            f"pos={r['pos_score']:.4f} neg={r['neg_score']:.4f} "
            f"clip={r['clip_score']:.4f} final={r['final_score']:.4f}"
        )
