"""Turning harness transcripts into indexable records.

The transcript format belongs to the harness, not to us, and it changes without
notice. So every field is read defensively: a key that moved, a line truncated
mid-write by a session that is still running, an entry shape nobody has seen
before — none of them may raise. A reader that throws on one malformed line
takes the whole index down with it, and the operator sees "indexing failed"
with no way to know that 6 999 of 7 000 messages were fine.

Two deliberate omissions:

**Tool results are not indexed.** They are the bulk of a transcript by volume
and almost never what someone is searching for. Tool *inputs* are indexed —
"which command did I run against staging" is a real question; "what did that
command print three weeks ago" is not.

**Sidechain and meta entries are skipped.** Subagent traces and harness
bookkeeping are not conversation, and indexing them makes every search return
the same scaffolding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

__all__ = ["Record", "read_transcript", "iter_transcripts"]

#: Content block types worth indexing, mapped to how their text is extracted.
_TEXT_BLOCKS = ("text", "thinking")


@dataclass(frozen=True)
class Record:
    """One indexable message."""

    session_id: str
    project: str
    role: str
    text: str
    uuid: str
    timestamp: str
    path: str


def iter_transcripts(root: Path) -> Iterator[Path]:
    """Every transcript under a projects directory, in a stable order."""
    if not root.is_dir():
        return
    yield from sorted(root.glob("*/*.jsonl"))


def read_transcript(path: Path) -> Iterator[Record]:
    """Yield records from one transcript, skipping anything unreadable."""
    project = path.parent.name
    fallback_session = path.stem

    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return

    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                # A live session may be mid-write on the last line. Skipping it
                # is correct: the next incremental pass picks it up complete.
                continue
            if not isinstance(entry, dict):
                continue
            record = _to_record(entry, project, fallback_session, str(path))
            if record is not None:
                yield record


def _to_record(
    entry: dict, project: str, fallback_session: str, path: str
) -> Record | None:
    if entry.get("isSidechain") or entry.get("isMeta"):
        return None

    message = entry.get("message")
    message = message if isinstance(message, dict) else {}

    role = str(message.get("role") or entry.get("type") or "").strip()
    if role not in ("user", "assistant"):
        return None

    text = _extract_text(message.get("content"))
    if not text:
        return None

    return Record(
        session_id=str(entry.get("sessionId") or fallback_session),
        project=project,
        role=role,
        text=text,
        uuid=str(entry.get("uuid") or ""),
        timestamp=str(entry.get("timestamp") or ""),
        path=path,
    )


def _extract_text(content: object) -> str:
    """Flatten message content to searchable text.

    Handles both shapes the harness emits — a bare string, or a list of typed
    blocks — and ignores block types it does not recognise rather than guessing
    at their contents.
    """
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in _TEXT_BLOCKS:
            value = block.get(kind if kind == "thinking" else "text")
            if isinstance(value, str):
                parts.append(value)
        elif kind == "tool_use":
            name = str(block.get("name") or "tool")
            parts.append(f"[{name}] {_flatten_input(block.get('input'))}")
        # tool_result and everything else: deliberately dropped.

    return "\n".join(p.strip() for p in parts if p and p.strip()).strip()


def _flatten_input(value: object, limit: int = 600) -> str:
    """Render a tool input compactly, bounded.

    Bounded because a single Write call can carry a whole file, and one such
    call would otherwise outweigh a hundred real messages in the index.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        flat = value
    else:
        try:
            flat = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            flat = str(value)
    flat = " ".join(flat.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def count_records(paths: Iterable[Path]) -> int:
    """Total indexable records across transcripts. Used by ``doctor``."""
    return sum(1 for path in paths for _ in read_transcript(path))
