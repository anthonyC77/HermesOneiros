"""Translating a human query into FTS5 syntax.

This module exists because a raw user query is **not** valid FTS5. Passing one
through unmodified is not a degraded search, it is a crash: an apostrophe, a
stray ``*``, an unbalanced quote or a bare ``NEAR`` all raise
``sqlite3.OperationalError`` rather than returning nothing. Anyone who has
shipped an FTS5 search has shipped this function; the only question is whether
they wrote it before or after the first bug report.

The approach is deliberately blunt: extract word-like tokens, quote every one
of them, and ``AND`` them together. Quoting neutralises the whole operator
grammar — ``NEAR``, ``OR``, ``*``, ``^``, parentheses and quotes all become
literal text to match. Users lose the ability to write FTS5 by hand, which they
were not doing, and gain a search that never explodes.
"""

from __future__ import annotations

import re

__all__ = ["build_match", "tokenise"]

#: Word-like runs. Unicode-aware so accented and non-Latin queries survive;
#: internal dots and dashes are kept so ``config.json`` and ``pre-commit``
#: stay single tokens.
_TOKEN = re.compile(r"[^\W_]+(?:[.\-_][^\W_]+)*", re.UNICODE)

#: Below this length a prefix wildcard matches most of the index, so the last
#: token is only widened when it is substantial enough to be selective.
_MIN_PREFIX = 3


def tokenise(query: str) -> list[str]:
    """Extract word-like tokens, discarding punctuation and operators."""
    return _TOKEN.findall(query or "")


def build_match(query: str, prefix: bool = True) -> str | None:
    """Return an FTS5 ``MATCH`` expression, or ``None`` if there is nothing to search.

    ``None`` rather than an empty string: an empty MATCH is a syntax error, and
    returning it would push the failure into the caller's SQL. The caller is
    expected to short-circuit to "no results".

    ``prefix`` widens the final token (``depl`` → ``depl*``), which is what
    makes incremental typing feel responsive. Turn it off for exact recall.
    """
    tokens = tokenise(query)
    if not tokens:
        return None

    quoted = [f'"{token}"' for token in tokens]
    if prefix and len(tokens[-1]) >= _MIN_PREFIX:
        # A prefix wildcard binds outside the quotes in FTS5: "depl"* is valid,
        # "depl*" would match a literal asterisk.
        quoted[-1] = f'{quoted[-1]}*'

    return " AND ".join(quoted)
