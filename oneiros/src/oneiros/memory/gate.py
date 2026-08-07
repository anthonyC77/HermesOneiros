"""Approval gate for memory writes.

The gate answers one question: does this write land now, or wait for a human?

The answer depends on **where the write came from**, not only on how the gate is
configured. A write the user asked for during a conversation is theirs, and
holding it up is friction with no safety benefit. A write proposed by an
unattended pass — nobody watching, hours after the fact, on a cheap model — is
the one that ends up encoding a wrong assumption about the user, so it stages by
default no matter what the setting says.

Approval re-plans against the *current* store rather than replaying a saved
result. Memory can change between staging and approval; applying a stale
computed outcome would silently drop whatever landed in between.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from .. import config as cfg
from .store import Operation, Plan, Store, Target

__all__ = ["Origin", "Decision", "PendingWrite", "Gate", "StoreFactory"]

#: Maps a target to its store. Injected rather than built here so tests and the
#: CLI can point the gate at a temporary directory.
StoreFactory = Callable[[Target], Store]


class Origin(str, Enum):
    """Who asked for this write."""

    #: The user or the agent, during a live conversation.
    FOREGROUND = "foreground"
    #: The post-turn review fork (SPEC.md E7).
    REVIEW = "review"
    #: Consolidation during a dream pass (SPEC.md §5.3). Never generative — the
    #: REM phase has no path to this module at all (SPEC.md E14).
    NREM = "nrem"

    @property
    def is_automatic(self) -> bool:
        return self is not Origin.FOREGROUND


@dataclass(frozen=True)
class PendingWrite:
    """A staged write, on disk, awaiting a verdict."""

    id: str
    target: str
    action: str
    content: str | None
    old_text: str | None
    origin: str
    created_at: float
    diff: str

    @property
    def operation(self) -> Operation:
        return Operation(
            action=self.action,  # type: ignore[arg-type]
            content=self.content,
            old_text=self.old_text,
        )

    def summary(self) -> str:
        age_h = (time.time() - self.created_at) / 3600
        return f"{self.id}  [{self.origin}]  {self.action} → {self.target}  ({age_h:.0f}h ago)"


@dataclass
class Decision:
    """What the gate did with a submitted write."""

    applied: bool
    plan: Plan | None = None
    pending: PendingWrite | None = None
    notes: list[str] = field(default_factory=list)


class Gate:
    """Routes memory writes to disk or to the pending queue."""

    def __init__(self, config: cfg.Config | None = None, root: Path | None = None) -> None:
        self.config = config or cfg.Config.load()
        self.root = root or (cfg.pending_dir() / "memory")
        self.root.mkdir(parents=True, exist_ok=True)

    # -- policy -------------------------------------------------------------

    def should_stage(self, origin: Origin) -> bool:
        """Whether a write of this origin waits for approval.

        Automatic origins always stage. That is not configurable on purpose:
        the setting exists so a user can tighten foreground writes, not so an
        unattended pass can loosen itself.
        """
        if origin.is_automatic:
            return True
        setting = (self.config.memory_gate or "off").lower()
        return setting in ("staged", "always")

    # -- submission ---------------------------------------------------------

    def submit(self, store: Store, operation: Operation, origin: Origin) -> Decision:
        """Plan a write, then apply or stage it.

        Planning happens first in both branches: an invalid write should fail
        immediately with a useful error, not sit in a queue until someone
        approves it and only then turn out to be impossible.
        """
        plan = store.plan(operation)

        if plan.no_op:
            return Decision(applied=True, plan=plan, notes=["already present — no change"])

        if not self.should_stage(origin):
            store.commit(plan)
            return Decision(applied=True, plan=plan)

        return Decision(applied=False, pending=self._stage(plan, origin))

    def _stage(self, plan: Plan, origin: Origin) -> PendingWrite:
        entry = PendingWrite(
            id=uuid.uuid4().hex[:8],
            target=plan.target.value,
            action=plan.operation.action,
            content=plan.operation.content,
            old_text=plan.operation.old_text,
            origin=origin.value,
            created_at=time.time(),
            diff=plan.diff(),
        )
        payload = {
            "id": entry.id,
            "target": entry.target,
            "action": entry.action,
            "content": entry.content,
            "old_text": entry.old_text,
            "origin": entry.origin,
            "created_at": entry.created_at,
            "diff": entry.diff,
        }
        (self.root / f"{entry.id}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        return entry

    # -- review -------------------------------------------------------------

    def pending(self) -> list[PendingWrite]:
        found: list[PendingWrite] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue  # a corrupt entry must not hide the readable ones
            try:
                found.append(PendingWrite(**raw))
            except TypeError:
                continue
        return sorted(found, key=lambda w: w.created_at)

    def get(self, write_id: str) -> PendingWrite | None:
        return next((w for w in self.pending() if w.id == write_id), None)

    def approve(self, write_id: str, store_for: StoreFactory) -> Plan:
        """Apply a staged write, re-planned against the store as it is now."""
        entry = self.get(write_id)
        if entry is None:
            raise KeyError(f"no pending write {write_id!r}")
        store = store_for(Target(entry.target))
        plan = store.commit(store.plan(entry.operation))
        self._drop(write_id)
        return plan

    def reject(self, write_id: str) -> PendingWrite:
        entry = self.get(write_id)
        if entry is None:
            raise KeyError(f"no pending write {write_id!r}")
        self._drop(write_id)
        return entry

    def _drop(self, write_id: str) -> None:
        (self.root / f"{write_id}.json").unlink(missing_ok=True)


#: A callable mapping a target to its store. Passed in rather than built here so
#: tests and the CLI can point the gate at a temporary directory.
StoreFactory = "callable[[Target], Store]"  # documented alias; see cli.py
