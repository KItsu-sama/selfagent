import os, subprocess, sys, time
from core import state, improve
from core.state import ROOT


def _int(crit, key, default):
    try:
        return max(1, int(crit.get(key, default)))
    except (TypeError, ValueError):
        return default


def sleep_checking_stop(secs):
    for _ in range(max(1, int(secs))):
        if (ROOT / "STOP").exists():
            return
        time.sleep(1)


def restart_self():
    """Re-run with the new code. os.execv does not replace the process on Windows (the parent just
    exits and the new one detaches from the console), so there we wait for a child instead."""
    if os.name == "nt":
        sys.exit(subprocess.call([sys.executable] + sys.argv))
    os.execv(sys.executable, [sys.executable] + sys.argv)


def main_loop(router):
    recovered = state.recover_interrupted()
    if recovered:
        print(f"recovered {recovered} interrupted task(s)")
    print("agent loop started (touch STOP or run `python run.py stop` to halt)")
    last_reflect, backoff = 0.0, 0
    while True:
        if (ROOT / "STOP").exists():
            print("STOP file found, exiting")
            state.kv_update("STATE.md", status="stopped")
            return
        crit = state.criteria()
        interval = _int(crit, "interval_seconds", 30)
        item = state.next_open()
        try:
            if item:
                print(f"[{state.now()}] working on {item['id']} ({item['kind']}): {item['text'][:80]}")
                res = improve.improve(router, item)
                print("  ->", res.get("verdict"), res.get("why"))
                backoff = 0
                if res.get("restart"):
                    print("  core changed, restarting with new code")
                    restart_self()
                # outage / uncommitted changes: wait longer instead of hammering the providers
                sleep_checking_stop(max(interval, 120) if res.get("verdict") in ("paused", "blocked") else interval)
                continue
            # Idle: poll for new complaints every `interval`, but reflect (spends API quota) only now and then.
            if state.on(crit.get("auto_reflect")) and time.time() - last_reflect >= _int(crit, "reflect_every_seconds", 3600):
                last_reflect = time.time()
                improve.reflect(router)
            backoff = 0
        except Exception as e:
            print("  ERROR:", e)
            state.kv_update("STATE.md", status="error", error=str(e)[:200], updated=state.now())
            backoff = min(max(backoff * 2, 60), 1800)
            sleep_checking_stop(backoff)
            continue
        sleep_checking_stop(interval)
