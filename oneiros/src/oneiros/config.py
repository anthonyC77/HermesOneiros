"""Path resolution and configuration.

Every other module resolves its filesystem locations through here. That is the
whole point: an operator who moves the state directory moves all of it at once,
and there is a single place to look when two components disagree about where
something lives.

Two directories are *not* ours and are treated differently:

``~/.claude/skills``
    Owned by the harness. We write into it, but only skills that have earned
    their way there — see the quarantine rule in SPEC.md §5.5.

``~/.claude/projects``
    Read-only input. Never created, never written. It holds the transcripts the
    session index feeds on, and creating it would mask a misconfiguration by
    making an empty index look like an empty history.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

#: Explicit override, checked first.
STATE_ENV = "ONEIROS_HOME"
#: Set by the harness when the plugin is installed normally.
PLUGIN_DATA_ENV = "CLAUDE_PLUGIN_DATA"
#: Credentials live apart from configuration; see :func:`load_env`.
ENV_FILE_NAME = "oneiros.env"

DEFAULT_MODEL = "claude-opus-5"
#: Auxiliary slots resolve to the main model unless the operator says otherwise.
#: Routing a pass to a cheaper model is a cost/quality trade-off that belongs to
#: the operator, so nothing here degrades silently.
AUTO = "auto"


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def state_dir() -> Path:
    """Return the state directory, creating it if needed.

    The resolution order is duplicated verbatim in the hooks, which cannot
    import this module (they run as bare subprocesses under an unknown
    interpreter). Any divergence gives an operator who sets ``ONEIROS_HOME``
    two state directories that each hold half the truth — so if this changes,
    ``plugin/hooks/_state.py`` changes in the same commit.
    """
    for var in (STATE_ENV, PLUGIN_DATA_ENV):
        raw = os.environ.get(var, "").strip()
        if raw:
            path = Path(raw).expanduser()
            break
    else:
        path = Path.home() / ".claude" / "oneiros"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sub(*parts: str) -> Path:
    path = state_dir().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_dir() -> Path:
    """Curated memory: MEMORY.md and USER.md."""
    return _sub("memory")


def pending_dir() -> Path:
    """Writes held for approval — see :mod:`oneiros.memory.gate`."""
    return _sub("pending")


def dreams_dir() -> Path:
    """Dream journal, run records, and the quarantine."""
    return _sub("dreams")


def quarantine_dir() -> Path:
    """Where dreamed artefacts wait.

    Deliberately under the state directory rather than ``~/.claude/skills``:
    the harness never looks here, so a quarantined artefact is inert by
    construction rather than by convention (SPEC.md E18).
    """
    return _sub("dreams", "pending")


def archive_dir() -> Path:
    """Archived skills. Curation archives; it never deletes (SPEC.md E11)."""
    return _sub("archive")


def backups_dir() -> Path:
    """Pre-pass snapshots of the skill tree (SPEC.md E11)."""
    return _sub("backups")


def reports_dir() -> Path:
    """One timestamped directory per pass (SPEC.md E12)."""
    return _sub("reports")


def skills_dir() -> Path:
    """Where the harness discovers skills.

    Not under the state directory: a skill written anywhere else silently never
    loads, which is a failure mode with no error message attached.
    """
    path = Path.home() / ".claude" / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcripts_dir() -> Path:
    """Harness session transcripts. Read-only input — never created."""
    return Path.home() / ".claude" / "projects"


#: Every state-owned directory, in the order ``doctor`` reports them.
DERIVED_DIRS = (
    memory_dir,
    pending_dir,
    dreams_dir,
    archive_dir,
    backups_dir,
    reports_dir,
)


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #

def load_env(path: Path | None = None) -> dict[str, str]:
    """Load the credentials file into ``os.environ`` and return what it held.

    Long-lived processes are not launched from an interactive shell, so
    something has to put credentials in the environment. An already-exported
    variable always wins: an operator who exported a value deliberately should
    not have it overwritten by a stale file.

    This file is for **secrets only**. Thresholds, intervals and display
    preferences belong in ``config.json`` — a value that is not a secret but
    lives here is a value nobody can find later.
    """
    target = path or (Path.home() / ".claude" / ENV_FILE_NAME)
    loaded: dict[str, str] = {}
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return loaded

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    """Runtime configuration, read from ``config.json`` in the state directory."""

    # --- models -----------------------------------------------------------
    model: str = DEFAULT_MODEL
    #: Model for the post-turn review fork (SPEC.md E7).
    review_model: str = AUTO
    #: Model for dream passes (SPEC.md §5).
    dream_model: str = AUTO

    # --- memory (SPEC.md E1, E5) ------------------------------------------
    memory_char_limit: int = 2200
    user_char_limit: int = 1375
    #: Gate for foreground writes: off | staged | always.
    #: Automatic writes are staged regardless — see gate.py, where the default
    #: depends on the *origin* of the write, not on this setting.
    memory_gate: str = "off"
    skill_gate: str = "staged"

    # --- skill lifecycle (SPEC.md E8) -------------------------------------
    stale_after_days: int = 30
    archive_after_days: int = 90
    backup_keep: int = 5

    # --- dreaming (SPEC.md §5) --------------------------------------------
    dream_interval_hours: float = 24.0
    dream_min_idle_hours: float = 2.0
    #: The generative phase is opt-in. Consolidation (NREM) always runs.
    rem_enabled: bool = False
    rem_token_budget: int = 20_000
    rem_max_tasks: int = 5
    rem_wall_clock_seconds: int = 1800

    # --- sessions ---------------------------------------------------------
    #: Whether a dream may seed itself from other projects' transcripts. More
    #: material, but context leaks across project boundaries. Default: no.
    dream_cross_project: bool = False

    # --- driving the harness (SPEC.md §6) ---------------------------------
    workspace: str = str(Path.home() / "oneiros-workspace")
    permission_mode: str = "acceptEdits"

    def resolve_model(self, slot: str) -> str:
        """Resolve an auxiliary slot to a concrete model id.

        ``auto`` means the main model. A typo in a slot name resolves to the
        main model too rather than raising: a misconfigured auxiliary should
        degrade to something that works, not stop background work on a headless
        machine with nobody watching the logs.
        """
        chosen = getattr(self, f"{slot}_model", AUTO)
        return self.model if not chosen or chosen == AUTO else str(chosen)

    def workspace_path(self) -> Path:
        path = Path(self.workspace).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load configuration, falling back to defaults on anything unreadable.

        A corrupt config file must not stop the agent: the defaults are usable,
        and ``doctor`` is where a malformed file gets reported.
        """
        target = path or (state_dir() / "config.json")
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> Path:
        target = path or (state_dir() / "config.json")
        payload: dict[str, Any] = {f.name: getattr(self, f.name) for f in fields(self)}
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        return target
