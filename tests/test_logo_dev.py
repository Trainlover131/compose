"""Unit tests for apps.api.integrations.logo_dev — no network calls."""

import hashlib
import os
import unittest
from unittest.mock import patch

# Ensure config env vars are set before importing the module
os.environ.setdefault("LOGO_DEV_SECRET_KEY", "test-secret-key")
os.environ.setdefault("LOGO_DEV_PUBLISHABLE_KEY", "test-pub-key")

from apps.api.integrations.logo_dev import (
    normalize_brand_query,
    logo_url_for_domain,
    logo_url_for_name,
    _cache_filename,
)


class TestNormalizeBrandQuery(unittest.TestCase):
    def test_strips_trailing_logo(self):
        self.assertEqual(normalize_brand_query("Google logo"), "Google")
        self.assertEqual(normalize_brand_query("Google Logo"), "Google")
        self.assertEqual(normalize_brand_query("Google LOGO"), "Google")

    def test_preserves_spaces(self):
        self.assertEqual(normalize_brand_query("Y Combinator"), "Y Combinator")
        self.assertEqual(
            normalize_brand_query("Massachusetts Institute of Technology"),
            "Massachusetts Institute of Technology",
        )

    def test_collapses_inner_whitespace(self):
        self.assertEqual(normalize_brand_query("Y   Combinator"), "Y Combinator")

    def test_strips_outer_whitespace(self):
        self.assertEqual(normalize_brand_query("  Google  "), "Google")

    def test_no_trailing_logo_inside_name(self):
        # "Logotherapy" should not be mangled
        self.assertEqual(normalize_brand_query("Logotherapy"), "Logotherapy")

    def test_empty_string(self):
        self.assertEqual(normalize_brand_query(""), "")
        self.assertEqual(normalize_brand_query("   "), "")

    def test_logo_only(self):
        # "logo" alone is not a valid brand suffix pattern (requires space
        # before "logo"), so it is preserved as-is.
        self.assertEqual(normalize_brand_query("logo"), "logo")


class TestLogoUrlForDomain(unittest.TestCase):
    @patch("apps.api.integrations.logo_dev.LOGO_DEV_PUBLISHABLE_KEY", "pk_abc123")
    def test_url_structure(self):
        url = logo_url_for_domain("google.com")
        self.assertEqual(
            url,
            "https://img.logo.dev/google.com"
            "?token=pk_abc123&format=png&size=256&theme=light&fallback=404",
        )

    @patch("apps.api.integrations.logo_dev.LOGO_DEV_PUBLISHABLE_KEY", "pk_abc123")
    def test_domain_with_subdomain(self):
        url = logo_url_for_domain("docs.google.com")
        self.assertIn("docs.google.com", url)
        self.assertIn("token=pk_abc123", url)


class TestLogoUrlForName(unittest.TestCase):
    @patch("apps.api.integrations.logo_dev.LOGO_DEV_PUBLISHABLE_KEY", "pk_abc123")
    def test_url_structure(self):
        url = logo_url_for_name("Stanford University")
        self.assertIn("img.logo.dev/name/Stanford%20University", url)
        self.assertIn("token=pk_abc123", url)
        self.assertIn("format=png", url)

    @patch("apps.api.integrations.logo_dev.LOGO_DEV_PUBLISHABLE_KEY", "pk_abc123")
    def test_special_characters_encoded(self):
        url = logo_url_for_name("AT&T")
        self.assertIn("img.logo.dev/name/AT%26T", url)


class TestCacheFilename(unittest.TestCase):
    def test_deterministic(self):
        """Same brand name always produces the same cache filename."""
        fn1 = _cache_filename("Google")
        fn2 = _cache_filename("Google")
        self.assertEqual(fn1, fn2)

    def test_different_brands_different_filenames(self):
        fn1 = _cache_filename("Google")
        fn2 = _cache_filename("Apple")
        self.assertNotEqual(fn1, fn2)

    def test_filename_format(self):
        fn = _cache_filename("Google")
        expected_hash = hashlib.sha1("Google".encode()).hexdigest()
        self.assertEqual(fn, f"logo_dev_{expected_hash}.png")

    def test_prefix_and_extension(self):
        fn = _cache_filename("Stripe")
        self.assertTrue(fn.startswith("logo_dev_"))
        self.assertTrue(fn.endswith(".png"))


if __name__ == "__main__":
    unittest.main()
