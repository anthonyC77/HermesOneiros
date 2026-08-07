"""T11 / T12 / T13 — reading transcripts, indexing them, and querying safely."""

from __future__ import annotations

import time

import pytest

from conftest import write_transcript
from oneiros.sessions.index import Index
from oneiros.sessions.query import build_match, tokenise
from oneiros.sessions.reader import iter_transcripts, read_transcript

CONVERSATION = [
    {
        "type": "user",
        "uuid": "u1",
        "sessionId": "sess-alpha",
        "timestamp": "2026-08-01T10:00:00Z",
        "message": {"role": "user", "content": "how do I fix the connection pool"},
    },
    {
        "type": "assistant",
        "uuid": "a1",
        "sessionId": "sess-alpha",
        "timestamp": "2026-08-01T10:00:12Z",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Raise the pool size and add a timeout."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "pytest tests/db"}},
            ],
        },
    },
    {
        "type": "user",
        "uuid": "u2",
        "sessionId": "sess-alpha",
        "isSidechain": True,
        "message": {"role": "user", "content": "subagent chatter nobody searches for"},
    },
    {
        "type": "user",
        "uuid": "u3",
        "sessionId": "sess-alpha",
        "isMeta": True,
        "message": {"role": "user", "content": "harness bookkeeping"},
    },
    {
        "type": "user",
        "uuid": "u4",
        "sessionId": "sess-alpha",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": "ten thousand lines of log output"}],
        },
    },
    '{"type": "assistant", "message": {"role": "assist',  # truncated mid-write
]


# --------------------------------------------------------------------------- #
# T11 — reader
# --------------------------------------------------------------------------- #

def test_reader_keeps_conversation_and_drops_the_rest(transcripts):
    path = write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
    records = list(read_transcript(path))

    texts = "\n".join(r.text for r in records)
    assert len(records) == 2
    assert "connection pool" in texts
    assert "subagent chatter" not in texts, "sidechain entries are not conversation"
    assert "bookkeeping" not in texts, "meta entries are not conversation"
    assert "ten thousand lines" not in texts, "tool results are bulk, not signal"


def test_tool_inputs_are_indexed(transcripts):
    """'Which command did I run against staging' is a real question."""
    path = write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
    texts = "\n".join(r.text for r in read_transcript(path))
    assert "pytest tests/db" in texts
    assert "[Bash]" in texts


def test_a_truncated_last_line_does_not_take_the_file_down(transcripts):
    path = write_transcript(transcripts, "proj", "live", CONVERSATION)
    assert len(list(read_transcript(path))) == 2


def test_huge_tool_inputs_are_bounded(transcripts):
    path = write_transcript(
        transcripts,
        "proj",
        "big",
        [
            {
                "type": "assistant",
                "uuid": "a",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Write", "input": {"content": "x" * 50_000}}
                    ],
                },
            }
        ],
    )
    record = next(read_transcript(path))
    assert len(record.text) < 1000, "one Write must not outweigh a hundred messages"


def test_reader_survives_a_shape_it_has_never_seen(transcripts):
    path = write_transcript(
        transcripts,
        "proj",
        "weird",
        [
            {"type": "user", "message": {"role": "user", "content": [{"type": "future_block"}]}},
            {"type": "summary", "summary": "not a message"},
            [1, 2, 3],
            {"message": None},
        ],
    )
    assert list(read_transcript(path)) == []


def test_missing_projects_directory_yields_nothing(tmp_path):
    assert list(iter_transcripts(tmp_path / "absent")) == []


# --------------------------------------------------------------------------- #
# T12 — index
# --------------------------------------------------------------------------- #

@pytest.fixture
def index(tmp_path):
    with Index(tmp_path / "sessions.db") as idx:
        yield idx


def test_indexing_then_searching(index, transcripts):
    write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
    seen, touched = index.refresh(transcripts)
    assert (seen, touched) == (1, 1)

    hits = index.search("connection pool")
    assert len(hits) == 1
    assert hits[0].session_id == "sess-alpha"
    assert hits[0].project == "proj"
    assert "«" in hits[0].snippet


def test_second_pass_reindexes_nothing(index, transcripts):
    write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
    index.refresh(transcripts)
    seen, touched = index.refresh(transcripts)
    assert (seen, touched) == (1, 0), "unchanged transcripts must not be re-read"


