"""Small, explicit persistent memory backed by local SQLite (no embeddings/API needed)."""
import re
from core import storage
from core.state import now


def remember(key, content, tags=""):
    key = str(key).strip()
    content = str(content).strip()
    if not key or not content:
        raise ValueError("key and content are required")
    if len(key) > 160 or len(content) > 6000 or len(str(tags)) > 500:
        raise ValueError("memory entry is too long")
    stamp = now()
    with storage.connect() as con:
        con.execute(
            "INSERT INTO memories(memory_key,content,tags,created_at,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(memory_key) DO UPDATE SET content=excluded.content, tags=excluded.tags, "
            "updated_at=excluded.updated_at",
            (key, content, str(tags), stamp, stamp),
        )
    return f"Saved memory '{key}'."


def forget(key):
    with storage.connect() as con:
        cur = con.execute("DELETE FROM memories WHERE memory_key=?", (str(key).strip(),))
    return f"Deleted memory '{key}'." if cur.rowcount else f"No memory found with key '{key}'."


def search(query="", limit=5):
    words = [w.lower() for w in re.findall(r"[\w-]{2,}", str(query)) if w.lower() not in {
        "what", "when", "where", "which", "with", "from", "that", "this", "have", "about",
        "please", "could", "would", "should", "remember", "memory"
    }]
    limit = max(1, min(int(limit), 10))
    with storage.connect() as con:
        rows = con.execute(
            "SELECT memory_key,content,tags,updated_at FROM memories ORDER BY updated_at DESC"
        ).fetchall()
    ranked = []
    for row in rows:
        haystack = f"{row['memory_key']} {row['content']} {row['tags']}".lower()
        score = sum(1 for word in words if word in haystack)
        if not words or score:
            ranked.append((score, dict(row)))
    ranked.sort(key=lambda pair: (pair[0], pair[1]["updated_at"]), reverse=True)
    return [row for _, row in ranked[:limit]]


def context_for(query, limit=3, max_chars=1800):
    matches = search(query, limit=limit)
    if not matches:
        return ""
    lines = ["Relevant saved memory (may be outdated; follow the user's current instructions):"]
    used = 0
    for item in matches:
        line = f"- {item['memory_key']}: {item['content']}"
        if item["tags"]:
            line += f" [tags: {item['tags']}]"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines) if len(lines) > 1 else ""
