"""T05 / T06 — memory format, bounds, and write semantics."""

from __future__ import annotations

import pytest

from oneiros.memory.store import (
    AmbiguousMatch,
    MemoryFull,
    NoMatch,
    Operation,
    Store,
    Target,
    parse,
    serialise,
    usage_of,
)


def make_store(tmp_path, limit=2200) -> Store:
    return Store(tmp_path / "MEMORY.md", limit, Target.MEMORY)


# --------------------------------------------------------------------------- #
# Format
# --------------------------------------------------------------------------- #

TWELVE_ENTRIES = [
    "Runs Windows 10 with Git Bash; POSIX scripts go through the Bash tool.",
    "Project ~/code/api uses Go 1.22, sqlc, chi. Tests: make test.",
    "Multi-line entry one:\n  - first detail\n  - second detail",
    "Prefers terse replies; dislikes preamble.",
    "Staging is 10.0.1.50 on SSH port 2222.",
    "Multi-line entry two:\nthe second line explains the first,\nand the third qualifies both.",
    "CI runs on GitHub Actions, workflow .github/workflows/test.yml.",
    "Do not run migrations without asking; they are irreversible here.",
    "Multi-line entry three:\n\tindented with a tab on purpose",
    "Uses pnpm, not npm. Lockfile conflicts are resolved by regenerating.",
    "Timezone Europe/Paris; expects dates written out, not relative.",
    "The parser drops trailing commas — known, tracked in issue 214.",
]


def test_round_trip_is_byte_exact():
    """Twelve entries, three of them multi-line, survive a full cycle."""
    canonical = serialise(TWELVE_ENTRIES)
    assert serialise(parse(canonical)) == canonical
    assert parse(canonical) == TWELVE_ENTRIES


def test_multiline_entries_are_not_split():
    entries = parse(serialise(TWELVE_ENTRIES))
    assert sum(1 for e in entries if "\n" in e) == 3


def test_usage_ignores_separators():
    """Separators are format, not content, and must not count against the limit."""
    entries = ["abc", "de"]
    assert usage_of(entries) == 5
    assert len(serialise(entries)) > 5


def test_crlf_is_normalised():
    assert parse("a\r\n§\r\nb") == ["a", "b"]


def test_empty_store_reads_as_no_entries(tmp_path):
    assert make_store(tmp_path).entries() == []


def test_header_reports_usage(tmp_path):
    store = make_store(tmp_path, limit=100)
    store.execute(Operation("add", content="x" * 40))
    header = store.header()
    assert "40%" in header and "40/100" in header


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def test_add_appends(tmp_path):
    store = make_store(tmp_path)
    store.execute(Operation("add", content="first"))
    store.execute(Operation("add", content="second"))
    assert store.entries() == ["first", "second"]


def test_exact_duplicate_is_a_no_op_not_an_error(tmp_path):
    store = make_store(tmp_path)
    store.execute(Operation("add", content="the same thing"))
    plan = store.execute(Operation("add", content="the same thing"))
    assert plan.no_op is True
    assert store.entries() == ["the same thing"]


def test_replace_matches_by_unique_substring(tmp_path):
    store = make_store(tmp_path)
    store.execute(Operation("add", content="User prefers dark mode in all editors"))
    store.execute(Operation("add", content="Deploys happen on Fridays"))
    store.execute(
        Operation("replace", old_text="dark mode", content="User prefers light mode in VS Code")
    )
    assert store.entries() == [
        "User prefers light mode in VS Code",
        "Deploys happen on Fridays",
    ]


def test_ambiguous_substring_names_the_candidates(tmp_path):
    store = make_store(tmp_path)
    store.execute(Operation("add", content="deploy runs on Friday"))
    store.execute(Operation("add", content="deploy is blocked on review"))

    with pytest.raises(AmbiguousMatch) as caught:
        store.plan(Operation("remove", old_text="deploy"))

    assert len(caught.value.matches) == 2
    assert "Friday" in str(caught.value)
    assert "review" in str(caught.value)


def test_no_match_is_explicit(tmp_path):
    store = make_store(tmp_path)
    store.execute(Operation("add", content="something"))
    with pytest.raises(NoMatch):
        store.plan(Operation("remove", old_text="absent"))


def test_remove_drops_exactly_one(tmp_path):
    store = make_store(tmp_path)
    store.execute(Operation("add", content="keep me"))
    store.execute(Operation("add", content="drop me"))
    store.execute(Operation("remove", old_text="drop"))
    assert store.entries() == ["keep me"]


# --------------------------------------------------------------------------- #
# Saturation — the behaviour the whole design turns on
# --------------------------------------------------------------------------- #

def test_overflowing_add_raises_and_lists_current_entries(tmp_path):
    store = make_store(tmp_path, limit=60)
    store.execute(Operation("add", content="a" * 30))
    store.execute(Operation("add", content="b" * 25))

    with pytest.raises(MemoryFull) as caught:
        store.plan(Operation("add", content="c" * 20))

    error = caught.value
    assert error.entries == ["a" * 30, "b" * 25], "the caller needs to see what to consolidate"
    assert error.usage == 55
    assert error.limit == 60
    assert error.needed == 15
    assert "Consolidate now" in str(error)


def test_nothing_is_written_when_an_add_overflows(tmp_path):
    store = make_store(tmp_path, limit=40)
    store.execute(Operation("add", content="x" * 35))
    with pytest.raises(MemoryFull):
        store.execute(Operation("add", content="y" * 10))
    assert store.entries() == ["x" * 35], "no silent eviction, no partial write"


def test_replace_is_bounded_too(tmp_path):
    """Swapping an entry for a longer one can overflow just as an add can."""
    store = make_store(tmp_path, limit=50)
    store.execute(Operation("add", content="short"))
    store.execute(Operation("add", content="z" * 40))

    with pytest.raises(MemoryFull):
        store.plan(Operation("replace", old_text="short", content="w" * 20))


def test_consolidate_then_retry_succeeds(tmp_path):
    """The documented recovery path, end to end, in one turn."""
    first = "project uses Go 1.22 for the API"
    second = "project uses sqlc for queries"
    third = "project uses chi for routing"
    merged = "project: Go 1.22 + sqlc"

    # Room for the first two and nothing more. Derived rather than hardcoded so
    # the test does not silently stop testing overflow if the strings change.
    limit = len(first) + len(second) + 5
    store = make_store(tmp_path, limit=limit)
    store.execute(Operation("add", content=first))
    store.execute(Operation("add", content=second))

    with pytest.raises(MemoryFull):
        store.plan(Operation("add", content=third))

    # Merge the two overlapping entries, then retry — exactly what the error says.
    store.execute(Operation("replace", old_text="Go 1.22", content=merged))
    store.execute(Operation("remove", old_text="sqlc for queries"))
    store.execute(Operation("add", content=third))

    assert store.entries() == [merged, third]
    assert store.usage() <= limit


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #

def test_plan_does_not_touch_disk(tmp_path):
    store = make_store(tmp_path)
    store.plan(Operation("add", content="not written"))
    assert store.entries() == []


def test_plan_diff_shows_both_sides(tmp_path):
    store = make_store(tmp_path)
    store.execute(Operation("add", content="old value"))
    plan = store.plan(Operation("replace", old_text="old", content="new value"))
    diff = plan.diff()
    assert "- old value" in diff
    assert "+ new value" in diff


def test_operation_rejects_incoherent_requests():
    with pytest.raises(ValueError):
        Operation("add", content="  ")
    with pytest.raises(ValueError):
        Operation("remove")
    with pytest.raises(ValueError):
        Operation("replace", old_text="x")
