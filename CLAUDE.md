# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace layout

`d:\HermesAnt` holds a single project, [oneiros/](oneiros/). Nothing here is
under version control — there is no `.git` anywhere in the tree, so there is no
history to consult and no diff to review against. Read the code and the spec.

`hermes-agent` and `hermes-cc` are **not** in this workspace. `hermes-agent`
appears throughout the docs as a *reference* to the upstream
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
project, which supplies oneiros' functional requirements. It is a citation, not
a checkout: there is no local copy to read, port from, or grep.

---

## oneiros

An agent that learns from its sessions, keeps curated memory, and dreams. Built
on the Claude Code harness and driven from the Claude Agent SDK, so the agent
loop, providers, compaction, tool calling, and the mechanisms behind skills,
hooks and subagents are all *deliberately not reimplemented*. What this project
owns is the part nothing else does: curated memory, maintained skills,
cross-session recall, and a dream pass.

**[oneiros/SPEC.md](oneiros/SPEC.md) is the functional spec;
[oneiros/TASKS.md](oneiros/TASKS.md) is the 36-task implementation breakdown
(T01–T36, grouped into lots L0–L6).** Read the relevant task before writing
code — each carries a testable done-condition, and the code refers back to
spec clauses by number (`SPEC.md E11`, `SPEC.md §5.3`) rather than restating
them.

**Both documents are written in French.** Match that when editing them. Source
code, docstrings, comments and tests are in English; do not mix the two.

### The rule that governs this directory

**No Hermès code enters `oneiros/`.** Hermès supplies a requirements document:
which capabilities exist, which trade-offs they force, which traps they hit.
The implementation is written from scratch for this harness. A reference to
Hermès names a documented behaviour, never a module to port.

### Two invariants

- **The prompt cache is sacred.** Nothing mutates past context or the system
  prompt mid-conversation. `memory/render.py` captures memory *once* per
  session and returns that same frozen snapshot forever after; `capture(force=True)`
  exists for tests and session boundaries, not as a refresh knob. The accepted
  cost: a write lands on disk immediately but is not visible in the prompt
  until session *n+1*. The memory block is **appended** to the harness preset,
  never substituted for it.
- **A fact is never dreamed.** The dream pass has no write path to memory at
  all — to be enforced by a test that walks the call graph, not by a prompt
  instruction. A procedure can be dreamed because it can be tested; a dreamed
  fact is indistinguishable from a confabulation and would be replayed into
  every session after it. `Origin` in `memory/gate.py` has `NREM` but
  deliberately no REM member.

### Commands

```bash
pip install -e ".[dev]"         # --no-deps if a stale console-script shim breaks it
python -m oneiros doctor        # what is wired up and what is missing — start here
python -m pytest                # 207 tests, no runner wrapper
python -m pytest tests/test_sessions.py -k fts
python -m oneiros sessions index
python -m oneiros memory show
```

**Use `python -m oneiros`, not the `oneiros` console script.** pip cannot write
the executable shim on this machine — the script is not on PATH even though the
package imports fine. Note the friction this creates: `plugin/commands/*.md`
tell the agent to run bare `oneiros memory add …` via Bash, which will fail
here. Prefer `python -m oneiros` when testing a command's instructions by hand,
and keep it in mind before concluding a command is broken.

### Layout

```
src/oneiros/config.py        every path and setting resolves through here
src/oneiros/cli.py           doctor · memory · sessions — argparse, no framework
src/oneiros/memory/          store (bounds) · guard (screening) · gate (approval) · render (snapshot)
src/oneiros/sessions/        reader (JSONL) · index (FTS5) · query (translation)
src/oneiros/mcp_server.py    stdlib only — imports nothing from the package
plugin/                      manifest, commands (/remember /memory /sessions), hooks
```

State lives outside the repo, under `~/.claude/oneiros` (override with
`ONEIROS_HOME`, or `CLAUDE_PLUGIN_DATA` when the harness sets it). Two
directories are explicitly not ours: `~/.claude/skills` is owned by the harness
and written into selectively, and `~/.claude/projects` is read-only input that
is **never created** — creating it would make a misconfiguration look like an
empty history.

### Things that are easy to break

- **`mcp_server.py` must import nothing from `oneiros`.** The harness may launch
  it under an interpreter that has never seen the install. It therefore
  duplicates the state-dir resolution and the FTS5 query translation; tests
  assert the two copies agree, so a change to `config.state_dir()` or
  `sessions/query.build_match()` changes `mcp_server.py` in the same commit.
  Register it **by file path**, never `-m` — `doctor` flags the `-m` form
  specifically, because it works right up until the harness picks a different
  interpreter.
- **The gate stages by origin, not by setting.** `Origin.is_automatic` is what
  decides; an automatic write is held for review whatever `memory_gate` says.
  The setting exists so a user can tighten foreground writes, never so an
  unattended pass can loosen itself. Approval **re-plans against the current
  store** rather than replaying the saved outcome — memory may have moved since
  staging.
- **Memory overflow raises; nothing is ever evicted.** `MemoryFull` carries the
  current entries so the agent consolidates and retries in the same turn.
  Mutation is two-phase — `Store.plan()` validates and computes without
  touching disk, `Store.commit()` writes — which is what lets the gate show a
  real diff for a write it has not applied. Entries are matched by *unique*
  substring; an ambiguous match is an error, never a guess.
- **`memory/guard.py` favours precision over recall.** Every pattern is
  phrase-level, so `ignore`, `system` and `~/.ssh/id_ed25519` are ordinary
  content in a technical note and trip nothing. A rule that fires on legitimate
  notes trains the operator to approve blindly, which costs more than it buys.
  Widen a pattern only with a test that shows the false positive it does not
  create.
- **`sessions/reader.py` may never raise on bad input.** The transcript format
  belongs to the harness and changes without notice; a reader that throws on one
  malformed line takes the whole index down. Tool *inputs* are indexed, tool
  results are not, and sidechain/meta entries are skipped.
- **Nothing may touch the real `~/.claude`.** The autouse `isolated_state`
  fixture in [oneiros/tests/conftest.py](oneiros/tests/conftest.py) redirects
  `ONEIROS_HOME` per test and resets the memory snapshot on both sides of the
  yield.

### Status

L0–L2 are done (config/doctor, curated memory, session recall + MCP). L3–L6
(skill registry and lifecycle, Agent SDK runners, NREM, REM) are not started —
see the table in [oneiros/README.md](oneiros/README.md).

Two consequences of that, both intentional and both easy to mistake for bugs:
`plugin/hooks/hooks.json` declares `"hooks": {}` so the plugin loads before its
handlers exist, and `plugin/hooks/_state.py` — referenced by the docstring on
`config.state_dir()` as the place the resolution order is duplicated — has not
been written yet. When it lands, it duplicates that order verbatim and changes
in the same commit as the original.
