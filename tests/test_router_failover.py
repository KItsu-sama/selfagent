"""Offline regression tests for API failover and cooldown classification."""
import unittest
from unittest.mock import Mock, patch

from core.router import ProviderHTTPError, Router, _cooldown_seconds, _safe_error_body


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
        messages = [{"role": "user", "content": "continue my task"}]
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
        self.assertEqual(router.health["Provider B/model-b"]["ok"], 1)

    def test_quota_and_auth_errors_get_longer_cooldowns(self):
        self.assertEqual(_cooldown_seconds(ProviderHTTPError(429, "rate limit")), 900)
        self.assertEqual(_cooldown_seconds(ProviderHTTPError(401, "invalid key")), 3600)

    def test_error_body_extracts_provider_message(self):
        self.assertEqual(_safe_error_body('{"error":{"message":"model not found"}}'), "model not found")


if __name__ == "__main__":
    unittest.main()
