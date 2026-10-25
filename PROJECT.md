# PROJECT
A 24/7 self-improving agent. It works as a normal tool-using agent (`python run.py ask "..."`).
When the owner reports a weakness (`complain`) or suggests tech (`add-tech`), it researches,
integrates the tech as a plugin on a git branch, compares before/after, and keeps or reverts.

## Architecture
- core/router.py   free-API router: fallback, health, cooldown, cache
- core/storage.py  local SQLite runtime/task database (ignored by Git)
- core/memory.py   explicit persistent memory + lightweight keyword retrieval
- core/tools.py    built-in tools + plugin loader
- core/agent.py    JSON tool-calling loop (fresh context every task)
- core/bench.py    timed benchmark + optional probe task
- core/improve.py  complaint -> research -> plan(probe) -> branch -> implement -> compare -> keep/drop
- core/loop.py     the 24/7 loop (STOP file to halt)
- plugins/*.py     one capability per file (NAME, DESCRIPTION, run, selftest)

## Rules
- Owner's words decide direction. `CRITERIA.md` decides what "better" means and is editable at any time.
- One small change per branch. Every change is revertable (git).
- BACKLOG.md is the portable intake queue; newly queued tasks and runtime status live in `.selfagent/data.sqlite3` to avoid dirtying the working tree.
- Memory is local and explicit: use `remember`, `search_memory`, and `forget_memory`; never store secrets.
- Task failures are retried at most three times. The loop pauses between tasks and waits five minutes after errors.
