"""Offline tests for the replaceable provider catalog adapter."""
import unittest

from core.provider_catalog import _normalise_base_url, parse_catalog


SAMPLE = """# Free APIs
### Provider APIs

### Example Provider
Permanent free tier.

Base URL: \x60https://api.example.test/v1\x60

| Model Name | Context | Rate |
| --- | --- | --- |
| \x60example/model-a\x60 | 32K | free |
| Plain Model B | 8K | free |
| + 5 more models | Varies | Varies |

### Inference providers

### Google Gemini
Base URL: \x60https://generativelanguage.googleapis.com/v1beta\x60

| Model Name | Context |
| --- | --- |
| Gemini Example | 1M |
"""


class ProviderCatalogTests(unittest.TestCase):
    def test_parses_provider_models_and_skips_summary_rows(self):
        providers = parse_catalog(SAMPLE)
        self.assertEqual([p["name"] for p in providers], ["Example Provider", "Google Gemini"])
        self.assertEqual(providers[0]["base_url"], "https://api.example.test/v1")
        self.assertEqual(providers[0]["models"], ["example/model-a", "Plain Model B"])

    def test_google_openai_compatible_endpoint_is_normalized(self):
        provider = {
            "name": "Google Gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
        }
        self.assertEqual(
            _normalise_base_url(provider),
            "https://generativelanguage.googleapis.com/v1beta/openai",
        )

    def test_rejects_provider_that_needs_a_different_request_format(self):
        provider = {"name": "Cohere", "base_url": "https://api.cohere.com/v2"}
        with self.assertRaises(ValueError):
            _normalise_base_url(provider)


if __name__ == "__main__":
    unittest.main()
