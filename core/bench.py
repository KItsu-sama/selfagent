import json, re, time
from core import agent
from core.state import ROOT

SYS = "You are a capable assistant agent. Use tools when needed. Be brief."


def _one(router, t):
    s = time.time()
    try:
        ans = agent.run_agent(router, SYS, t["prompt"], stage="solve", max_steps=8)
    except Exception as e:
        ans = f"ERROR {e}"
    return {"id": t["id"], "ok": bool(re.search(t["expect"], ans)),
            "seconds": round(time.time() - s, 2), "answer": ans[:200]}


def run(router, extra=None):
    tasks = json.loads((ROOT / "bench/tasks.json").read_text(encoding="utf-8"))
    res = [_one(router, t) for t in tasks]
    out = {"passed": sum(r["ok"] for r in res), "total": len(res),
           "seconds": round(sum(r["seconds"] for r in res), 2), "tasks": res}
    if extra:
        p = _one(router, {"id": "probe", **extra})
        out["probe"], out["probe_answer"] = p["ok"], p["answer"]
    return out
