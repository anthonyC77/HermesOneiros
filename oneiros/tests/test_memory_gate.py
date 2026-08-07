"""T08 — the approval gate, and T09 — the frozen snapshot."""

from __future__ import annotations

import pytest

from oneiros import config as cfg
from oneiros.memory.gate import Gate, Origin
from oneiros.memory.render import build_stores, capture, reset
from oneiros.memory.store import MemoryFull, Operation, Target


@pytest.fixture
def wired(config):
    stores = build_stores(config)
    return config, stores, Gate(config)


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #

def test_foreground_writes_apply_immediately_by_default(wired):
    _, stores, gate = wired
    decision = gate.submit(
        stores[Target.MEMORY], Operation("add", content="a fact"), Origin.FOREGROUND
    )
    assert decision.applied is True
    assert stores[Target.MEMORY].entries() == ["a fact"]


@pytest.mark.parametrize("origin", [Origin.REVIEW, Origin.NREM])
def test_automatic_writes_stage_even_when_the_gate_is_off(wired, origin):
    """The setting exists so a user can tighten foreground writes — never so an
    unattended pass can loosen itself."""
    config, stores, gate = wired
    assert config.memory_gate == "off"

    decision = gate.submit(stores[Target.MEMORY], Operation("add", content="learned"), origin)

    assert decision.applied is False
    assert stores[Target.MEMORY].entries() == []
    assert decision.pending is not None
    assert decision.pending.origin == origin.value


def test_foreground_writes_stage_when_the_user_asks_for_it(config):
    config.memory_gate = "staged"
    stores = build_stores(config)
    gate = Gate(config)
    decision = gate.submit(
        stores[Target.MEMORY], Operation("add", content="x"), Origin.FOREGROUND
    )
    assert decision.applied is False


def test_invalid_writes_fail_now_rather_than_at_approval_time(wired):
    """A write that cannot succeed should not sit in a queue until someone
    approves it and only then turn out to be impossible."""
    config, stores, gate = wired
    store = stores[Target.MEMORY]
    store.limit = 20
    store.execute(Operation("add", content="x" * 18))

    with pytest.raises(MemoryFull):
        gate.submit(store, Operation("add", content="y" * 10), Origin.REVIEW)

    assert gate.pending() == []


# --------------------------------------------------------------------------- #
# Review
# --------------------------------------------------------------------------- #

def test_approve_applies_exactly_what_the_diff_showed(wired):
    _, stores, gate = wired
    decision = gate.submit(
        stores[Target.MEMORY], Operation("add", content="staged fact"), Origin.REVIEW
    )
    assert "+ staged fact" in decision.pending.diff

    gate.approve(decision.pending.id, lambda target: stores[target])

    assert stores[Target.MEMORY].entries() == ["staged fact"]
    assert gate.pending() == []


def test_approval_replans_against_current_state(wired):
    """Memory can change between staging and approval. Replaying a saved
    outcome would silently drop whatever landed in between."""
    _, stores, gate = wired
    store = stores[Target.MEMORY]

    decision = gate.submit(store, Operation("add", content="from the review"), Origin.REVIEW)
    store.execute(Operation("add", content="written meanwhile"))

    gate.approve(decision.pending.id, lambda target: stores[target])

    assert store.entries() == ["written meanwhile", "from the review"]


def test_approval_reports_failure_instead_of_forcing_it(wired):
    """If the store filled up after staging, approval must fail loudly."""
    _, stores, gate = wired
    store = stores[Target.MEMORY]
    store.limit = 60

    decision = gate.submit(store, Operation("add", content="b" * 30), Origin.REVIEW)
    store.execute(Operation("add", content="a" * 50))

    with pytest.raises(MemoryFull):
        gate.approve(decision.pending.id, lambda target: stores[target])


def test_reject_drops_without_writing(wired):
    _, stores, gate = wired
    decision = gate.submit(stores[Target.MEMORY], Operation("add", content="no"), Origin.NREM)
    gate.reject(decision.pending.id)
    assert gate.pending() == []
    assert stores[Target.MEMORY].entries() == []


def test_unknown_id_is_a_clear_error(wired):
    _, _, gate = wired
    with pytest.raises(KeyError):
        gate.reject("deadbeef")


def test_a_corrupt_pending_file_does_not_hide_the_readable_ones(wired):
    _, stores, gate = wired
    gate.submit(stores[Target.MEMORY], Operation("add", content="good"), Origin.REVIEW)
    (gate.root / "corrupt.json").write_text("{oh no", encoding="utf-8")
    assert len(gate.pending()) == 1


# --------------------------------------------------------------------------- #
# T09 — the frozen snapshot
# --------------------------------------------------------------------------- #

def test_snapshot_is_captured_once_per_session(config):
    stores = build_stores(config)
    stores[Target.MEMORY].execute(Operation("add", content="known at session start"))

    first = capture(config)
    stores[Target.MEMORY].execute(Operation("add", content="written mid-session"))
    second = capture(config)

    assert first is second
    assert "written mid-session" not in second.text, (
        "a prompt prefix that changes mid-conversation invalidates the cache "
        "for every turn after it"
    )


def test_a_new_session_sees_the_new_entry(config):
    stores = build_stores(config)
    stores[Target.MEMORY].execute(Operation("add", content="first"))
    capture(config)
    stores[Target.MEMORY].execute(Operation("add", content="second"))

    reset()  # what a new session does

    assert "second" in capture(config).text


def test_snapshot_renders_both_stores_with_headers(config):
    stores = build_stores(config)
    stores[Target.MEMORY].execute(Operation("add", content="an environment fact"))
    stores[Target.MEMORY].execute(Operation("add", content="a second fact"))
    stores[Target.USER].execute(Operation("add", content="prefers terse replies"))

    text = capture(config, force=True).text

    assert "MEMORY (your own notes)" in text
    assert "USER PROFILE" in text
    assert "an environment fact" in text
    assert "prefers terse replies" in text
    assert "\n§\n" in text, "entries within a store are separated"
    assert "1%" in text, "the header tells the agent when to consolidate"


def test_empty_memory_renders_nothing(config):
    snapshot = capture(config, force=True)
    assert snapshot.is_empty()
