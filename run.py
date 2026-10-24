#!/usr/bin/env python3
"""Self-improving agent CLI.  python run.py -h"""
import sys, os, json, argparse, pathlib, shutil, subprocess, tempfile

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def load_env():
    f = ROOT / ".env"
    if f.exists():
        for l in f.read_text().splitlines():
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, v = l.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


load_env()
from core import state, tools, agent, bench, improve, loop, gitutil, memory  # noqa: E402
from core.router import Router  # noqa: E402

SYS = "You are a capable agent living in a git repo you can improve. Use tools when needed. Be concise."


def main():
    ap = argparse.ArgumentParser(description="24/7 self-improving agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("loop", help="run 24/7 (STOP file halts it)")
    sub.add_parser("once", help="process the next backlog item, then exit")
    sp = sub.add_parser("complain", help="tell it what is lacking"); sp.add_argument("text")
    sp = sub.add_parser("add-tech", help="suggest tech to add"); sp.add_argument("text")
    sp = sub.add_parser("ask", help="use it as an agent"); sp.add_argument("text", nargs="?")
    sp = sub.add_parser("bench"); sp.add_argument("--json", action="store_true"); sp.add_argument("--extra")
    sub.add_parser("selftest", help="run every plugin's selftest")
    sub.add_parser("reflect", help="bench now; failures become backlog notes")
    sub.add_parser("status"); sub.add_parser("stop"); sub.add_parser("resume")
    sp = sub.add_parser("memory", help="inspect or manage local persistent memory")
    sp.add_argument("action", choices=("list", "search", "forget"))
    sp.add_argument("value", nargs="?")
    sub.add_parser("demo", help="offline end-to-end test with a fake LLM in a temp copy")
    a = ap.parse_args()

    if a.cmd == "complain":
        print("added", state.backlog_add(a.text, "complaint"))
    elif a.cmd == "add-tech":
        print("added", state.backlog_add(a.text, "tech"))
    elif a.cmd == "status":
        print(state.render_state())
        print("open items:")
        for i in state.backlog_items():
            if i["status"] in (" ", "~", "!"):
                print(f"  [{i['status']}] {i['id']} {i['kind']} attempts={i.get('attempts', 0)} phase={i.get('phase', '')}: {i['text'][:90]}")
                if i.get("result"):
                    print(f"      last result: {i['result'][:160]}")
    elif a.cmd == "stop":
        (ROOT / "STOP").write_text("stop"); print("STOP written")
    elif a.cmd == "resume":
        (ROOT / "STOP").unlink(missing_ok=True); print("STOP removed")
    elif a.cmd == "selftest":
        errs = []
        plugs = tools.load_plugins(errs)
        bad = len(errs)
        import py_compile, importlib
        for f in sorted((ROOT / "core").glob("*.py")) + [ROOT / "run.py"]:
            try:
                py_compile.compile(str(f), doraise=True)
            except Exception as e:
                print("FAIL compile", f.name, e); bad += 1
        for m in ("state", "gitutil", "tools", "agent", "bench", "improve", "loop", "router"):
            try:
                importlib.import_module("core." + m)
            except Exception as e:
                print("FAIL import core." + m, e); bad += 1
        for f, e in errs:
            print("FAIL import", f, e)
        for n, p in plugs.items():
            try:
                p["mod"].selftest(); print("ok", n)
            except Exception as e:
                print("FAIL", n, e); bad += 1
        sys.exit(1 if bad else 0)
    elif a.cmd == "bench":
        r = bench.run(Router(), json.loads(a.extra) if a.extra else None)
        if a.json:
            print(json.dumps(r))
        else:
            for t in r["tasks"]:
                print(("PASS" if t["ok"] else "FAIL"), t["id"], f"{t['seconds']}s", t["answer"][:60])
            print(f"{r['passed']}/{r['total']} in {r['seconds']}s")
    elif a.cmd == "ask":
        r = Router()
        if a.text:
            print(agent.run_agent(r, SYS, a.text))
        else:
            while True:
                try:
                    q = input("you> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if q:
                    print(agent.run_agent(r, SYS, q))
    elif a.cmd == "memory":
        if a.action == "list":
            rows = memory.search("", limit=10)
            print("\n".join(f"- {m['memory_key']}: {m['content']}" for m in rows) or "No saved memories.")
        elif a.action == "search":
            rows = memory.search(a.value or "", limit=10)
            print("\n".join(f"- {m['memory_key']}: {m['content']}" for m in rows) or "No matching memories.")
        else:
            if not a.value:
                ap.error("memory forget requires the exact memory key")
            print(memory.forget(a.value))
    elif a.cmd == "once":
        state.recover_interrupted()
        item = state.next_open()
        print(improve.improve(Router(), item) if item else "backlog empty")
    elif a.cmd == "reflect":
        improve.reflect(Router()); print("done; see BACKLOG.md")
    elif a.cmd == "loop":
        loop.main_loop(Router())
    elif a.cmd == "demo":
        tmp = pathlib.Path(tempfile.mkdtemp()) / "selfagent"
        shutil.copytree(ROOT, tmp, ignore=shutil.ignore_patterns(".git", ".cache", ".deps", "__pycache__", "notes", "STOP", ".env"))
        env = {**os.environ, "AGENT_MOCK": "1"}
        for args in (["complain", "I cannot greet people with a custom tool"], ["once"], ["status"]):
            print("$ python run.py", *args)
            subprocess.run([sys.executable, "run.py", *args], cwd=tmp, env=env)
        print("\n--- TECH.md ---\n" + (tmp / "TECH.md").read_text())
        print("demo dir:", tmp)


if __name__ == "__main__":
    main()
