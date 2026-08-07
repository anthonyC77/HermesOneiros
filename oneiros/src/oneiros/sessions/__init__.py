"""Recall across past sessions.

Memory holds the handful of facts that must be in *every* prompt. This holds
everything else: the full history, searched on demand, at no token cost. The
two are not competing designs — they answer different questions, and the split
is what keeps memory small enough to stay honest.
"""

from .index import Index, IndexStats, Hit
from .query import build_match
from .reader import Record, read_transcript, iter_transcripts

__all__ = [
    "Hit",
    "Index",
    "IndexStats",
    "Record",
    "build_match",
    "iter_transcripts",
    "read_transcript",
]
