# Oneiros

An agent that learns from its sessions, keeps curated memory, and dreams.

Built on the Claude Code harness, driven from the Claude Agent SDK.
[SPEC.md](SPEC.md) is what it is meant to do; [TASKS.md](TASKS.md) is how it
gets built.

## Why it is small

The harness already supplies the agent loop, tool calling, compaction,
providers, the core tools, and the mechanisms behind skills, hooks and
subagents. None of that is reimplemented here. What is left is the part nothing
else does: **memory that is curated rather than merely written, skills that are
maintained after they are created, recall across past sessions, and a dream
pass.**

The functional requirements come from
[hermes-agent](https://github.com/NousResearch/hermes-agent) — its documented
behaviour, the trade-offs it forced, and the traps it hit. No code was taken
from it.

## Install

```bash
pip install -e ".[dev]"          # add ",sdk" once the runners land
oneiros doctor
```

Link the plugin so the harness picks up its commands:

```bash
# POSIX
ln -s "$PWD/plugin" ~/.claude/plugins/oneiros
# Windows — a junction needs no elevation; /D does
mklink /J "%USERPROFILE%\.claude\plugins\oneiros" "%CD%\plugin"
```

Prefer `/J`. A symbolic link (`/D`) requires an elevated prompt or developer
mode, and the failure is a permission error most people read as "the plugin
cannot be installed". A junction is the same thing for a local directory and
works from an ordinary shell.

Register the session-search MCP server in `~/.claude/settings.json`, **by file
path**:

```json
{
  "mcpServers": {
    "oneiros-sessions": {
      "command": "python",
      "args": ["/absolute/path/to/oneiros/src/oneiros/mcp_server.py"]
    }
  }
}
```

`oneiros doctor` prints the exact path for this machine.

Not `python -m oneiros.mcp_server`. The two look equivalent and are not: `-m`
needs the package on the import path, which is precisely what the server is
written not to depend on. It imports nothing from this package and opens the
index directly, so a file-path registration keeps working when the harness
picks an interpreter that has never seen the install. The `-m` form works right
up until it doesn't, and then fails with an import error nobody connects back
to this line. `doctor` flags it if you use it anyway.

## Use

In a session:

```
/remember I prefer pytest over unittest
/memory pending
/sessions why did we drop the redis cache
```

From a shell:

```bash
oneiros doctor
oneiros sessions index
oneiros sessions search "connection pool"
oneiros memory show
```

## Configuration

`~/.claude/oneiros/config.json` — thresholds, limits, models. Every field has a
working default; the file is optional.

Credentials go in `~/.claude/oneiros.env` (`KEY=value` per line). **Secrets
only.** An exported variable always wins over the file. Anything that is not a
secret belongs in `config.json`, where someone can find it later.

Move the whole state directory with `ONEIROS_HOME`.

## Two rules worth knowing before reading the code

**Memory is written by refusal.** A write over the limit raises and lists what
is already there; nothing is ever evicted silently. A write that looks like a
prompt injection is refused outright. A write from an unattended pass is staged
for review no matter how the gate is configured — that policy depends on the
*origin* of the write, not on the setting.

**A fact is never dreamed.** The dream pass has no write path to memory at all.
A procedure can be dreamed because it can be tested; a fact cannot, and a
dreamed fact would be replayed into every session that follows. See
[SPEC.md §5](SPEC.md) — it is the constraint the whole dream design is built
around.

## Status

| Lot | Scope | State |
|---|---|---|
| L0 | project, paths, config, `doctor` | done |
| L1 | curated memory: bounds, guard, gate, snapshot | done |
| L1+ | `SessionStart` hook carrying the snapshot into a live session | done |
| L2 | session index, query translation, MCP server | done |
| L3 | skill registry, telemetry, lifecycle, rollback | not started |
| L4 | Agent SDK runners, post-turn review | not started |
| L5 | dream trigger, NREM consolidation | not started |
| L6 | REM, quarantine, wake test | not started |

## Development

```bash
pytest
```

## Licence

MIT.
