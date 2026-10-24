"""Offline fake LLM so the whole pipeline can be tested without API keys (AGENT_MOCK=1)."""
import json

PLUGIN = '''NAME = "hello_demo"
DESCRIPTION = "hello_demo(name) - returns a greeting"
def run(name=""): return ("hello " + name).strip()
def selftest(): assert "hello" in run()
'''


def reply(stage, messages):
    sysm = messages[0]["content"]
    n = len(messages)
    if stage == "solve":
        q = messages[1]["content"]
        if "17*23" in q: a = "391"
        elif "list_dir" in q: a = "yes"
        elif "git --version" in q: a = "git version 2.x"
        elif "capital of France" in q: a = "Paris"
        elif "notes/bench.txt" in q: a = "ok"
        elif "hello_demo" in sysm: a = "hello world"
        else: a = "I can't do that."
        return json.dumps({"final": a})
    if stage == "research":
        return json.dumps({"final": json.dumps([{"name": "hello_demo", "why": "demo", "how": "plugin", "source": ""}])})
    if stage == "pick":
        return json.dumps({"choice": 0})
    if stage == "plan":
        return json.dumps({"summary": "add hello_demo plugin",
                           "probe": {"prompt": "Greet me using the hello_demo tool.", "expect": "(?i)hello"}})
    if stage == "implement":
        if n <= 2:
            return json.dumps({"tool": "write_file", "args": {"path": "plugins/hello_demo.py", "content": PLUGIN}})
        return json.dumps({"final": "added plugins/hello_demo.py"})
    if stage == "reflect":
        return json.dumps({"final": "ok"})
    return json.dumps({"final": "mock"})
