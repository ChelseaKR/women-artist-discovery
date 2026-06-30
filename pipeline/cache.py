"""Local-first SQLite cache with data-lineage timestamps.

Privacy posture (RESPONSIBLE-TECH-AUDITS §C): listening data and enriched
metadata live in a single on-disk SQLite file under ``data/`` and never leave the
machine. There is no telemetry and no third-party client here — only stdlib
``sqlite3``. Every cached row carries a ``fetched_at`` timestamp so each record is
traceable to a source + fetch time (Quality §9, data quality & lineage).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Optional

from pipeline.models import Artist, Scrobble
from pipeline.serde import artist_from_dict, artist_to_dict

DEFAULT_DB_PATH = Path("data") / "cache.db"

_SCHEMA = """
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


class Cache:
    """A thin, typed wrapper over a local SQLite database.

    Use as a context manager so the connection is always closed::

        with Cache(":memory:") as cache:
            cache.put_artist(artist, fetched_at="2026-05-31")
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        with closing(self.conn.cursor()) as cur:
            cur.executescript(_SCHEMA)
        self.conn.commit()

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
