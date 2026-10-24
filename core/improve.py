"""complaint / tech suggestion -> research -> plan(probe) -> branch -> implement -> compare -> keep|drop"""
import json, re, subprocess, sys, time
from core import state, gitutil, agent
from core.state import ROOT

RESEARCH_SYS = ("You are the research module of a self-improving agent. Find 2-4 concrete, free, maintained "
                "tools/libraries/techniques that fix the reported weakness. Use web_search and fetch. Prefer pip-installable, "
                "no paid keys. Final answer = JSON list: [{\"name\":..,\"why\":..,\"how\":..,\"source\":url}].")
IMPL_SYS = ("Prefer str_replace over write_file when editing existing files. You are the self-upgrade module of an agent living in this repo. Integrate the chosen tech as a plugin: create "
            "plugins/<name>.py exposing NAME, DESCRIPTION (one line showing how to call it), run(**kwargs), selftest(). "
            "See plugins/README.md. Use pip_install if a package is needed. selftest() must pass. Keep the change small. "
            "Verify with shell: python run.py selftest. Finish with a one-line summary.")


def project():
    return (ROOT / "PROJECT.md").read_text(encoding="utf-8")[:2500]


def sub_bench(router, extra=None):
    # Use one focused acceptance probe rather than replaying every LLM benchmark task.
    # If planning failed to produce a valid probe, judge() rejects the task without extra calls.
    if not extra:
        return {"passed": 0, "total": 0, "seconds": 0.0, "tasks": [], "probe": None}
    if extra:
        started = time.time()
        answer = agent.run_agent(
            router, "You are a concise tool-using assistant.", extra["prompt"],
            stage="solve", max_steps=4
        )
        ok = bool(re.search(extra["expect"], answer))
        seconds = round(time.time() - started, 2)
        task = {"id": "probe", "ok": ok, "seconds": seconds, "answer": answer[:200]}
        return {"passed": int(ok), "total": 1, "seconds": seconds, "tasks": [task],
                "probe": ok, "probe_answer": task["answer"]}



def judge(before, after, probe, crit):
    if not probe:
        return False, ["plan did not provide a valid acceptance probe; refusing an unverified change"]
    why, ok = [], True
    if probe and before.get("probe"):
        return False, ["probe already passed before the change: nothing to improve"]
    if after["passed"] < before["passed"]:
        ok = False
        why.append(f"bench regressed {before['passed']} -> {after['passed']}")
    flipped = bool(probe and after.get("probe"))
    if probe and not after.get("probe"):
        ok = False
        why.append("probe still failing")
    if ok and crit.get("primary", "speed") == "speed" and not flipped:
        tol = float(crit.get("tolerance", 0.25))
        b, a = before["seconds"], after["seconds"]
        if a > b * (1 + tol) and a - b > 1.0:
            ok = False
            why.append(f"slower {b}s -> {a}s")
    if ok:
        why.append("probe went fail->pass" if flipped else "no regression")
    return ok, why


def _candidates(router, kind, text):
    if kind == "tech":
        return [{"name": text, "why": "suggested by owner", "how": "integrate as plugin", "source": ""}]
    raw = agent.run_agent(router, RESEARCH_SYS, f"Reported weakness: {text}\n\nProject:\n{project()}",
                          stage="research", max_steps=10)
    lst = agent.parse_json(raw)
    if isinstance(lst, list) and lst and all(isinstance(x, dict) for x in lst):
        return lst[:4]
    return [{"name": "unstructured", "why": raw[:300], "how": raw[:600], "source": ""}]


def _pick(router, cands, text):
    if len(cands) == 1:
        return cands[0]
    out = router.chat([{"role": "system", "content": '[STAGE:pick]\nPick the single best candidate: small, free, maintained, '
                        'easy to add as a plugin. Reply JSON {"choice": <index>}'},
                       {"role": "user", "content": f"Problem: {text}\n{json.dumps(cands)}"}], stage="pick", cache=False)
    obj = agent.parse_json(out)
    try:
        return cands[int(obj["choice"])]
    except Exception:
        return cands[0]


def _plan(router, text, cand):
    out = router.chat([{"role": "system", "content": '[STAGE:plan]\nWrite ONE acceptance test (a "probe") that an agent with '
                        'the new capability should pass but would fail without it. Reply JSON: {"summary": "...", '
                        '"probe": {"prompt": "<task for the agent>", "expect": "<python regex the answer must match>"}}'},
                       {"role": "user", "content": f"Weakness: {text}\nChosen tech: {json.dumps(cand)}"}],
                      stage="plan", cache=False)
    obj = agent.parse_json(out) or {}
    pr = obj.get("probe")
    try:
        if pr and pr.get("prompt") and pr.get("expect"):
            re.compile(pr["expect"])
            return obj.get("summary", ""), {"prompt": pr["prompt"], "expect": pr["expect"]}
    except Exception:
        pass
    return obj.get("summary", ""), None


