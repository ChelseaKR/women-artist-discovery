"""Local-first SQLite cache with data-lineage timestamps and a managed schema.

Privacy posture (RESPONSIBLE-TECH-AUDITS §C): listening data and enriched
metadata live in a single on-disk SQLite file under ``data/`` and never leave the
machine. There is no telemetry and no third-party client here — only stdlib
``sqlite3``. Every cached row carries a ``fetched_at``/``ts`` timestamp so each
record is traceable to a source + fetch time (Quality §9, data quality &
lineage).

Schema versioning: ``PRAGMA user_version`` plus a tiny forward-only migration
runner (see :data:`_MIGRATIONS`). Opening an older cache migrates it in place;
opening one written by a newer version of this code raises
:class:`CacheSchemaError` rather than silently misreading it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from pathlib import Path
from typing import Optional

from recommender.feedback import Feedback

from pipeline.models import Artist, Scrobble
from pipeline.serde import artist_from_dict, artist_to_dict

DEFAULT_DB_PATH = Path("data") / "cache.db"

#: Current on-disk schema version. Bump when a migration is added below.
CACHE_SCHEMA_VERSION = 2

# Base tables (schema v1).
_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    artist_id  TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scrobbles (
    username    TEXT NOT NULL,
    artist_id   TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    track       TEXT NOT NULL,
    ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scrobbles_user ON scrobbles(username);
CREATE TABLE IF NOT EXISTS http_cache (
    url        TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

# v2 (M6 feedback loop): one row per (username, artist_id) thumbs vote, upserted
# on re-vote. ``ts`` is the vote's own lineage timestamp (unix seconds, matching
# Scrobble.ts); ``fetched_at`` is when this cache row was last written, kept for
# the same data-lineage reason every other cached row carries it.
_MIGRATE_V2 = """
CREATE TABLE IF NOT EXISTS feedback (
    username    TEXT NOT NULL,
    artist_id   TEXT NOT NULL,
    vote        INTEGER NOT NULL,
    ts          INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    UNIQUE(username, artist_id)
);
"""


class CacheSchemaError(RuntimeError):
    """Raised when a cache file's schema is newer than this code can safely read."""


def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(_BASE_SCHEMA)


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(_MIGRATE_V2)


#: Forward-only migrations keyed by the schema version they *produce*.
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_to_v1,
    2: _migrate_to_v2,
}


class Cache:
    """A thin, typed wrapper over a local SQLite database.

    Use as a context manager so the connection is always closed::

        with Cache(":memory:") as cache:
            cache.put_artist(artist, fetched_at="2026-05-31")

    Opening a cache runs any pending :data:`_MIGRATIONS`; a cache written by a
    newer version of the code raises :class:`CacheSchemaError` rather than
    misreading it.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._migrate()

    # -- schema lifecycle ------------------------------------------------------
    def _migrate(self) -> None:
        current = self.schema_version
        if current > CACHE_SCHEMA_VERSION:
            self.conn.close()
            raise CacheSchemaError(
                f"cache schema v{current} is newer than supported v{CACHE_SCHEMA_VERSION}; "
                "upgrade women-artist-discovery or start from a fresh cache"
            )
        with closing(self.conn.cursor()) as cur:
            for target in range(current + 1, CACHE_SCHEMA_VERSION + 1):
                _MIGRATIONS[target](self.conn)
            if current < CACHE_SCHEMA_VERSION:
                # PRAGMA cannot be parameterised; the value is a trusted int constant.
                cur.execute(f"PRAGMA user_version = {int(CACHE_SCHEMA_VERSION)}")
        self.conn.commit()

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    # -- lifecycle -----------------------------------------------------------
    def __enter__(self) -> Cache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # -- artists -------------------------------------------------------------
    def put_artist(self, artist: Artist, fetched_at: str) -> None:
        self.conn.execute(
            "INSERT INTO artists(artist_id, payload, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(artist_id) DO UPDATE SET payload=excluded.payload, "
            "fetched_at=excluded.fetched_at",
            (artist.artist_id, json.dumps(artist_to_dict(artist)), fetched_at),
        )
        self.conn.commit()

    def get_artist(self, artist_id: str) -> Optional[Artist]:
        row = self.conn.execute(
            "SELECT payload FROM artists WHERE artist_id = ?", (artist_id,)
        ).fetchone()
        if row is None:
            return None
        return artist_from_dict(json.loads(row["payload"]))

    def artist_fetched_at(self, artist_id: str) -> Optional[str]:
        """Return when an artist was last enriched — the lineage timestamp."""
        row = self.conn.execute(
            "SELECT fetched_at FROM artists WHERE artist_id = ?", (artist_id,)
        ).fetchone()
        return row["fetched_at"] if row else None

    # -- scrobbles -----------------------------------------------------------
    def put_scrobbles(self, username: str, scrobbles: Iterable[Scrobble]) -> None:
        self.conn.executemany(
            "INSERT INTO scrobbles(username, artist_id, artist_name, track, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            [(username, s.artist_id, s.artist_name, s.track, s.ts) for s in scrobbles],
        )
        self.conn.commit()

    def get_scrobbles(self, username: str) -> list[Scrobble]:
        rows = self.conn.execute(
            "SELECT artist_id, artist_name, track, ts FROM scrobbles "
            "WHERE username = ? ORDER BY ts",
            (username,),
        ).fetchall()
        return [
            Scrobble(
                artist_id=r["artist_id"],
                artist_name=r["artist_name"],
                track=r["track"],
                ts=r["ts"],
            )
            for r in rows
        ]

    # -- http response cache (rate-limit respect) ----------------------------
    def get_cached_response(self, url: str) -> Optional[str]:
        row = self.conn.execute("SELECT body FROM http_cache WHERE url = ?", (url,)).fetchone()
        return row["body"] if row else None

    def put_cached_response(self, url: str, body: str, fetched_at: str) -> None:
        self.conn.execute(
            "INSERT INTO http_cache(url, body, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET body=excluded.body, "
            "fetched_at=excluded.fetched_at",
            (url, body, fetched_at),
        )
        self.conn.commit()

    # -- feedback (M6 feedback loop) ------------------------------------------
    def record_feedback(self, feedback: Feedback, fetched_at: str) -> None:
        """Upsert one thumbs vote, keyed on ``(username, artist_id)``.

        A re-vote on the same artist replaces the prior vote rather than
        accumulating duplicate rows — one live opinion per user per artist.
        """
        self.conn.execute(
            "INSERT INTO feedback(username, artist_id, vote, ts, fetched_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(username, artist_id) DO UPDATE SET vote=excluded.vote, "
            "ts=excluded.ts, fetched_at=excluded.fetched_at",
            (feedback.username, feedback.artist_id, feedback.vote, feedback.ts, fetched_at),
        )
        self.conn.commit()

    def load_feedback(self, username: str) -> list[Feedback]:
        """All stored votes for a user, oldest first."""
        rows = self.conn.execute(
            "SELECT username, artist_id, vote, ts FROM feedback WHERE username = ? ORDER BY ts",
            (username,),
        ).fetchall()
        return [
            Feedback(
                username=r["username"],
                artist_id=r["artist_id"],
                vote=r["vote"],
                ts=r["ts"],
            )
            for r in rows
        ]
