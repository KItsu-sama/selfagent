"""Run an acceptance probe (optionally plus the fixed bench) in a FRESH Python process.

    python -m core.probe_cli --probe '{"prompt": "...", "expect": "regex"}' [--full]

Why a fresh process: the loop already has the old core/*.py imported. Judging a branch inside that
process would never execute edits to core/, so a broken core change could pass. Prints ONE JSON line.
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _load_env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--full", action="store_true", help="also run bench/tasks.json")
    a = ap.parse_args()
    _load_env()
    from core import agent, bench
    from core.router import Router
    probe = json.loads(a.probe)
    try:
        router = Router()
        out = bench.run(router, probe) if a.full else bench.run_probe(router, probe)
    except agent.TaskPaused as tp:
        print(json.dumps({"paused": True, "reason": str(tp), "kind": tp.kind}))
        return 3
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
