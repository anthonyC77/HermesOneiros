"""T14 — the MCP server.

Two things are under test. The protocol surface, and the promise made in the
module docstring: that the duplication it carries stays in sync with the
package. Duplication that drifts is worse than a dependency.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conftest import write_transcript
from oneiros import config as cfg, mcp_server
from oneiros.sessions.index import Index
from oneiros.sessions.query import build_match as package_build_match
from test_sessions import CONVERSATION, HOSTILE


# --------------------------------------------------------------------------- #
# The duplication contract
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "query",
    HOSTILE + ["connection pool", "config.json", "pre-commit", "café", "a b c"],
)
def test_query_translation_matches_the_package(query):
    """If these diverge, the agent and the CLI silently search differently."""
    assert mcp_server.build_match(query) == package_build_match(query)


def test_state_resolution_matches_the_package(isolated_state):
    assert mcp_server.state_dir() == cfg.state_dir()


def test_state_resolution_matches_on_the_plugin_data_path(tmp_path, monkeypatch):
    monkeypatch.delenv(cfg.STATE_ENV, raising=False)
    monkeypatch.setenv(cfg.PLUGIN_DATA_ENV, str(tmp_path / "pd"))
    assert mcp_server.state_dir() == cfg.state_dir()


def test_server_imports_nothing_from_the_package():
    """The whole point of the file: it must run under an interpreter that has
    never heard of oneiros."""
    source = Path(mcp_server.__file__).read_text(encoding="utf-8")
    offenders = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
        and ("oneiros" in line or line.startswith("from ."))
    ]
    assert offenders == [], f"package imports found: {offenders}"


def test_server_runs_under_a_bare_interpreter(tmp_path, monkeypatch):
    """Launch it the way the harness would: no PYTHONPATH, no install."""
    script = Path(mcp_server.__file__)
    env = {
        "PATH": "",
        "ONEIROS_HOME": str(tmp_path / "state"),
        "SYSTEMROOT": "",
    }
    request = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
    result = subprocess.run(
        [sys.executable, "-E", "-S", str(script)],
        input=request,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"search_sessions"' in result.stdout


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #

def test_initialize_echoes_the_client_protocol_version():
    response = mcp_server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2099-01-01"}}
    )
    assert response["result"]["protocolVersion"] == "2099-01-01"
    assert response["result"]["serverInfo"]["name"] == "oneiros-sessions"
    assert "tools" in response["result"]["capabilities"]


def test_initialize_falls_back_when_the_client_says_nothing():
    response = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response["result"]["protocolVersion"] == mcp_server.DEFAULT_PROTOCOL


def test_tools_list_describes_when_to_call_each_tool():
    tools = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"search_sessions", "session_stats"}
    # A description that only says what a tool does gets called less than one
    # that says when to call it.
    assert "Use it when" in next(t for t in tools if t["name"] == "search_sessions")["description"]


def test_notifications_get_no_reply():
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_is_an_error_not_a_crash():
    response = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
    assert response["error"]["code"] == -32601


def test_unknown_tool_is_an_error():
    response = mcp_server.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}}
    )
    assert response["error"]["code"] == -32602


# --------------------------------------------------------------------------- #
# Behaviour
# --------------------------------------------------------------------------- #

def test_search_before_the_index_exists_says_what_to_do():
    body = mcp_server.do_search("anything")
    assert "oneiros sessions index" in body


def test_search_returns_matches(isolated_state, transcripts):
    with Index(isolated_state / "sessions.db") as index:
        write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
        index.refresh(transcripts)

    response = mcp_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "search_sessions", "arguments": {"query": "connection pool"}},
        }
    )
    text = response["result"]["content"][0]["text"]
    assert "1 match(es)" in text
    assert "sess-alp" in text


def test_stats_reports_the_corpus(isolated_state, transcripts):
    with Index(isolated_state / "sessions.db") as index:
        write_transcript(transcripts, "proj", "sess-alpha", CONVERSATION)
        index.refresh(transcripts)

    response = mcp_server.handle(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "session_stats", "arguments": {}}}
    )
    assert "2 messages" in response["result"]["content"][0]["text"]


def test_a_wordless_query_is_reported_not_executed():
    assert "no searchable words" in mcp_server.do_search("!!!")


def test_limit_is_clamped(isolated_state, transcripts):
    with Index(isolated_state / "sessions.db") as index:
        write_transcript(transcripts, "proj", "s", CONVERSATION)
        index.refresh(transcripts)
    # Absurd values must not reach SQLite unchecked.
    assert mcp_server.do_search("connection", limit=10**9)
    assert mcp_server.do_search("connection", limit=-5)
