"""T04 — doctor, the diagnostic everything else leans on."""

from __future__ import annotations

import json

import pytest

from oneiros import cli


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: home))
    return home


def write_settings(home, payload) -> None:
    (home / ".claude" / "settings.json").write_text(json.dumps(payload), encoding="utf-8")


def test_missing_registration_names_the_fix(fake_home):
    status, _, detail = cli._mcp_row()
    assert status == cli.WARN
    assert "mcp_server.py" in detail, "a warning without the command is a dead end"


def test_file_path_registration_is_accepted(fake_home):
    write_settings(
        fake_home,
        {"mcpServers": {"oneiros-sessions": {"command": "python", "args": ["/x/mcp_server.py"]}}},
    )
    status, _, detail = cli._mcp_row()
    assert status == cli.OK
    assert detail == "oneiros-sessions"


def test_module_registration_is_flagged_even_though_it_currently_works(fake_home):
    """`-m` needs the package importable — the one thing the server is written
    not to depend on. It works until the harness picks another interpreter."""
    write_settings(
        fake_home,
        {"mcpServers": {"s": {"command": "python", "args": ["-m", "oneiros.mcp_server"]}}},
    )
    status, _, detail = cli._mcp_row()
    assert status == cli.WARN
    assert "-m" in detail
    assert "mcp_server.py" in detail


def test_unrelated_servers_are_ignored(fake_home):
    write_settings(fake_home, {"mcpServers": {"other": {"command": "node", "args": ["x.js"]}}})
    assert cli._mcp_row()[0] == cli.WARN


def test_corrupt_settings_is_a_warning_not_a_crash(fake_home):
    (fake_home / ".claude" / "settings.json").write_text("{oh no", encoding="utf-8")
    assert cli._mcp_row()[0] == cli.WARN


def test_doctor_runs_and_reports_every_check(isolated_state, capsys):
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    for label in ("state directory", "session index", "MCP server", "agent SDK"):
        assert label in out
    assert exit_code in (0, 1)


def test_doctor_fails_when_the_state_directory_is_unusable(isolated_state, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_writable", lambda _path: False)
    assert cli.main(["doctor"]) == 1
    assert "[FAIL]" in capsys.readouterr().out