def improve(router, item):
    id_, kind, text = item["id"], item["kind"], item["text"]
    crit = state.criteria()
    gitutil.ensure_clean()
    base = gitutil.ensure()
    branch = f"agent/{id_}"
    state.task_begin(id_, "research")
    state.kv_update("STATE.md", status="working", item=id_, task=text[:120], phase="research", updated=state.now())
    result = {"kept": False, "restart": False}

    cands = _candidates(router, kind, text)
    cand = _pick(router, cands, text)
    (ROOT / ".selfagent" / "research").mkdir(parents=True, exist_ok=True)
    (ROOT / f".selfagent/research/{id_}.md").write_text(f"# {text}\n\n```json\n{json.dumps(cands, indent=2)}\n```\n\nPicked: {cand.get('name')}\n",
                                             encoding="utf-8")
    state.task_phase(id_, "plan")
    state.kv_update("STATE.md", phase="plan")
    summary, probe = _plan(router, text, cand)
    state.task_phase(id_, "baseline")
    state.kv_update("STATE.md", phase="baseline")
    before = sub_bench(router, probe)
    gitutil.ensure_clean()
    head_before = gitutil.git("rev-parse", "HEAD")

    ok, why, after, smoke = False, [], None, ""
    try:
        gitutil.git("checkout", "-b", branch)
        state.task_phase(id_, "implement")
        state.kv_update("STATE.md", phase="implement")
        agent.run_agent(router, IMPL_SYS, f"Weakness: {text}\nChosen tech: {json.dumps(cand)}\nPlan: {summary}",
                        stage="implement", max_steps=8)
        s = subprocess.run([sys.executable, "run.py", "selftest"], cwd=ROOT, capture_output=True, text=True, timeout=600)
        smoke = (s.stdout + s.stderr)[-400:]
        gitutil.commit_all(f"implement {id_}")
        changed = gitutil.changed_files(head_before, "HEAD")
        from core.tools import protected_paths
        hit = [f for f in changed if any(f == x or f.startswith(x + "/") for x in protected_paths())]
        if not changed:
            why = ["agent made no changes"]
        elif hit:
            why = ["touched protected files: " + ", ".join(hit)]
        elif s.returncode:
            why = ["selftest failed: " + smoke.replace("\n", " ")]
        else:
            state.task_phase(id_, "compare")
            state.kv_update("STATE.md", phase="compare")
            after = sub_bench(router, probe)
            ok, why = judge(before, after, probe, crit)
            if state.on(crit.get("human_judge")):
                print(f"\n[{id_}] {text}\nBEFORE: {before['passed']}/{before['total']} {before['seconds']}s probe={before.get('probe')}"
                      f"\nAFTER:  {after['passed']}/{after['total']} {after['seconds']}s probe={after.get('probe')}\nauto-verdict: {ok} {why}")
                try:
                    ok = input("keep this change? [y/n] ").strip().lower() == "y"
                    state.log("JUDGEMENTS.md", f"- {state.now()} | {id_} | {'keep' if ok else 'drop'} | {text} | {cand.get('name')} | {why}")
                except EOFError:
                    pass
    except Exception as exc:
        gitutil.git("checkout", base, check=False)
        gitutil.git("branch", "-D", branch, check=False)
        state.backlog_set(id_, "!", phase="failed", result=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        current = gitutil.git("rev-parse", "--abbrev-ref", "HEAD", check=False)
        if current and current != base:
            gitutil.git("checkout", base, check=False)

    if ok:
        files = gitutil.changed_files(base, branch)
        gitutil.git("merge", "--no-ff", branch, "-m", f"keep {id_}: {cand.get('name')}")
        gitutil.git("tag", f"good-{id_}")
        result["kept"] = True
        result["restart"] = any(f.startswith("core/") or f == "run.py" for f in files)
    gitutil.git("branch", "-D", branch, check=False)

    verdict = "kept" if ok else "dropped"
    state.backlog_set(id_, "x" if ok else "-", phase="done" if ok else "dropped", result="; ".join(why))
    delta = (f"bench {before['passed']}/{before['total']} {before['seconds']}s -> "
             f"{after['passed']}/{after['total']} {after['seconds']}s" if after else "n/a")
    state.log("TECH.md", f"- {state.now()} | {verdict} | {cand.get('name')} | for: {text[:80]} | {delta} | {'; '.join(why)}")
    if not ok:
        state.log("LESSONS.md", f"- {state.now()} | {id_} | tried {cand.get('name')} for '{text[:80]}' | dropped: {'; '.join(why)}")
    state.kv_update("STATE.md", status="idle", phase="-", last=f"{id_} {verdict}: {'; '.join(why)}"[:200], updated=state.now())
    gitutil.commit_all(f"result {id_} {verdict}")
    result.update(verdict=verdict, why=why, tech=cand.get("name"))
    return result


def reflect(router):
    """Run the bench; failing tasks become self-notes in BACKLOG.md (no duplicates)."""
    r = bench.run(router)
    existing = " ".join(i["text"] for i in state.backlog_items())
    for t in r["tasks"]:
        tag = f"bench task '{t['id']}'"
        if not t["ok"] and tag not in existing:
            state.backlog_add(f"{tag} fails (answer: {t['answer'][:80]})", kind="self")
    return r
