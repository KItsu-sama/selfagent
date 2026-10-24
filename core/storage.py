"""Small local SQLite store for runtime state and persistent memory."""
import pathlib
import sqlite3
from contextlib import contextmanager

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / ".selfagent"
DB_PATH = DATA_DIR / "data.sqlite3"


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=10000")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS runtime_kv (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, memory_key TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                task_id TEXT NOT NULL DEFAULT '', phase TEXT NOT NULL DEFAULT '',
                event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
            );
        """)
        yield con
        con.commit()
    finally:
        con.close()
