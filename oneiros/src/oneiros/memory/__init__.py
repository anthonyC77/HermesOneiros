"""Curated, bounded memory that survives across sessions.

The distinction that matters here is *curated*, not *stored*. Anything can
append to a file; what makes memory useful is that it stays small enough to sit
in every prompt and honest enough to be trusted there. Both properties come
from refusing writes rather than accepting them:

- over the limit → an error the agent must resolve (:mod:`.store`)
- looks like an injection → refused outright (:mod:`.guard`)
- written by an unattended pass → staged for review (:mod:`.gate`)
"""

from .store import (
    AmbiguousMatch,
    MemoryRefused,
    MemoryFull,
    NoMatch,
    Operation,
    Plan,
    Store,
    Target,
)

__all__ = [
    "AmbiguousMatch",
    "MemoryRefused",
    "MemoryFull",
    "NoMatch",
    "Operation",
    "Plan",
    "Store",
    "Target",
]
