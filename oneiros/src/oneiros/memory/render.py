"""Rendering memory into the system prompt.

Two decisions live here, and both are load-bearing.

**Append, never replace.** The block is appended to the harness's own preset.
Replacing the preset drops the harness's tool guidance, and the agent starts
misusing the edit tools in ways that are hard to trace back to a prompt change
made days earlier.

**Captured once per session.** The block is a frozen snapshot taken at session
start. Memory written mid-session lands on disk immediately but does not appear
in the prompt until the next session — that is the visible cost of keeping the
prompt prefix byte-stable, and it is the right trade: a prefix that changes
mid-conversation invalidates the cache for every turn that follows it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import config as cfg
from .store import Store, Target

__all__ = ["Snapshot", "build_stores", "capture", "reset"]

_RULE = "═" * 46


def build_stores(config: cfg.Config | None = None, root: Path | None = None) -> dict[Target, Store]:
    """The two stores, wired to their limits."""
    config = config or cfg.Config.load()
    base = root or cfg.memory_dir()
    return {
        Target.MEMORY: Store(base / Target.MEMORY.filename, config.memory_char_limit, Target.MEMORY),
        Target.USER: Store(base / Target.USER.filename, config.user_char_limit, Target.USER),
    }


def render(stores: dict[Target, Store]) -> str:
    """Render both stores as the block appended to the preset."""
    sections: list[str] = []
    for target in (Target.MEMORY, Target.USER):
        store = stores[target]
        entries = store.entries()
        if not entries:
            continue
        sections.append("\n".join([_RULE, store.header(), _RULE, *_body(entries)]))
    return "\n\n".join(sections)


def _body(entries: list[str]) -> list[str]:
    out: list[str] = []
    for i, entry in enumerate(entries):
        if i:
            out.append("§")
        out.append(entry)
    return out


@dataclass(frozen=True)
class Snapshot:
    """An immutable view of memory, as the current session sees it."""

    text: str
    entry_counts: dict[str, int]

    def is_empty(self) -> bool:
        return not self.text.strip()


_current: Snapshot | None = None


def capture(
    config: cfg.Config | None = None,
    root: Path | None = None,
    force: bool = False,
) -> Snapshot:
    """Return this session's snapshot, taking it on first call.

    Subsequent calls return the same object even if the files changed — that is
    the point. ``force`` exists for tests and for a deliberate new session, not
    as a refresh knob: calling it mid-conversation is what this module is here
    to prevent.
    """
    global _current
    if _current is not None and not force:
        return _current
    stores = build_stores(config, root)
    _current = Snapshot(
        text=render(stores),
        entry_counts={t.value: len(s.entries()) for t, s in stores.items()},
    )
    return _current


def reset() -> None:
    """Drop the captured snapshot. Session boundaries and tests only."""
    global _current
    _current = None
