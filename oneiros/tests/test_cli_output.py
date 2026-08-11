"""What the CLI prints, and on what console it survives.

The memory block is framed with U+2550 and separated by U+00A7, and past
sessions hold whatever anyone has ever pasted into a terminal. None of that
survives the Windows default codepage, so ``memory show`` on a non-empty store
died with a ``UnicodeEncodeError`` — a crash on the one command whose whole job
is to let a human read what the agent is about to be told.

The text is not negotiable: it is prompt material and must stay byte-identical
to what the agent sees. The console bends instead.

These run the CLI as a subprocess with ``PYTHONIOENCODING`` forced, because that
is the real condition. Swapping ``sys.stdout`` in-process fights pytest's own
capture and proves less.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from oneiros.memory import render
from oneiros.memory.store import Target

#: Characters chosen to break cp1252 specifically: box rule, CJK, a check mark.
ENTRIES = "prefers pytest over unittest\n§\nthe Mac serves on 1234 — 内容 ✓\n"


@pytest.fixture
def stored(isolated_state):
    base = isolated_state / "memory"
    base.mkdir(parents=True, exist_ok=True)
    (base / Target.MEMORY.filename).write_text(ENTRIES, encoding="utf-8")
    render.reset()
    return isolated_state


def run(home: Path, *args: str, encoding: str = "cp1252") -> subprocess.CompletedProcess:
    """Invoke the CLI the way a stock Windows terminal would."""
    env = {
        # Path.home() is read at import time for a config default, so the
        # home-pointing variables have to survive.
        k: v
        for k, v in os.environ.items()
        if k in {"SYSTEMROOT", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME", "PATH", "TEMP"}
    }
    env.update(
        {
            "ONEIROS_HOME": str(home),
            "PYTHONIOENCODING": encoding,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
    )
    env.pop("CLAUDE_PLUGIN_DATA", None)
    return subprocess.run(
        [sys.executable, "-m", "oneiros", *args],
        capture_output=True,
        env=env,
        timeout=60,
    )


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "utf-8"])
def test_memory_show_survives_a_narrow_console(stored, encoding):
    """The regression: this exited non-zero on the box-drawing rule."""
    result = run(stored, "memory", "show", encoding=encoding)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"UnicodeEncodeError" not in result.stderr


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_doctor_survives_a_narrow_console(stored, encoding):
    result = run(stored, "doctor", encoding=encoding)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout.strip() != b""


def test_the_printed_block_is_what_the_agent_sees(stored):
    """No sanitising on the way out: a reader must see the real bytes."""
    result = run(stored, "memory", "show")
    # The console translates line endings; the characters are what is under test.
    printed = result.stdout.decode("utf-8", "replace").replace("\r\n", "\n")

    expected = render.capture(force=True).text
    assert expected in printed
    assert "内容 ✓" in printed


def test_sessions_search_survives_a_narrow_console(stored):
    """Past sessions hold arbitrary pasted text; the reader must not die on it."""
    result = run(stored, "sessions", "search", "内容", encoding="cp1252")

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
