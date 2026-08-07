"""Test isolation.

Every test gets its own state directory. Nothing here may touch the real
``~/.claude`` — a test suite that writes into the user's actual memory is a
test suite that eventually corrupts it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oneiros import config as cfg
from oneiros.memory import render


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect the state directory and drop any captured memory snapshot."""
    home = tmp_path / "state"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(cfg.STATE_ENV, str(home))
    monkeypatch.delenv(cfg.PLUGIN_DATA_ENV, raising=False)
    render.reset()
    yield home
    render.reset()


@pytest.fixture
def config():
    return cfg.Config()


@pytest.fixture
def transcripts(tmp_path):
    """A projects directory, ready to be filled with transcripts."""
    root = tmp_path / "projects"
    root.mkdir()
    return root


def write_transcript(root: Path, project: str, name: str, entries: list) -> Path:
    """Write a JSONL transcript. Non-dict entries are written verbatim as text,
    which is how malformed-line handling gets exercised."""
    directory = root / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jsonl"
    lines = [
        entry if isinstance(entry, str) else json.dumps(entry)
        for entry in entries
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
