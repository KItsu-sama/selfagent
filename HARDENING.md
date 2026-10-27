# Hardening pass: what was found and fixed

Scope: flaws beyond the four already known (sandboxing, weak benchmark, learning from judgments, README/real-provider validation).
Every item below was reproduced against the original `core/` before it was fixed.

| # | Flaw (reproduced) | Fix | File |
|---|---|---|---|
| 1 | `fetch("file:///...")` read any file on the machine, skipping the project jail. Also reachable: `localhost`, LAN, cloud-metadata IPs, redirects into them. | http(s) only; every resolved address must be public; redirects re-checked; 2 MB read cap. `SELFAGENT_ALLOW_PRIVATE_URLS=1` opts out. | `core/tools.py` |
| 2 | `read_file(".env")` returned your API keys; `.selfagent/`, `.git/`, `providers.json` were readable too. A web page seen in chat could ask for them and leak them through a search query. | Secrets/runtime folders are unreadable and unwritable by every agent tool. | `core/tools.py` |
| 3 | The chat's `write_file` could write `plugins/*.py` (executed with shell rights by the loop at next load), `providers.json` (`base_url` swap = key exfiltration) or `core/*.py`. This defeated "shell disabled in chat". | Chat writes only inside git-ignored `workspace/`; chat reads the project but never secrets. Prompt-injection warning added to every chat prompt. | `core/tools.py`, `core/agent.py` |
| 4 | The agent could edit the code that enforces its own limits. | `core/tools.py`, `core/router.py`, `core/gitutil.py`, `core/improve.py` are protected by default (merged with `protected:` in CRITERIA.md). Remove them from `DEFAULT_PROTECTED` by hand if you want self-edits there. | `core/tools.py` |
| 5 | API keys were sent to any `base_url`, including plain `http://`; raw keys in `providers.json` were silently accepted (and committed by `git add -A`). | https only (or localhost for local models); loud warning for raw keys. | `core/router.py` |
| 6 | Memory (writable from chat, i.e. from untrusted web content) was injected into the shell-capable research/implement prompts and into benchmarks. | Memory and its tools exist only in the `solve`/`chat` stages; benchmarks and probes run without memory (so scores are reproducible). | `core/agent.py`, `core/bench.py` |
| 7 | A provider outage inside `run_agent` came back as a normal answer string. Research then "found" an unstructured candidate made of the error text; probes counted as failures; items were dropped and **lessons were written about techniques that never ran**. | `run_agent(..., on_pause="raise")` raises `TaskPaused`; the pipeline re-queues the item without spending a retry or writing a lesson. Default (`"return"`) is unchanged, so `ask`/`resume-task` behave as before. | `core/agent.py`, `core/improve.py`, `core/state.py`, `core/router.py` |
| 8 | Any file in the working tree (e.g. `hello.txt` from the chat example prompt) made `ensure_clean()` raise on every cycle, **before** the attempt counter ran: the loop stalled forever, silently. Chat files could also be swept into `git add -A` on an agent branch and deleted with it. | Owner changes now give verdict `blocked` (re-queued, no retry spent, loop waits). `workspace/` and `.selfagent/` are ignored by the clean check and never committed. | `core/gitutil.py`, `core/improve.py` |
| 9 | After a crash the repo stayed on `agent/<id>` with a dirty tree; `ensure_clean()` ran before the recovery in `ensure()`, so recovery never happened. `main` was hard-coded. | Recovery first, then the clean check; stale `agent/*` branches removed; `main`/`master` detected. Any failure or Ctrl+C abandons the branch cleanly. | `core/gitutil.py`, `core/improve.py` |
| 10 | The probe ran **inside the already-running process**, so edits to `core/` were never exercised before merging. | Probe (and optional full bench) runs in a fresh process: `python -m core.probe_cli`. | `core/probe_cli.py`, `core/improve.py` |
| 11 | `reflect()` raised `NameError` (`bench` not imported): `auto_reflect: on` never worked. Idle sleep was hard-wired to 300 s (a new complaint waited up to 5 min); the "loop started" message printed only after a crash recovery; `os.execv` restart is broken on Windows. | Fixed imports; idle polling = `interval_seconds`; reflect has its own `reflect_every_seconds` (default 3600) so it can't burn quota; Windows-safe restart; errored bench tasks are not turned into backlog notes. | `core/improve.py`, `core/loop.py` |
| 12 | Implementation had an 8-step cap; hitting it was treated as a finished attempt. `shell`/`pip` could hang on interactive prompts. | `implement_steps` (default 16); step limit is reported as its own reason; stdin is closed for subprocesses. | `core/improve.py`, `core/tools.py` |

## Apply

1. Copy the files in this zip over your repo (same paths).
2. Add to `.gitignore`: `.selfagent/`, `workspace/`, `.env`, `providers.json`.
3. Optional `CRITERIA.md` lines: `- bench_mode: probe` (or `full`), `- implement_steps: 16`, `- reflect_every_seconds: 3600`.
4. `chat_ui.py`: change the SYSTEM sentence "File tools operate inside the selfagent project folder only" to "File tools write only inside the workspace/ folder (paths are relative to it)".
5. Run `python tests/test_hardening.py` (15 offline tests, no API keys).

## Things you will notice

- Chat files now land in `workspace/` (e.g. `workspace/hello.txt`), not the project root.
- `bench_mode: probe` stays the default (your quota-saving choice). In that mode the regression and speed checks cannot fire, so `primary: speed` has no effect; the verdict says so. Use `bench_mode: full` to enable them.

## Not changed / limits

- DNS rebinding between the address check and the request is not covered; a container with no LAN access is the real fix (your item 1).
- `state.kv_read` merges runtime SQLite values over the file and ignores its `file` argument, so `criteria` and `STATE` share one namespace. Left alone because other code may rely on it.
- I could not see `run.py`, `chat_ui.py` source beyond the GitHub page, `plugins/`, `tests/`, or the workflows, and nothing was run against a real provider: validated with the offline mock only.
