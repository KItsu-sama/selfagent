"""Offline tests for resumable local task snapshots."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import task_session


class TaskSessionTests(unittest.TestCase):
    def test_save_load_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(task_session, "SESSION_DIR", Path(tmp)):
                snapshot = {
                    "task": "research and continue",
                    "stage": "solve",
                    "head": [{"role": "user", "content": "original request"}],
                    "tail": [{"role": "assistant", "content": "previous result"}],
                    "step": 3,
                    "max_steps": 10,
                }
                session_id = task_session.save(snapshot)
                restored = task_session.load(session_id)
                self.assertEqual(restored["task"], snapshot["task"])
                self.assertEqual(restored["tail"], snapshot["tail"])
                self.assertEqual(restored["step"], 3)
                self.assertEqual(task_session.list_pending()[0]["session_id"], session_id)
                task_session.complete(session_id)
                self.assertEqual(task_session.list_pending(), [])


if __name__ == "__main__":
    unittest.main()
