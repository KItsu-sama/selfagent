"""Offline regression test for checkpointing and resuming a paused tool task."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import agent, task_session, tools


class FakeRouter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class AgentResumeTests(unittest.TestCase):
    def test_resume_keeps_prior_tool_result_after_provider_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(task_session, "SESSION_DIR", Path(tmp)), \
                 patch.object(tools, "all_tools", return_value=(
                     {"echo": lambda text: text},
                     {"echo": "echo(text) - return the supplied text"},
                 )), \
                 patch("core.agent.M.context_for", return_value=""):
                first_router = FakeRouter([
                    '{"tool":"echo","args":{"text":"checkpointed-result"}}',
                    RuntimeError("simulated provider outage"),
                ])
                with self.assertRaises(agent.TaskPaused) as paused:
                    agent.run_agent(
                        first_router, "test system", "resume this task",
                        max_steps=4, on_pause="raise", use_memory=False,
                    )

                session_id = paused.exception.session_id
                saved = task_session.load(session_id)
                self.assertEqual(saved["task"], "resume this task")
                self.assertIn("checkpointed-result", saved["tail"][-1]["content"])

                resume_router = FakeRouter(['{"final":"finished after resume"}'])
                answer = agent.run_agent(
                    resume_router, "ignored on resume", "ignored task",
                    resume_id=session_id, on_pause="raise", use_memory=False,
                )

                self.assertEqual(answer, "finished after resume")
                resumed_messages = resume_router.calls[0]
                self.assertTrue(any(
                    "checkpointed-result" in message.get("content", "")
                    for message in resumed_messages
                ))
                self.assertFalse(task_session.list_pending())


if __name__ == "__main__":
    unittest.main()
