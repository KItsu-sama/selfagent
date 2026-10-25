"""Local snapshots for tasks paused by provider failures.

Snapshots stay under .selfagent/ (git-ignored) and contain prompts/tool results,
never provider API keys. They let a task resume after credentials/quota are fixed.
"""
import json
import pathlib
import secrets
from datetime import datetime, timezone

from core.state import ROOT

SESSION_DIR = ROOT / ".selfagent" / "pending_tasks"


def _path(session_id):
    if not session_id or not all(c.isalnum() or c in "-_" for c in session_id):
        raise ValueError("Invalid task session ID")
    return SESSION_DIR / (session_id + ".json")


def save(snapshot, session_id=None):
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_id = session_id or secrets.token_hex(6)
    payload = dict(snapshot)
    payload["session_id"] = session_id
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _path(session_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return session_id


def load(session_id):
    path = _path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"Paused task '{session_id}' was not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def complete(session_id):
    _path(session_id).unlink(missing_ok=True)


def list_pending():
    if not SESSION_DIR.exists():
        return []
    items = []
    for path in sorted(SESSION_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return items
