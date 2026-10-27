import json, re, time
from core import agent
from core.state import ROOT

SYS = "You are a capable assistant agent. Use tools when needed. Be brief."


def _one(router, t, system=SYS, max_steps=8):
    s = time.time()
    try:
        # use_memory=False: a benchmark must not change with what happens to be in memory.
        # on_pause="raise": a provider outage is not a wrong answer, so it must not count as a failure.
        ans = agent.run_agent(router, system, t["prompt"], stage="solve", max_steps=max_steps,
                              on_pause="raise", use_memory=False)
    except agent.TaskPaused as tp:
        if tp.kind == "provider":
            raise
        ans = f"ERROR step limit: {tp}"
    except Exception as e:
        ans = f"ERROR {e}"
    return {"id": t["id"], "ok": bool(re.search(t["expect"], ans)), "error": ans.startswith("ERROR"),
            "seconds": round(time.time() - s, 2), "answer": ans[:200]}


def run_probe(router, probe):
    """Only the acceptance probe (cheap on free-tier quota)."""
    r = _one(router, {"id": "probe", **probe}, system="You are a concise tool-using assistant.", max_steps=4)
    return {"passed": int(r["ok"]), "total": 1, "seconds": r["seconds"], "tasks": [r],
            "probe": r["ok"], "probe_answer": r["answer"]}


def run(router, extra=None):
    tasks = json.loads((ROOT / "bench/tasks.json").read_text(encoding="utf-8"))
    res = [_one(router, t) for t in tasks]
    out = {"passed": sum(r["ok"] for r in res), "total": len(res),
           "seconds": round(sum(r["seconds"] for r in res), 2), "tasks": res}
    if extra:
        p = _one(router, {"id": "probe", **extra})
        out["probe"], out["probe_answer"] = p["ok"], p["answer"]
    return out
