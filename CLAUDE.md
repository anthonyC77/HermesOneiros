# oneiros — an agent that keeps curated memory, recalls its sessions, and dreams

## Commands
- Install from [oneiros/](oneiros/): `pip install -e ".[dev]"` — `--no-deps` if a stale console-script shim breaks it.
- What is wired and what is missing: `python -m oneiros doctor`. Start here.
- Tests: `python -m pytest` (245). One file: `python -m pytest tests/test_sessions.py -k fts`.
- Use: `python -m oneiros sessions index`, `python -m oneiros memory show`.
- Never the bare `oneiros` script: pip cannot write the shim here, so the plugin commands fail when replayed by hand.
- Harness guardrails: `python .claude/hooks/test_hooks.py` (28 probes).

## Landmarks
- [oneiros/SPEC.md](oneiros/SPEC.md) is the spec, [oneiros/TASKS.md](oneiros/TASKS.md) the 36 tasks (T01–T36, lots L0–L6). Read the task first; code cites clauses by number, never restates them.
- Both documents are in French. Source, docstrings, comments and tests are in English.
- `src/oneiros/`: `config.py` (every path and setting resolves here), `cli.py`, `memory/` (store, guard, gate, render), `sessions/` (reader, index, query), `mcp_server.py` — stdlib only, imports nothing from the package.
- State lives outside the repo, under `~/.claude/oneiros` — move it with `ONEIROS_HOME`; `config.py` owns the resolution order.
- [.claude/](.claude/): agents (testeur, codeur, relecteur), skills (`/cadrer`, `/livrer`, `/etat`), path-scoped rules, and the hooks that enforce the rules below.
- Status: L0–L2 done; L3–L6 (skills, SDK runners, NREM, REM) not started — table in [oneiros/README.md](oneiros/README.md).

## Rules for this repo
- No Hermès code enters [oneiros/](oneiros/) — it supplies a requirements document, not a checkout. A reference to Hermès names a documented behaviour, never a module to port; there is no local copy to grep.
- The prompt cache is sacred: nothing mutates past context or the system prompt mid-conversation. A write lands on disk at once, and shows in the prompt at session *n+1*.
- A fact is never dreamed. The dream pass has no write path to memory — enforced by a test that walks the call graph, not by a prompt instruction.
- The spec is never rewritten to make code pass. If it is wrong, say so and stop.
- Two directories are not ours: the harness owns its skills directory; the transcript history is read-only input, **never created** — creating it makes a misconfiguration look like an empty history.
- Subagent result: ≤ 20 lines — files touched, the verification command run, the verdict.
