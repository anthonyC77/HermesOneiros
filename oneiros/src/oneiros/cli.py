"""Command line entry point.

``doctor`` comes first among these commands because everything else assumes a
correctly wired install, and "it silently did nothing" is the failure mode this
project is most prone to: a plugin that is not linked, an index that was never
built, a settings source that is not loaded. Each of those produces no error
anywhere — just an agent that quietly stops learning.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, config as cfg
from .memory import MemoryRefused, Operation, Target
from .memory.gate import Gate, Origin
from .memory.guard import UnsafeContent, assert_safe
from .memory.render import build_stores, capture
from .sessions.index import Fts5Unavailable, Index

OK = "ok  "
WARN = "warn"
FAIL = "FAIL"


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #

def cmd_doctor(_args: argparse.Namespace) -> int:
    config = cfg.Config.load()
    rows: list[tuple[str, str, str]] = []

    state = cfg.state_dir()
    writable = _is_writable(state)
    rows.append((OK if writable else FAIL, "state directory", str(state)))

    config_path = state / "config.json"
    if not config_path.exists():
        rows.append((WARN, "config.json", "absent — using defaults"))
    else:
        try:
            json.loads(config_path.read_text(encoding="utf-8"))
            rows.append((OK, "config.json", str(config_path)))
        except (OSError, json.JSONDecodeError) as exc:
            rows.append((FAIL, "config.json", f"unreadable ({exc}) — defaults in use"))

    stores = build_stores(config)
    for target, store in stores.items():
        exists = store.path.exists()
        rows.append(
            (OK if exists else WARN, f"memory/{target.filename}",
             store.header() if exists else "not written yet")
        )

    pending = Gate(config).pending()
    rows.append(
        (WARN if pending else OK, "pending memory writes",
         f"{len(pending)} awaiting review" if pending else "none")
    )

    transcripts = cfg.transcripts_dir()
    rows.append(
        (OK if transcripts.is_dir() else FAIL, "harness transcripts",
         str(transcripts) if transcripts.is_dir() else f"{transcripts} not found")
    )

    try:
        with Index() as index:
            stats = index.stats()
        rows.append(
            (OK if stats.messages else WARN, "session index",
             stats.describe() if stats.messages else "empty — run: oneiros sessions index")
        )
    except Fts5Unavailable as exc:
        rows.append((FAIL, "session index", str(exc)))

    plugin = Path.home() / ".claude" / "plugins" / "oneiros"
    rows.append(
        (OK if plugin.exists() else WARN, "plugin linked",
         str(plugin) if plugin.exists() else "not linked — see README")
    )

    rows.append(_mcp_row())

    rows.append(
        (OK if shutil.which("claude") else WARN, "claude CLI",
         shutil.which("claude") or "not on PATH — dream passes cannot self-spawn")
    )

    try:
        import claude_agent_sdk  # noqa: F401

        rows.append((OK, "agent SDK", "importable"))
    except ImportError:
        rows.append((WARN, "agent SDK", 'absent — install with: pip install -e ".[sdk]"'))

    width = max(len(name) for _, name, _ in rows)
    for status, name, detail in rows:
        print(f"[{status}] {name.ljust(width)}  {detail}")

    return 1 if any(status == FAIL for status, _, _ in rows) else 0


def _mcp_row() -> tuple[str, str, str]:
    """Is the session-search server registered, and registered *correctly*?

    Registering it as ``python -m oneiros.mcp_server`` looks equivalent and is
    not: ``-m`` needs the package on the import path, which is exactly what the
    server is written not to depend on. It works right up until the harness
    picks a different interpreter, then fails with an import error nobody
    connects to this. So the check is specific about the shape, not just the
    presence.
    """
    from . import mcp_server

    server_path = Path(mcp_server.__file__)
    settings = Path.home() / ".claude" / "settings.json"
    hint = f'register it as: python "{server_path}"'

    try:
        raw = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (WARN, "MCP server", f"not registered — {hint}")

    servers = raw.get("mcpServers")
    if not isinstance(servers, dict):
        return (WARN, "MCP server", f"not registered — {hint}")

    for name, spec in servers.items():
        args = spec.get("args") if isinstance(spec, dict) else None
        joined = " ".join(str(a) for a in args) if isinstance(args, list) else ""
        if "mcp_server" not in joined:
            continue
        if "-m" in (args or []):
            return (
                WARN,
                "MCP server",
                f"{name} uses -m, which needs the package importable — {hint}",
            )
        return (OK, "MCP server", name)

    return (WARN, "MCP server", f"not registered — {hint}")


def _is_writable(path: Path) -> bool:
    probe = path / ".oneiros-write-probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# memory
# --------------------------------------------------------------------------- #

def _store_factory(config: cfg.Config):
    stores = build_stores(config)
    return lambda target: stores[target]


def cmd_memory(args: argparse.Namespace) -> int:
    config = cfg.Config.load()
    stores = build_stores(config)
    gate = Gate(config)

    if args.memory_command == "show":
        snapshot = capture(config, force=True)
        print(snapshot.text or "(memory is empty)")
        return 0

    if args.memory_command in ("add", "replace", "remove"):
        target = Target(args.target)
        content = getattr(args, "content", None)
        if content is not None:
            try:
                assert_safe(content)
            except UnsafeContent as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 2
        try:
            operation = Operation(
                action=args.memory_command,
                content=content,
                old_text=getattr(args, "old_text", None),
            )
            decision = gate.submit(stores[target], operation, Origin.FOREGROUND)
        except (MemoryRefused, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if decision.applied:
            note = f" ({decision.notes[0]})" if decision.notes else ""
            print(f"applied to {target.value}{note}")
        else:
            assert decision.pending is not None
            print(f"staged as {decision.pending.id} — review with: oneiros memory pending")
        return 0

    if args.memory_command == "pending":
        entries = gate.pending()
        if not entries:
            print("nothing pending")
            return 0
        for entry in entries:
            print(entry.summary())
            print("\n".join(f"    {line}" for line in entry.diff.splitlines()))
        return 0

    if args.memory_command in ("approve", "reject"):
        try:
            if args.memory_command == "approve":
                plan = gate.approve(args.id, _store_factory(config))
                print(f"applied to {plan.target.value}")
            else:
                entry = gate.reject(args.id)
                print(f"dropped {entry.id}")
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except MemoryRefused as exc:
            # Re-planning against current state can legitimately fail — memory
            # may have changed since staging. Say so rather than applying a
            # stale outcome.
            print(f"cannot apply now: {exc}", file=sys.stderr)
            return 2
        return 0

    return 2


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #

def cmd_sessions(args: argparse.Namespace) -> int:
    try:
        with Index() as index:
            if args.sessions_command == "index":
                seen, touched = index.refresh()
                print(f"{seen} transcript(s) seen, {touched} indexed")
                print(index.stats().describe())
                return 0

            if args.sessions_command == "stats":
                print(index.stats().describe())
                return 0

            if args.sessions_command == "recent":
                for hit in index.recent(args.limit):
                    print(f"[{(hit.timestamp or '')[:19]}] {hit.project} ({hit.role})")
                    print(f"    {hit.snippet}")
                return 0

            if args.sessions_command == "search":
                hits = index.search(args.query, args.limit, args.project)
                if not hits:
                    print(f"no matches for {args.query!r}")
                    return 0
                for hit in hits:
                    stamp = (hit.timestamp or "")[:19] or "undated"
                    print(f"[{stamp}] {hit.project}/{hit.session_id[:8]} ({hit.role})")
                    print(f"    {hit.snippet}")
                return 0
    except Fts5Unavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 2


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oneiros", description=__doc__)
    parser.add_argument("--version", action="version", version=f"oneiros {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="report what is wired up and what is missing")

    memory = sub.add_parser("memory", help="inspect and edit curated memory")
    msub = memory.add_subparsers(dest="memory_command", required=True)
    msub.add_parser("show", help="print memory as the next session will see it")

    add = msub.add_parser("add", help="add an entry")
    add.add_argument("content")
    add.add_argument("--target", choices=[t.value for t in Target], default="memory")

    replace = msub.add_parser("replace", help="replace an entry, matched by substring")
    replace.add_argument("old_text")
    replace.add_argument("content")
    replace.add_argument("--target", choices=[t.value for t in Target], default="memory")

    remove = msub.add_parser("remove", help="remove an entry, matched by substring")
    remove.add_argument("old_text")
    remove.add_argument("--target", choices=[t.value for t in Target], default="memory")

    msub.add_parser("pending", help="list writes awaiting review")
    approve = msub.add_parser("approve", help="apply a staged write")
    approve.add_argument("id")
    reject = msub.add_parser("reject", help="drop a staged write")
    reject.add_argument("id")

    sessions = sub.add_parser("sessions", help="search past sessions")
    ssub = sessions.add_subparsers(dest="sessions_command", required=True)
    ssub.add_parser("index", help="index new and changed transcripts")
    ssub.add_parser("stats", help="how much history is indexed")

    recent = ssub.add_parser("recent", help="most recent messages")
    recent.add_argument("--limit", type=int, default=10)

    search = ssub.add_parser("search", help="full-text search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--project", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg.load_env()
    handlers = {"doctor": cmd_doctor, "memory": cmd_memory, "sessions": cmd_sessions}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
