"""The SessionStart hook that carries curated memory into a live session.

Three promises are under test, and only the first is about behaviour:

1. it renders what the package renders, and freezes it for the session (I1);
2. it stays in sync with the code it duplicates — ``config.state_dir`` and the
   memory rendering — because duplication that drifts is worse than a
   dependency;
3. it runs under an interpreter that has never seen ``oneiros``, which is the
   whole reason the duplication exists.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from oneiros import config as cfg
from oneiros.memory import render as pkg_render
from oneiros.memory.store import Target

HOOKS_DIR = Path(__file__).resolve().parents[1] / "plugin" / "hooks"


def _load(name: str):
    """Import a hook module the way the harness does: by file, from its directory."""
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


hook = _load("session_start_memory")
_state = _load("_state")


@pytest.fixture
def memory(isolated_state):
    """A memory directory, with a helper to fill it."""
    base = isolated_state / "memory"
    base.mkdir(parents=True, exist_ok=True)

    def write(memory_text: str = "", user_text: str = "") -> Path:
        (base / "MEMORY.md").write_text(memory_text, encoding="utf-8")
        (base / "USER.md").write_text(user_text, encoding="utf-8")
        return base

    write.base = base  # type: ignore[attr-defined]
    return write


# --------------------------------------------------------------------------- #
# The duplication contract
# --------------------------------------------------------------------------- #

def test_state_resolution_matches_the_package(isolated_state):
    assert _state.state_dir() == cfg.state_dir()


def test_state_resolution_matches_on_the_plugin_data_path(tmp_path, monkeypatch):
    monkeypatch.delenv(cfg.STATE_ENV, raising=False)
    monkeypatch.setenv(cfg.PLUGIN_DATA_ENV, str(tmp_path / "pd"))
    assert _state.state_dir() == cfg.state_dir()


def test_memory_dir_matches_the_package(isolated_state):
    assert _state.memory_dir() == cfg.memory_dir()


@pytest.mark.parametrize(
    "entries",
    [
        ["one fact"],
        ["first", "second", "third"],
        ["multi\nline\nentry", "another"],
        ["accentué — em dash, 1,234 chars"],
    ],
)
def test_rendering_matches_the_package(memory, entries):
    """If these diverge, the agent sees a different memory than `memory show`."""
    stored = "\n§\n".join(entries) + "\n"
    memory(memory_text=stored, user_text="a preference")

    stores = pkg_render.build_stores()
    assert hook.render() == pkg_render.render(stores)


def test_rendering_honours_a_configured_limit(memory, isolated_state):
    """The header drives consolidation; a stale cap makes it lie."""
    memory(memory_text="a fact\n")
    (isolated_state / "config.json").write_text(
        json.dumps({"memory_char_limit": 500}), encoding="utf-8"
    )

    stores = pkg_render.build_stores()
    assert hook.render() == pkg_render.render(stores)
    assert "/500 chars" in hook.render()


def test_hook_imports_nothing_from_the_package():
    """It runs under an interpreter that may never have seen oneiros."""
    for name in ("session_start_memory", "_state"):
        source = (HOOKS_DIR / f"{name}.py").read_text(encoding="utf-8")
        offenders = [
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from "))
            and ("oneiros" in line or line.startswith("from ."))
        ]
        assert offenders == [], f"{name}: package imports found: {offenders}"


def test_hook_creates_no_directories(isolated_state, monkeypatch):
    """A hook that creates the state directory makes a broken install look fine."""
    missing = isolated_state / "nowhere"
    monkeypatch.setenv(cfg.STATE_ENV, str(missing))

    assert hook.render() == ""
    assert hook.build_response({"session_id": "s1"}) is None
    assert not missing.exists()


# --------------------------------------------------------------------------- #
# I1 — one snapshot per session
# --------------------------------------------------------------------------- #

def test_the_snapshot_is_frozen_for_the_session(memory):
    """`compact` fires SessionStart again; it must not show a mid-session write."""
    memory(memory_text="original fact\n")
    first = hook.frozen_text("session-a")
    assert "original fact" in first

    memory(memory_text="rewritten fact\n")
    assert hook.frozen_text("session-a") == first, "a compact leaked a mid-session write"


def test_a_new_session_sees_the_new_memory(memory):
    """The cost of I1 is a one-session delay, not a permanent freeze."""
    memory(memory_text="original fact\n")
    hook.frozen_text("session-a")

    memory(memory_text="rewritten fact\n")
    assert "rewritten fact" in hook.frozen_text("session-b")


def test_an_unusable_cache_re_renders(memory, isolated_state):
    """A corrupt cache is a reason to render again, never a reason to fail."""
    memory(memory_text="a fact\n")
    (isolated_state / hook.CACHE_NAME).write_text("{not json", encoding="utf-8")

    assert "a fact" in hook.frozen_text("session-a")


def test_the_cache_does_not_accumulate(memory, isolated_state):
    """One file, overwritten — not one per session."""
    memory(memory_text="a fact\n")
    for i in range(5):
        hook.frozen_text(f"session-{i}")

    caches = list(isolated_state.glob(".session-snapshot*"))
    assert len(caches) == 1, caches


# --------------------------------------------------------------------------- #
# The response
# --------------------------------------------------------------------------- #

def test_empty_memory_says_nothing(memory):
    memory()
    assert hook.build_response({"session_id": "s1"}) is None


def test_response_carries_the_block_as_additional_context(memory):
    memory(memory_text="pytest over unittest\n", user_text="prefers French\n")
    response = hook.build_response({"session_id": "s1"})

    output = response["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert "pytest over unittest" in output["additionalContext"]
    assert "prefers French" in output["additionalContext"]
    assert Target.MEMORY.label in output["additionalContext"]


def test_the_block_is_framed_as_notes_not_instructions(memory):
    """Memory is system-prompt material (SPEC.md E4); it must not read as user input."""
    memory(memory_text="a fact\n")
    context = hook.build_response({"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
    assert hook.PREAMBLE in context


@pytest.mark.parametrize("payload", [{}, {"session_id": None}, {"session_id": 42}])
def test_a_payload_without_a_session_id_still_renders(memory, payload):
    """No id means no freeze, but never no memory."""
    memory(memory_text="a fact\n")
    response = hook.build_response(payload)
    assert "a fact" in response["hookSpecificOutput"]["additionalContext"]


# --------------------------------------------------------------------------- #
# End to end, as the harness runs it
# --------------------------------------------------------------------------- #

def _run(stdin: str, home: Path, executable: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [executable or sys.executable, str(HOOKS_DIR / "session_start_memory.py")],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"ONEIROS_HOME": str(home), "SYSTEMROOT": "", "PATH": ""},
        timeout=30,
    )


def test_runs_under_a_bare_interpreter(memory, isolated_state):
    """No PYTHONPATH, no install — the case the duplication exists for."""
    memory(memory_text="a durable fact\n")
    result = _run(json.dumps({"session_id": "s1", "source": "startup"}), isolated_state)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "a durable fact" in payload["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("stdin", ["", "   ", "not json", "[]", "null"])
def test_malformed_input_is_silent_and_successful(memory, isolated_state, stdin):
    """A hook that fails loudly puts a traceback in front of the user at startup."""
    memory(memory_text="a fact\n")
    result = _run(stdin, isolated_state)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_no_memory_produces_no_output(isolated_state):
    result = _run(json.dumps({"session_id": "s1"}), isolated_state)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


# --------------------------------------------------------------------------- #
# Declaration
# --------------------------------------------------------------------------- #

def test_hooks_json_declares_the_handler():
    declared = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    entries = declared["hooks"]["SessionStart"]
    commands = [h["command"] for entry in entries for h in entry["hooks"]]

    assert any("session_start_memory.py" in c for c in commands)
    assert all("${CLAUDE_PLUGIN_ROOT}" in c for c in commands), "a hard-coded path breaks on install"


def test_resume_is_not_matched():
    """The block is already in a resumed context; firing there would duplicate it."""
    declared = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    matchers = [e.get("matcher", "") for e in declared["hooks"]["SessionStart"]]

    assert all("resume" not in m for m in matchers), matchers
