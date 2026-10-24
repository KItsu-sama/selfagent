"""Minimal tool-calling loop. Fresh context per task (GSD: keep context lean, state lives in files)."""
import json, re
from core import tools as T


def parse_json(text):
    dec = json.JSONDecoder()
    for m in re.finditer(r"[\{\[]", text or ""):
        try:
            return dec.raw_decode(text[m.start():])[0]
        except ValueError:
            continue
    return None


def run_agent(router, system, task, stage="solve", max_steps=10):
    tools, docs = T.all_tools()
    tool_help = "\n".join(f"- {d}" for d in docs.values())
    head = [{"role": "system", "content":
             f"[STAGE:{stage}]\n{system}\n\nTools:\n{tool_help}\n\n"
             'Each turn reply with exactly ONE JSON object: {"tool": "<name>", "args": {...}} '
             'or, when finished, {"final": "<answer>"}.'},
            {"role": "user", "content": task}]
    tail = []
    for _ in range(max_steps):
        out = router.chat(head + tail[-8:], stage=stage, cache=False)
        obj = parse_json(out)
        if not isinstance(obj, dict):
            tail += [{"role": "assistant", "content": out},
                     {"role": "user", "content": "Invalid. Reply with ONE JSON object."}]
            continue
        if "final" in obj:
            f = obj["final"]
            return f if isinstance(f, str) else json.dumps(f)
        try:
            res = tools[obj.get("tool")](**(obj.get("args") or {}))
        except Exception as e:
            res = f"ERROR: {type(e).__name__}: {e}"
        tail += [{"role": "assistant", "content": out},
                 {"role": "user", "content": "RESULT:\n" + str(res)[:4000]}]
    return "(max steps reached)"
