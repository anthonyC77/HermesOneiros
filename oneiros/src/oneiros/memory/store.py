"""Reading, writing and bounding the two memory files.

The file format is deliberately dull: entries separated by a lone ``§`` on its
own line. Entries may span lines, so a line-based format would not do, and a
structured one (JSON, YAML) would make the file hostile to the two things it
most needs to survive — an operator opening it in an editor, and a diff.

Three rules drive every design decision below.

**Nothing is evicted silently.** A write that would exceed the limit raises,
and the error carries the current entries so the agent can consolidate and
retry in the same turn. An automatic eviction would drop the entry the user
cared about most, on the turn they were least likely to be watching.

**Mutation is two-phase.** :meth:`Store.plan` validates and computes the result
without touching disk; :meth:`Store.commit` writes it. That split is what lets
the approval gate show a real diff for a write it has not yet applied — the
alternative is a second, drifting implementation of the same arithmetic.

**Matching is by unique substring.** Callers should not have to reproduce an
entry verbatim to replace it, but a substring that matches two entries is an
error rather than a guess: picking one would edit memory the caller never saw.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

SEPARATOR = "§"
_JOIN = f"\n{SEPARATOR}\n"

Action = Literal["add", "replace", "remove"]


class Target(str, Enum):
    """Which store a write applies to.

    Two stores rather than one because they answer different questions and rot
    at different rates: what the agent learned about the work, and who it is
    working for.
    """

    MEMORY = "memory"
    USER = "user"

    @property
    def filename(self) -> str:
        return "MEMORY.md" if self is Target.MEMORY else "USER.md"

    @property
    def label(self) -> str:
        return "MEMORY (your own notes)" if self is Target.MEMORY else "USER PROFILE"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class MemoryRefused(Exception):
    """Base class for refusals. Every subclass is actionable by the caller."""


class MemoryFull(MemoryRefused):
    """A write would exceed the character limit.

    Carries the current entries because the recovery is always the same, and it
    happens in the same turn: read what is there, consolidate or drop
    something, retry. An error that only said "full" would force a second round
    trip to discover what could be merged.
    """

    def __init__(self, entries: list[str], usage: int, limit: int, needed: int) -> None:
        self.entries = entries
        self.usage = usage
        self.limit = limit
        self.needed = needed
        super().__init__(
            f"Memory at {usage:,}/{limit:,} chars. This write needs {needed:,} more "
            f"and would exceed the limit. Consolidate now — merge overlapping "
            f"entries with 'replace' or drop stale ones with 'remove' — then retry, "
            f"all in this turn. Current entries: {len(entries)}."
        )


class NoMatch(MemoryRefused):
    """No entry contains the given substring."""

    def __init__(self, old_text: str, entries: list[str]) -> None:
        self.old_text = old_text
        self.entries = entries
        super().__init__(
            f"No entry contains {old_text!r}. There are {len(entries)} entries; "
            f"use a substring from one of them."
        )


class AmbiguousMatch(MemoryRefused):
    """The substring matches more than one entry.

    Names the candidates: the caller's next move is to pick a longer substring,
    and they need to see what they are disambiguating between.
    """

    def __init__(self, old_text: str, matches: list[str]) -> None:
        self.old_text = old_text
        self.matches = matches
        preview = "; ".join(_ellipsis(m, 60) for m in matches)
        super().__init__(
            f"{old_text!r} matches {len(matches)} entries — be more specific. "
            f"Candidates: {preview}"
        )


def _ellipsis(text: str, width: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Operation:
    """A requested mutation, before it is known to be valid."""

    action: Action
    content: str | None = None
    old_text: str | None = None

    def __post_init__(self) -> None:
        if self.action == "add" and not (self.content or "").strip():
            raise ValueError("add requires content")
        if self.action in ("replace", "remove") and not (self.old_text or "").strip():
            raise ValueError(f"{self.action} requires old_text")
        if self.action == "replace" and not (self.content or "").strip():
            raise ValueError("replace requires content")


@dataclass(frozen=True)
class Plan:
    """A validated mutation and its outcome, not yet written to disk.

    ``no_op`` is a success, not a failure: adding content that is already
    present should leave the caller with nothing to handle.
    """

    target: Target
    operation: Operation
    before: list[str]
    after: list[str]
    no_op: bool = False

    @property
    def usage_after(self) -> int:
        return usage_of(self.after)

    def diff(self) -> str:
        """A minimal, human-readable diff — what a reviewer needs to say yes or no."""
        removed = [e for e in self.before if e not in self.after]
        added = [e for e in self.after if e not in self.before]
        lines: list[str] = []
        for entry in removed:
            lines.extend(f"- {line}" for line in entry.splitlines() or [""])
        for entry in added:
            lines.extend(f"+ {line}" for line in entry.splitlines() or [""])
        return "\n".join(lines) if lines else "(no change)"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def parse(raw: str) -> list[str]:
    """Split stored text into entries, dropping empties.

    Line endings are normalised to ``\\n``. Round-tripping is byte-exact for
    files already in canonical form; a CRLF file is rewritten with LF on first
    write, which is the lesser of two evils — the alternative is a store whose
    character counts depend on which platform last touched it.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    parts = text.split(f"\n{SEPARATOR}\n") if f"\n{SEPARATOR}\n" in text else text.split(SEPARATOR)
    return [p.strip() for p in parts if p.strip()]


