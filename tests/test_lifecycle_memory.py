"""Offline regression tests for lifecycle recovery and persistent memory."""
import pathlib
import tempfile
import unittest

from core import memory, state, storage


class LifecycleMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.old_root = state.ROOT
        self.old_data_dir = storage.DATA_DIR
        self.old_db_path = storage.DB_PATH
        state.ROOT = self.root
        storage.DATA_DIR = self.root / ".selfagent"
        storage.DB_PATH = storage.DATA_DIR / "data.sqlite3"
        (self.root / "BACKLOG.md").write_text("# test backlog\n", encoding="utf-8")

    def tearDown(self):
        state.ROOT = self.old_root
        storage.DATA_DIR = self.old_data_dir
        storage.DB_PATH = self.old_db_path
        self.tmp.cleanup()

    def test_parses_indented_existing_backlog_items(self):
        (self.root / "BACKLOG.md").write_text(
            "# test backlog\n  - [ ] id=c24e29 | kind=tech | test item\n",
            encoding="utf-8",
        )
        items = state.backlog_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "c24e29")

    def test_retry_limit_stops_after_three_attempts(self):
        task_id = state.backlog_add("bounded retry test", "complaint")
        for attempt in range(3):
            item = state.next_open()
            self.assertIsNotNone(item)
            self.assertEqual(item["id"], task_id)
            state.task_begin(task_id, "test")
            state.backlog_set(task_id, "!", phase="failed", result=f"failure {attempt + 1}")
        self.assertIsNone(state.next_open())

    def test_interrupted_task_becomes_retryable(self):
        task_id = state.backlog_add("crash recovery test", "complaint")
        state.task_begin(task_id, "implement")
        self.assertEqual(state.recover_interrupted(), 1)
        item = next(i for i in state.backlog_items() if i["id"] == task_id)
        self.assertEqual(item["status"], "!")
        self.assertEqual(item["phase"], "interrupted")

    def test_memory_upsert_search_and_forget(self):
        memory.remember("project.preference", "Prefer local and free tools", "project preferences")
        memory.remember("project.preference", "Prefer local, free, low-call tools", "updated")
        matches = memory.search("low-call tools")
        self.assertEqual(matches[0]["memory_key"], "project.preference")
        self.assertIn("low-call", memory.context_for("low-call"))
        self.assertIn("Deleted", memory.forget("project.preference"))
        self.assertEqual(memory.search("low-call"), [])


if __name__ == "__main__":
    unittest.main()
