"""Markdown-as-database helpers: CRITERIA, BACKLOG, STATE and append-only logs."""
import re, time, pathlib, secrets

ROOT = pathlib.Path(__file__).resolve().parent.parent
KV = re.compile(r"^- (\w+):\s*(.*)$")
ITEM = re.compile(r"^- \[(.)\] id=(\w+) \| kind=(\w+) \| (.*)$")


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def on(v):
    return str(v).strip().lower() in ("on", "true", "yes", "1")


def kv_read(file):
    d = {}
    for line in (ROOT / file).read_text(encoding="utf-8").splitlines():
        m = KV.match(line)
        if m:
            d[m.group(1)] = m.group(2).strip()
    return d


def kv_update(file, **kv):
    p = ROOT / file
    lines = p.read_text(encoding="utf-8").splitlines()
    for k, v in kv.items():
        v = str(v).replace("\n", " ")
        for i, l in enumerate(lines):
            m = KV.match(l)
            if m and m.group(1) == k:
                lines[i] = f"- {k}: {v}"
                break
        else:
            lines.append(f"- {k}: {v}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def criteria():
    return kv_read("CRITERIA.md")


def log(file, line):
    with open(ROOT / file, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def backlog_items():
    out = []
    for line in (ROOT / "BACKLOG.md").read_text(encoding="utf-8").splitlines():
        m = ITEM.match(line)
        if m:
            out.append({"status": m[1], "id": m[2], "kind": m[3], "text": m[4]})
    return out


def backlog_add(text, kind="complaint"):
    id_ = secrets.token_hex(3)
    log("BACKLOG.md", f"- [ ] id={id_} | kind={kind} | {text.replace(chr(10), ' ')}")
    return id_


def backlog_set(id_, status):
    p = ROOT / "BACKLOG.md"
    lines = p.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines):
        m = ITEM.match(l)
        if m and m[2] == id_:
            lines[i] = f"- [{status}] id={id_} | kind={m[3]} | {m[4]}"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def next_open(max_retries=3):
    state_data = kv_read("STATE.md")
    candidates = []

    for item in backlog_items():
        status = item["status"]

        if status == " ":
            candidates.append(item)
        elif status == "!":
            try:
                attempts = int(state_data.get(f"retry_{item['id']}", "0"))
            except ValueError:
                attempts = max_retries

            if attempts < max_retries:
                candidates.append(item)

    candidates.sort(key=lambda item: item["kind"] == "self")
    return candidates[0] if candidates else None