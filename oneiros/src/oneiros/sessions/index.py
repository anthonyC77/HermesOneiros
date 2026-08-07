"""The session index: SQLite FTS5 over harness transcripts.

Incremental by ``(size, mtime)``. The alternative — hashing every file on every
run — is correct and unusably slow once a machine has a few thousand
transcripts, and the failure mode of the cheap check (a file rewritten to the
same size within filesystem timestamp granularity) does not occur with
append-only logs.

Re-indexing a changed file deletes its rows and reinserts them rather than
diffing. Transcripts are append-only in practice but not by contract, and
delete-then-insert is correct under both assumptions.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config as cfg
from .query import build_match
from .reader import iter_transcripts, read_transcript

__all__ = ["Index", "IndexStats", "Hit", "Fts5Unavailable"]


class Fts5Unavailable(RuntimeError):
    """This interpreter's SQLite was built without FTS5.

    Rare but real on minimal or self-compiled Python builds. Detected at open
    time so ``doctor`` can say so plainly, rather than at first search where it
    looks like a query bug.
    """


@dataclass(frozen=True)
class Hit:
    session_id: str
    project: str
    role: str
    text: str
    timestamp: str
    path: str
    snippet: str


@dataclass(frozen=True)
class IndexStats:
    files: int
    messages: int
    sessions: int
    projects: int
    last_indexed_at: float | None

    def describe(self) -> str:
        return (
            f"{self.messages:,} messages · {self.sessions:,} sessions · "
            f"{self.projects:,} projects · {self.files:,} transcripts"
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path        TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    mtime       REAL    NOT NULL,
    indexed_at  REAL    NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5 (
    text,
    session_id  UNINDEXED,
    project     UNINDEXED,
    role        UNINDEXED,
    uuid        UNINDEXED,
    ts          UNINDEXED,
    path        UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


class Index:
    """Full-text index over past sessions."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (cfg.state_dir() / "sessions.db")
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(_SCHEMA)
        except sqlite3.OperationalError as exc:
            conn.close()
            if "fts5" in str(exc).lower():
                raise Fts5Unavailable(
                    "this Python's SQLite has no FTS5 support, so session search "
                    "cannot run. Install a Python built with FTS5 enabled."
                ) from exc
            raise
        conn.commit()
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Index":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- indexing -----------------------------------------------------------

    def refresh(self, root: Path | None = None) -> tuple[int, int]:
        """Index new and changed transcripts. Returns (files seen, files reindexed)."""
        conn = self.connect()
        root = root or cfg.transcripts_dir()

        known = {
            row["path"]: (row["size"], row["mtime"])
            for row in conn.execute("SELECT path, size, mtime FROM files")
        }

        seen = 0
        touched = 0
        for path in iter_transcripts(root):
            seen += 1
            try:
                stat = path.stat()
            except OSError:
                continue
            key = str(path)
            if known.get(key) == (stat.st_size, stat.st_mtime):
                continue
            self._reindex(conn, path, stat.st_size, stat.st_mtime)
            touched += 1

        conn.commit()
        return seen, touched

    def _reindex(self, conn: sqlite3.Connection, path: Path, size: int, mtime: float) -> None:
        key = str(path)
        conn.execute("DELETE FROM messages WHERE path = ?", (key,))
        rows = [
            (r.text, r.session_id, r.project, r.role, r.uuid, r.timestamp, r.path)
            for r in read_transcript(path)
        ]
        if rows:
            conn.executemany(
                "INSERT INTO messages (text, session_id, project, role, uuid, ts, path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        conn.execute(
            "INSERT INTO files (path, size, mtime, indexed_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, "
            "indexed_at=excluded.indexed_at",
            (key, size, mtime, time.time()),
        )

    # -- querying -----------------------------------------------------------

    def search(self, query: str, limit: int = 20, project: str | None = None) -> list[Hit]:
        """Search the index. An unusable query returns no results, never raises."""
        match = build_match(query)
        if match is None:
            return []

        sql = (
            "SELECT text, session_id, project, role, ts, path, "
            "       snippet(messages, 0, '«', '»', '…', 16) AS snip "
            "FROM messages WHERE messages MATCH ?"
        )
        params: list[object] = [match]
        if project:
            sql += " AND project = ?"
            params.append(project)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        conn = self.connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # build_match should make this unreachable. If it ever is reached,
            # an empty result is a better outcome than a stack trace in a hook.
            return []

        return [
            Hit(
                session_id=row["session_id"],
                project=row["project"],
                role=row["role"],
                text=row["text"],
                timestamp=row["ts"],
                path=row["path"],
                snippet=row["snip"],
            )
            for row in rows
        ]

    def recent(self, limit: int = 10) -> list[Hit]:
        conn = self.connect()
        rows = conn.execute(
            "SELECT text, session_id, project, role, ts, path FROM messages "
            "WHERE ts != '' ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Hit(
                session_id=row["session_id"],
                project=row["project"],
                role=row["role"],
                text=row["text"],
                timestamp=row["ts"],
                path=row["path"],
                snippet=row["text"][:160],
            )
            for row in rows
        ]

    def stats(self) -> IndexStats:
        conn = self.connect()
        files = conn.execute("SELECT COUNT(*) AS n, MAX(indexed_at) AS t FROM files").fetchone()
        agg = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT session_id) AS s, "
            "COUNT(DISTINCT project) AS p FROM messages"
        ).fetchone()
        return IndexStats(
            files=files["n"] or 0,
            messages=agg["n"] or 0,
            sessions=agg["s"] or 0,
            projects=agg["p"] or 0,
            last_indexed_at=files["t"],
        )
