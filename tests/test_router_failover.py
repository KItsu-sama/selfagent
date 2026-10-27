"""Offline regression tests for API failover and cooldown classification."""
import unittest
from unittest.mock import Mock

from core.router import (
    ProviderHTTPError,
    ProviderUnavailable,
    Router,
    _cooldown_seconds,
    _safe_error_body,
)


class RouterFailoverTests(unittest.TestCase):
    def make_router(self):
        router = Router.__new__(Router)
        router.health = {}
        router.mock = False
        router._save = Mock()
        router._call = Mock()
        return router

    def test_quota_failure_switches_provider_with_same_messages(self):
        router = self.make_router()
        messages = [
            {"role": "system", "content": "keep context"},
            {"role": "user", "content": "continue my task"},
            {"role": "assistant", "content": "prior tool result"},
        ]
        p1 = {"name": "Provider A"}
        p2 = {"name": "Provider B"}
        router.candidates = Mock(return_value=[
            (1.0, p1, "model-a", "Provider A/model-a", "key-a"),
            (0.9, p2, "model-b", "Provider B/model-b", "key-b"),
        ])
        router._call.side_effect = [
            ProviderHTTPError(429, "quota exceeded"),
            "continued response",
        ]

        answer = router.chat(messages, cache=False)

        self.assertEqual(answer, "continued response")
        self.assertEqual(router._call.call_count, 2)
        self.assertIs(router._call.call_args_list[0].args[2], messages)
        self.assertIs(router._call.call_args_list[1].args[2], messages)
        self.assertGreater(router.health["Provider A/model-a"]["cool_until"], 0)
        self.assertGreater(router.health["provider:Provider A"]["cool_until"], 0)
        self.assertEqual(router.health["Provider B/model-b"]["ok"], 1)

    def test_auth_failure_switches_provider_and_cools_down_bad_key(self):
        router = self.make_router()
        messages = [{"role": "user", "content": "continue"}]
        p1 = {"name": "Provider A"}
        p2 = {"name": "Provider B"}
        router.candidates = Mock(return_value=[
            (1.0, p1, "model-a", "Provider A/model-a", "key-a"),
            (0.9, p2, "model-b", "Provider B/model-b", "key-b"),
        ])
        router._call.side_effect = [
            ProviderHTTPError(401, "invalid API key"),
            "backup response",
        ]

        self.assertEqual(router.chat(messages, cache=False), "backup response")
        self.assertEqual(router._call.call_count, 2)
        self.assertIs(router._call.call_args_list[1].args[2], messages)
        self.assertGreater(router.health["Provider A/model-a"]["cool_until"], 0)
        self.assertEqual(
            router.health["Provider A/model-a"]["last_error"],
            "HTTP 401: invalid API key",
        )

    def test_all_provider_failures_raise_unavailable_error(self):
        router = self.make_router()
        router.candidates = Mock(return_value=[
            (1.0, {"name": "Provider A"}, "model-a", "Provider A/model-a", "key-a"),
            (0.9, {"name": "Provider B"}, "model-b", "Provider B/model-b", "key-b"),
        ])
        router._call.side_effect = [
            ProviderHTTPError(503, "provider unavailable"),
            ProviderHTTPError(429, "rate limit"),
        ]

        with self.assertRaises(ProviderUnavailable) as caught:
            router.chat([{"role": "user", "content": "task"}], cache=False)

        self.assertIn("All configured providers failed", str(caught.exception))
        self.assertIn("Provider A/model-a", str(caught.exception))
        self.assertIn("Provider B/model-b", str(caught.exception))
        self.assertEqual(router._call.call_count, 2)

    def test_quota_and_auth_errors_get_longer_cooldowns(self):
        self.assertEqual(_cooldown_seconds(ProviderHTTPError(429, "rate limit")), 900)
        self.assertEqual(_cooldown_seconds(ProviderHTTPError(401, "invalid key")), 3600)

    def test_error_body_extracts_provider_message(self):
        self.assertEqual(
            _safe_error_body('{"error":{"message":"model not found"}}'),
            "model not found",
        )


if __name__ == "__main__":
    unittest.main()
