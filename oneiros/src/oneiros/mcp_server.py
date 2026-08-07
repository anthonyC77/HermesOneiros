#!/usr/bin/env python3
"""Session search, exposed to the agent over MCP.

**This file imports nothing from ``oneiros``, and that is deliberate.** The
harness launches MCP servers as bare subprocesses, and there is no guarantee
the interpreter it picks has this package installed — a user can install the
plugin without the Python package, or the harness can resolve a different
Python than the one the package lives in. A server that only works when the
stars align is a server that fails silently and intermittently, which is worse
than one that does not exist.

So: standard library only, and the database is opened directly. Two things are
consequently duplicated from the package — the state-directory resolution order
and the FTS5 query translation. That duplication is the price of the guarantee.
If either changes, it changes here in the same commit; the tests assert the two
implementations agree.

Protocol: newline-delimited JSON-RPC 2.0 on stdin/stdout, hand-rolled. The
surface an MCP server needs is four methods wide, and taking a dependency to
get them would defeat the point of the file.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "oneiros-sessions"
SERVER_VERSION = "0.1.0"
#: Fallback when the client does not state one; otherwise we echo theirs.
DEFAULT_PROTOCOL = "2025-06-18"

# --------------------------------------------------------------------------- #
# Duplicated from oneiros.config — keep in sync (asserted by tests)
# --------------------------------------------------------------------------- #

def state_dir() -> Path:
    for var in ("ONEIROS_HOME", "CLAUDE_PLUGIN_DATA"):
        raw = os.environ.get(var, "").strip()
        if raw:
            return Path(raw).expanduser()
    return Path.home() / ".claude" / "oneiros"


# --------------------------------------------------------------------------- #
# Duplicated from oneiros.sessions.query — keep in sync (asserted by tests)
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(r"[^\W_]+(?:[.\-_][^\W_]+)*", re.UNICODE)
_MIN_PREFIX = 3


def build_match(query: str, prefix: bool = True) -> str | None:
    tokens = _TOKEN.findall(query or "")
    if not tokens:
        return None
    quoted = [f'"{t}"' for t in tokens]
    if prefix and len(tokens[-1]) >= _MIN_PREFIX:
        quoted[-1] = f"{quoted[-1]}*"
    return " AND ".join(quoted)


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

def _connect() -> sqlite3.Connection | None:
    path = state_dir() / "sessions.db"
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _no_index_message() -> str:
    return (
        "No session index yet. Build it with `oneiros sessions index`, "
        "then search again."
    )


def do_search(query: str, limit: int = 20, project: str | None = None) -> str:
    match = build_match(query)
    if match is None:
        return "That query has no searchable words in it."

    conn = _connect()
    if conn is None:
        return _no_index_message()

    sql = (
        "SELECT session_id, project, role, ts, "
        "snippet(messages, 0, '«', '»', '…', 16) AS snip "
        "FROM messages WHERE messages MATCH ?"
    )
    params: list[Any] = [match]
    if project:
        sql += " AND project = ?"
        params.append(project)
    sql += " ORDER BY rank LIMIT ?"
    params.append(max(1, min(int(limit), 100)))

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        return f"Search failed: {exc}"
    finally:
        conn.close()

    if not rows:
        return f"No matches for {query!r}."

    lines = [f"{len(rows)} match(es) for {query!r}:", ""]
    for row in rows:
        stamp = (row["ts"] or "")[:19] or "undated"
        lines.append(
            f"- [{stamp}] {row['project']}/{row['session_id'][:8]} "
            f"({row['role']}): {row['snip']}"
        )
    return "\n".join(lines)


def do_stats() -> str:
    conn = _connect()
    if conn is None:
        return _no_index_message()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT session_id) AS s, "
            "COUNT(DISTINCT project) AS p FROM messages"
        ).fetchone()
    except sqlite3.Error as exc:
        return f"Stats failed: {exc}"
    finally:
        conn.close()
    return (
        f"{row['n']:,} messages across {row['s']:,} sessions "
        f"in {row['p']:,} projects."
    )


# --------------------------------------------------------------------------- #
# MCP surface
# --------------------------------------------------------------------------- #

TOOLS = [
    {
        "name": "search_sessions",
        "description": (
            "Full-text search across this machine's past Claude Code sessions. "
            "Use it when the answer may already exist in an earlier conversation — "
            "'did we decide anything about X', 'what was the fix for Y', 'have I "
            "seen this error before'. Free: no model call, no token cost. Prefer "
            "it over asking the user to remember."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Plain words to look for. Not FTS5 syntax — "
                                   "operators are matched literally.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return (1-100, default 20).",
                },
                "project": {
                    "type": "string",
                    "description": "Restrict to one project directory name.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "session_stats",
        "description": "How much history is indexed: messages, sessions, projects.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _result(request_id: Any, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text(body: str) -> dict:
    return {"content": [{"type": "text", "text": body}]}


def handle(message: dict) -> dict | None:
    """Handle one JSON-RPC message. Returns None for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    # Notifications carry no id and expect no reply.
    if request_id is None:
        return None

    if method == "initialize":
        requested = params.get("protocolVersion")
        return _result(
            request_id,
            {
                "protocolVersion": requested if isinstance(requested, str) else DEFAULT_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "search_sessions":
            return _result(
                request_id,
                _text(
                    do_search(
                        str(args.get("query") or ""),
                        int(args.get("limit") or 20),
                        args.get("project"),
                    )
                ),
            )
        if name == "session_stats":
            return _result(request_id, _text(do_stats()))
        return _error(request_id, -32602, f"unknown tool {name!r}")

    if method in ("ping", "shutdown"):
        return _result(request_id, {})

    return _error(request_id, -32601, f"unknown method {method!r}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        try:
            response = handle(message)
        except Exception as exc:  # noqa: BLE001
            # A crashed server is a dead tool for the rest of the session, so
            # any unexpected failure becomes a JSON-RPC error and the loop
            # keeps running.
            response = _error(message.get("id"), -32603, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