def test_only_the_changed_file_is_reindexed(index, transcripts):
    write_transcript(transcripts, "proj", "one", CONVERSATION)
    write_transcript(transcripts, "proj", "two", CONVERSATION)
    index.refresh(transcripts)

    time.sleep(0.01)
    write_transcript(
        transcripts,
        "proj",
        "two",
        CONVERSATION
        + [
            {
                "type": "user",
                "uuid": "u9",
                "sessionId": "sess-beta",
                "message": {"role": "user", "content": "a brand new question about caching"},
            }
        ],
    )

    seen, touched = index.refresh(transcripts)
    assert (seen, touched) == (2, 1)
    assert len(index.search("caching")) == 1


def test_reindexing_does_not_duplicate_rows(index, transcripts):
    path = write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
    index.refresh(transcripts)
    before = index.stats().messages

    path.touch()
    time.sleep(0.01)
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    index.refresh(transcripts)

    assert index.stats().messages == before


def test_stats_describe_the_corpus(index, transcripts):
    write_transcript(transcripts, "alpha", "s1", CONVERSATION)
    write_transcript(transcripts, "beta", "s2", CONVERSATION)
    index.refresh(transcripts)
    stats = index.stats()
    assert stats.files == 2
    assert stats.projects == 2
    assert "messages" in stats.describe()


def test_search_can_be_scoped_to_a_project(index, transcripts):
    write_transcript(transcripts, "alpha", "s1", CONVERSATION)
    write_transcript(transcripts, "beta", "s2", CONVERSATION)
    index.refresh(transcripts)
    assert len(index.search("connection pool")) == 2
    assert len(index.search("connection pool", project="alpha")) == 1


def test_recent_returns_newest_first(index, transcripts):
    write_transcript(transcripts, "proj", "s1", CONVERSATION)
    index.refresh(transcripts)
    recent = index.recent(5)
    assert recent
    assert recent[0].timestamp >= recent[-1].timestamp


# --------------------------------------------------------------------------- #
# T13 — query translation
# --------------------------------------------------------------------------- #

HOSTILE = [
    '"',
    '"unbalanced',
    "NEAR",
    "NEAR(a b)",
    "*",
    "**",
    "^caret",
    "a AND b",
    "a OR b",
    "a and b",
    "(parens)",
    "trailing-",
    "-leading",
    "l'apostrophe",
    "accentué café",
    "日本語のクエリ",
    "",
    "   ",
    "!@#$%^&*()",
    'a "b" c',
    "path/to/file.py:42",
    "config.json",
    "pre-commit",
    "100%",
    "\\backslash",
    "; DROP TABLE messages; --",
]


@pytest.mark.parametrize("query", HOSTILE, ids=range(len(HOSTILE)))
def test_hostile_queries_never_raise(query):
    build_match(query)  # must not raise


@pytest.mark.parametrize("query", HOSTILE, ids=range(len(HOSTILE)))
def test_hostile_queries_never_reach_sqlite_as_syntax(index, transcripts, query):
    write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
    index.refresh(transcripts)
    index.search(query)  # must not raise


def test_empty_query_is_none_not_empty_string():
    """An empty MATCH is a syntax error; returning None makes the caller
    short-circuit instead of pushing the failure into SQL."""
    assert build_match("") is None
    assert build_match("   ") is None
    assert build_match("!!!") is None


def test_operators_are_matched_literally_not_interpreted(index, transcripts):
    write_transcript(
        transcripts,
        "proj",
        "s",
        [
            {
                "type": "user",
                "uuid": "u",
                "sessionId": "s",
                "message": {"role": "user", "content": "the NEAR keyword is a red herring"},
            }
        ],
    )
    index.refresh(transcripts)
    assert len(index.search("NEAR keyword")) == 1


def test_dotted_and_hyphenated_names_stay_whole():
    assert tokenise("config.json and pre-commit") == ["config.json", "and", "pre-commit"]


def test_last_token_gets_a_prefix_wildcard():
    assert build_match("connection poo") == '"connection" AND "poo"*'
    assert build_match("connection poo", prefix=False) == '"connection" AND "poo"'
    assert build_match("ab") == '"ab"', "too short to be selective"


def test_prefix_search_finds_partial_words(index, transcripts):
    write_transcript(transcripts, "proj", "s", CONVERSATION)
    index.refresh(transcripts)
    assert index.search("connect")
