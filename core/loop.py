import os, sys, time
from core import state, improve, gitutil
from core.state import ROOT


def sleep_checking_stop(secs):
    for _ in range(max(1, secs)):
        if (ROOT / "STOP").exists():
            return
        time.sleep(1)


def main_loop(router):
    print("agent loop started (touch STOP or `python run.py stop` to halt)")
    while True:
        if (ROOT / "STOP").exists():
            print("STOP file found, exiting")
            state.kv_update("STATE.md", status="stopped")
            return
        crit = state.criteria()
        item = state.next_open()
        try:
            if item:
                print(f"[{state.now()}] working on {item['id']} ({item['kind']}): {item['text'][:80]}")
                res = improve.improve(router, item)
                print("  ->", res.get("verdict"), res.get("why"))
                if res.get("restart"):
                    print("  core changed, restarting with new code")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                continue
            if state.on(crit.get("auto_reflect")):
                improve.reflect(router)
        except Exception as e:
            print("  ERROR:", e)
            state.kv_update("STATE.md", status="error", error=str(e)[:200], updated=state.now())
            if item:
                state.backlog_set(item["id"], "!")
            try:
                gitutil.git("checkout", "-f", "main", check=False)
            except Exception:
                pass
        sleep_checking_stop(int(crit.get("interval_seconds", 30)))
