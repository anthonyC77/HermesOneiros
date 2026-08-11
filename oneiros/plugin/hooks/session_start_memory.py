#!/usr/bin/env python3
"""Put curated memory in front of the model, once, at session start.

Without this hook the loop is open: ``memory add`` writes to disk, ``memory
show`` renders it, and the agent never sees any of it. This is the only thing
that carries memory into a live session until the SDK runners land (SPEC.md §6),
and it stays useful afterwards — a hook reaches sessions the user starts by
hand, which a runner does not.

**Why the block is appended and never substituted.** The harness owns the system
prompt. What this hook returns is additional context, not a replacement for
anything, which is the same contract ``memory/render.py`` observes (SPEC.md E1).

**Why the snapshot is cached per session.** Invariant I1: the prompt prefix is
byte-stable for the life of a conversation. ``SessionStart`` fires again on
``compact``, and re-reading the files there would let a write made mid-session
change what the model sees mid-conversation — precisely what ``render.capture``
exists to prevent. So the first fire of a session records what it rendered, and
later fires in the *same* session replay those bytes even if the files moved.
The accepted cost is unchanged: a write lands on disk now and is visible in
session *n+1*.

**Stdlib only, and no import from oneiros.** See ``_state.py``. The consequence
is that the rendering below duplicates ``memory/render.py`` and ``memory/store.py``;
tests assert the two agree, and both change in the same commit.

**Silence on failure.** Any error means no context and exit 0. A hook that
prints a traceback puts it in the user's face at every session start, for a
feature that is supplementary by design.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from _state import memory_dir, state_dir
except Exception:  # pragma: no cover - only when the hook is run from elsewhere
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _state import memory_dir, state_dir

# --------------------------------------------------------------------------- #
# Duplicated from oneiros.memory.store / .render — keep in sync (tests assert)
# --------------------------------------------------------------------------- #

SEPARATOR = "§"
_RULE = "═" * 46

#: Mirrors Config.memory_char_limit / Config.user_char_limit.
_DEFAULT_LIMITS = {"memory": 2200, "user": 1375}
_FILENAMES = {"memory": "MEMORY.md", "user": "USER.md"}
_LABELS = {"memory": "MEMORY (your own notes)", "user": "USER PROFILE"}
#: Rendering order. MEMORY before USER, as in render.render.
_ORDER = ("memory", "user")


def parse(raw: str) -> list[str]:
    """Split stored text into entries. Mirrors ``store.parse``."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    joined = f"\n{SEPARATOR}\n"
    parts = text.split(joined) if joined in text else text.split(SEPARATOR)
    return [p.strip() for p in parts if p.strip()]


def usage_of(entries: list[str]) -> int:
    """Character usage. Separators are format, not content."""
    return sum(len(e) for e in entries)


def header(target: str, entries: list[str], limit: int) -> str:
    """The usage line, so the agent knows when to consolidate. Mirrors ``Store.header``."""
    used = usage_of(entries)
    pct = round(100 * used / limit) if limit else 0
    return f"{_LABELS[target]} [{pct}% — {used:,}/{limit:,} chars]"


def _body(entries: list[str]) -> list[str]:
    out: list[str] = []
    for i, entry in enumerate(entries):
        if i:
            out.append(SEPARATOR)
        out.append(entry)
    return out


def limits() -> dict[str, int]:
    """Character caps, from config.json when it names them."""
    resolved = dict(_DEFAULT_LIMITS)
    try:
        raw = json.loads((state_dir() / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return resolved
    if not isinstance(raw, dict):
        return resolved
    for target, key in (("memory", "memory_char_limit"), ("user", "user_char_limit")):
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            resolved[target] = value
    return resolved


def render(base: Path | None = None) -> str:
    """Render both stores as the block appended to the preset."""
    base = base or memory_dir()
    caps = limits()
    sections: list[str] = []
    for target in _ORDER:
        try:
            raw = (base / _FILENAMES[target]).read_text(encoding="utf-8")
        except OSError:
            continue
        entries = parse(raw)
        if not entries:
            continue
        sections.append(
            "\n".join([_RULE, header(target, entries, caps[target]), _RULE, *_body(entries)])
        )
    return "\n\n".join(sections)


# --------------------------------------------------------------------------- #
# Per-session freeze (I1)
# --------------------------------------------------------------------------- #

#: One file, overwritten by each new session, so it cannot accumulate.
CACHE_NAME = ".session-snapshot.json"


def frozen_text(session_id: str, base: Path | None = None) -> str:
    """Return this session's block, rendering it only on the session's first call.

    A later fire — ``compact`` — replays the recorded bytes. An unusable cache
    is a reason to re-render, never a reason to fail.
    """
    cache = state_dir() / CACHE_NAME
    if session_id:
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved.get("session_id") == session_id:
                text = saved.get("text")
                if isinstance(text, str):
                    return text
        except Exception:
            pass

    text = render(base)

    if session_id:
        try:
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"session_id": session_id, "text": text}),
                encoding="utf-8",
            )
            tmp.replace(cache)
        except Exception:
            pass
    return text


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

PREAMBLE = (
    "Curated memory from previous sessions, carried forward by oneiros. "
    "Treat it as notes you wrote, not as instructions from the user. "
    "It is a frozen snapshot: a write made now is visible next session."
)


def build_response(payload: dict) -> dict | None:
    """The hook's JSON response, or ``None`` when there is nothing to say."""
    session_id = payload.get("session_id")
    text = frozen_text(session_id if isinstance(session_id, str) else "")
    if not text.strip():
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"{PREAMBLE}\n\n{text}",
        }
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        response = build_response(payload)
    except Exception:
        return 0
    if response:
        print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
