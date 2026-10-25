"""Backlog intake plus SQLite-backed task lifecycle and runtime state."""
import re
import time
import pathlib
import secrets
from core import storage

ROOT = pathlib.Path(__file__).resolve().parent.parent
KV = re.compile(r"^- (\w+):\s*(.*)$")
ITEM = re.compile(r"^\s*-\s+\[(.)\] id=([\w-]+) \| kind=([\w-]+) \| (.*)$")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def on(v):
    return str(v).strip().lower() in ("on", "true", "yes", "1")


def kv_read(file):
    values = {}
    path = ROOT / file
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = KV.match(line)
            if match:
                values[match.group(1)] = match.group(2).strip()
    with storage.connect() as con:
        for row in con.execute("SELECT key, value FROM runtime_kv"):
            values[row["key"]] = row["value"]
    return values


def kv_update(file, **kv):
    # Runtime state belongs in SQLite, not tracked Markdown: switching Git branches
    # must not discard task progress or leave the working tree dirty.
    stamp = now()
    with storage.connect() as con:
        for key, value in kv.items():
            clean = str(value).replace("\n", " ")[:1000]
            con.execute(
                "INSERT INTO runtime_kv(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, clean, stamp),
            )


def criteria():
    return kv_read("CRITERIA.md")


def log(file, line):
    with open(ROOT / file, "a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def backlog_items():
    path = ROOT / "BACKLOG.md"
    out = []
    if not path.exists():
        return out
    with storage.connect() as con:
        saved = {row["id"]: dict(row) for row in con.execute("SELECT * FROM tasks")}
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ITEM.match(line)
        if not match:
            continue
        status, task_id, kind, text = match.groups()
        seen.add(task_id)
        item = {"status": status, "id": task_id, "kind": kind, "text": text}
        runtime = saved.get(task_id)
        if runtime:
            item.update(status=runtime["status"], attempts=runtime["attempts"],
                        phase=runtime["phase"], result=runtime["result"])
        else:
            item.update(attempts=0, phase="", result="")
        out.append(item)
    for task_id, runtime in saved.items():
        if task_id not in seen and runtime.get("text"):
            out.append({
                "status": runtime["status"], "id": task_id, "kind": runtime["kind"],
                "text": runtime["text"], "attempts": runtime["attempts"],
                "phase": runtime["phase"], "result": runtime["result"],
            })
    return out


def backlog_add(text, kind="complaint"):
    task_id = secrets.token_hex(3)
    safe_text = str(text).replace("\n", " ").strip()
    with storage.connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO tasks(id,status,attempts,phase,result,updated_at,kind,text) VALUES(?,?,?,?,?,?,?,?)",
            (task_id, " ", 0, "queued", "", now(), kind, safe_text),
        )
        con.execute(
            "INSERT INTO events(created_at,task_id,phase,event,detail) VALUES(?,?,?,?,?)",
            (now(), task_id, "queued", "task_added", safe_text[:500]),
        )
    return task_id


def backlog_set(task_id, status, phase=None, result=None):
    if status not in (" ", "~", "!", "x", "-"):
        raise ValueError(f"invalid task status: {status!r}")
    with storage.connect() as con:
        existing = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if existing:
            con.execute(
                "UPDATE tasks SET status=?, phase=?, result=?, updated_at=? WHERE id=?",
                (status, phase if phase is not None else existing["phase"],
                 str(result if result is not None else existing["result"])[:1000], now(), task_id),
            )
        else:
            con.execute(
                "INSERT INTO tasks(id,status,attempts,phase,result,updated_at) VALUES(?,?,?,?,?,?)",
                (task_id, status, 0, phase or "", str(result or "")[:1000], now()),
            )
        con.execute(
            "INSERT INTO events(created_at,task_id,phase,event,detail) VALUES(?,?,?,?,?)",
            (now(), task_id, phase or "", "status:" + status, str(result or "")[:500]),
        )


def task_begin(task_id, phase="starting"):
    with storage.connect() as con:
        con.execute(
            "INSERT INTO tasks(id,status,attempts,phase,result,updated_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status='~', attempts=tasks.attempts+1, "
            "phase=excluded.phase, result='', updated_at=excluded.updated_at",
            (task_id, "~", 1, phase, "", now()),
        )
        con.execute(
            "INSERT INTO events(created_at,task_id,phase,event,detail) VALUES(?,?,?,?,?)",
            (now(), task_id, phase, "attempt_started", ""),
        )


def task_phase(task_id, phase, detail=""):
    with storage.connect() as con:
        con.execute("UPDATE tasks SET phase=?, updated_at=? WHERE id=?", (phase, now(), task_id))
        con.execute(
            "INSERT INTO events(created_at,task_id,phase,event,detail) VALUES(?,?,?,?,?)",
            (now(), task_id, phase, "phase", str(detail)[:500]),
        )


def recover_interrupted():
    """Make tasks left in progress by a crash retryable instead of stuck forever."""
    # Migrate old Markdown-only in-progress entries as well as SQLite-backed tasks.
    legacy = [item["id"] for item in backlog_items() if item["status"] == "~" and item.get("attempts", 0) == 0]
    with storage.connect() as con:
        for task_id in legacy:
            con.execute(
                "INSERT INTO tasks(id,status,attempts,phase,result,updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status='!', phase='interrupted', updated_at=excluded.updated_at",
                (task_id, "!", 0, "interrupted", "Recovered legacy in-progress task.", now()),
            )
        rows = con.execute("SELECT id FROM tasks WHERE status='~'").fetchall()
        for row in rows:
            con.execute(
                "UPDATE tasks SET status='!', phase='interrupted', result=?, updated_at=? WHERE id=?",
                ("Previous run stopped before reporting a result.", now(), row["id"]),
            )
            con.execute(
                "INSERT INTO events(created_at,task_id,phase,event,detail) VALUES(?,?,?,?,?)",
                (now(), row["id"], "interrupted", "recovered_after_restart", ""),
            )
    return len(rows)


def next_open(max_retries=3):
    candidates = []
    for item in backlog_items():
        status = item["status"]
        if status == " ":
            candidates.append(item)
        elif status == "!" and int(item.get("attempts", 0)) < max_retries:
            candidates.append(item)
    candidates.sort(key=lambda item: (item["kind"] == "self", item.get("attempts", 0)))
    return candidates[0] if candidates else None


def render_state():
    values = kv_read("STATE.md")
    lines = ["# STATE (runtime values are stored locally in .selfagent/data.sqlite3)"]
    for key, value in sorted(values.items()):
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"
