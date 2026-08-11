"""Path resolution for the hooks.

**This module imports nothing from ``oneiros``, and that is deliberate.** The
harness runs hooks as bare subprocesses under an interpreter it chooses, and
there is no guarantee that interpreter has ever seen the package — a user can
link the plugin without installing the Python distribution, and the harness can
resolve a different Python than the one the package lives in. A hook that only
works when the stars align is a hook that fails silently and intermittently.

So: standard library only. The cost is that the state-directory resolution order
is duplicated from :func:`oneiros.config.state_dir`. That duplication is the
price of the guarantee, and it is bounded: if the order changes there, it
changes here in the same commit, and the tests assert the two agree.

Unlike the package's version, nothing here creates a directory. A hook is a
read-only observer of state; a hook that creates ``~/.claude/oneiros`` as a
side effect would make a misconfigured install look like a working one.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["STATE_ENV", "PLUGIN_DATA_ENV", "state_dir", "memory_dir"]

#: Explicit override, checked first.
STATE_ENV = "ONEIROS_HOME"
#: Set by the harness when the plugin is installed normally.
PLUGIN_DATA_ENV = "CLAUDE_PLUGIN_DATA"


def state_dir() -> Path:
    """Where oneiros keeps its state.

    Duplicated verbatim from :func:`oneiros.config.state_dir` — see the module
    docstring. Any divergence gives an operator who sets ``ONEIROS_HOME`` two
    state directories that each hold half the truth.
    """
    for var in (STATE_ENV, PLUGIN_DATA_ENV):
        raw = os.environ.get(var, "").strip()
        if raw:
            return Path(raw).expanduser()
    return Path.home() / ".claude" / "oneiros"


def memory_dir() -> Path:
    """Curated memory: MEMORY.md and USER.md."""
    return state_dir() / "memory"