def serialise(entries: list[str]) -> str:
    """Render entries to canonical stored form."""
    if not entries:
        return ""
    return _JOIN.join(e.strip() for e in entries) + "\n"


def usage_of(entries: list[str]) -> int:
    """Character usage. Separators do not count — they are format, not content."""
    return sum(len(e) for e in entries)


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #

class Store:
    """One memory file, bounded."""

    def __init__(self, path: Path, limit: int, target: Target) -> None:
        self.path = path
        self.limit = limit
        self.target = target

    # -- reading ------------------------------------------------------------

    def entries(self) -> list[str]:
        try:
            return parse(self.path.read_text(encoding="utf-8"))
        except OSError:
            return []

    def usage(self) -> int:
        return usage_of(self.entries())

    def header(self) -> str:
        """The usage line the agent sees, so it knows when to consolidate."""
        used = self.usage()
        pct = round(100 * used / self.limit) if self.limit else 0
        return f"{self.target.label} [{pct}% — {used:,}/{self.limit:,} chars]"

    # -- mutation -----------------------------------------------------------

    def plan(self, operation: Operation) -> Plan:
        """Validate an operation and compute its result. Nothing is written."""
        before = self.entries()

        if operation.action == "add":
            content = (operation.content or "").strip()
            if content in before:
                # Exact duplicate. Succeeding with no change beats an error:
                # two passes independently learning the same thing is normal.
                return Plan(self.target, operation, before, before, no_op=True)
            after = before + [content]
            self._check_limit(before, after)
            return Plan(self.target, operation, before, after)

        index = self._locate(operation.old_text or "", before)

        if operation.action == "remove":
            after = before[:index] + before[index + 1 :]
            return Plan(self.target, operation, before, after)

        content = (operation.content or "").strip()
        after = before[:index] + [content] + before[index + 1 :]
        # replace is bounded too: swapping an entry for a longer one can
        # overflow just as an add can.
        self._check_limit(before, after)
        return Plan(self.target, operation, before, after)

    def commit(self, plan: Plan) -> Plan:
        """Write a plan's result to disk."""
        if not plan.no_op:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(serialise(plan.after), encoding="utf-8")
        return plan

    def execute(self, operation: Operation) -> Plan:
        """Plan and commit in one step, for callers with nothing to review."""
        return self.commit(self.plan(operation))

    # -- internals ----------------------------------------------------------

    def _check_limit(self, before: list[str], after: list[str]) -> None:
        projected = usage_of(after)
        if projected <= self.limit:
            return
        raise MemoryFull(
            entries=before,
            usage=usage_of(before),
            limit=self.limit,
            needed=projected - self.limit,
        )

    @staticmethod
    def _locate(needle: str, entries: list[str]) -> int:
        needle = needle.strip()
        hits = [i for i, entry in enumerate(entries) if needle in entry]
        if not hits:
            raise NoMatch(needle, entries)
        if len(hits) > 1:
            raise AmbiguousMatch(needle, [entries[i] for i in hits])
        return hits[0]
