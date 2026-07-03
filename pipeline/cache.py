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

from pipeline.identity import IdentityEvidence
from pipeline.models import Artist, Scrobble, SourceKind, UnsourcedIdentityError
from pipeline.serde import artist_from_dict, artist_to_dict

DEFAULT_DB_PATH = Path("data") / "cache.db"

#: The schema this module knows how to produce. Bumped whenever a migration is
#: added; ``Cache.__init__`` applies every migration up to this version, so an
#: older on-disk cache is upgraded in place rather than requiring a wipe.
CACHE_SCHEMA_VERSION = 3

# The baseline schema (artists/scrobbles/http_cache) — everything this module
# shipped before schema-version tracking existed. Treated as "version 2" for
# migration-numbering purposes (FIX-10 is the first migration on top of it).
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

# v3 (FIX-10): the local corrections ledger. `citation` and `retrieved_at` are
# NOT NULL — an operator-entered override with no citation cannot be stored,
# mirroring `Source.__post_init__`'s "no citation, no override" invariant.
# Corrections live outside `http_cache`, so `wad refresh` (which only expires
# `http_cache`) never touches them — a correction persists until an operator
# removes it.
_MIGRATE_TO_V3 = """
CREATE TABLE IF NOT EXISTS corrections (
    artist_id      TEXT NOT NULL,
    asserted_value TEXT NOT NULL,
    citation       TEXT NOT NULL,
    retrieved_at   TEXT NOT NULL,
    entered_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_corrections_artist ON corrections(artist_id);
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
            self._migrate(cur)
        self.conn.commit()

    def _migrate(self, cur: sqlite3.Cursor) -> None:
        """Apply every migration between the on-disk version and current.

        Uses SQLite's built-in ``PRAGMA user_version`` as the version marker
        (no extra table needed). All migration DDL is idempotent
        (``CREATE TABLE IF NOT EXISTS``), so this is safe to run against a
        fresh ``:memory:`` cache, an untracked pre-versioning cache, or one
        already on the latest version.
        """
        version = cur.execute("PRAGMA user_version").fetchone()[0]
        if version < CACHE_SCHEMA_VERSION:
            self._migrate_to_v3(cur)
            cur.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION}")

    def _migrate_to_v3(self, cur: sqlite3.Cursor) -> None:
        """Add the local corrections ledger (FIX-10)."""
        cur.executescript(_MIGRATE_TO_V3)

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

    def expire_http_cache(self) -> int:
        """Clear the HTTP response cache (what ``wad refresh`` refreshes).

        Deliberately touches only ``http_cache`` — ``artists``, ``scrobbles``,
        and ``corrections`` are untouched, so a local correction (FIX-10)
        survives a refresh rather than being wiped alongside stale HTTP bodies.
        Returns the number of rows cleared.
        """
        cur = self.conn.execute("DELETE FROM http_cache")
        self.conn.commit()
        return cur.rowcount

    # -- local corrections ledger (FIX-10) ------------------------------------
    def put_correction(self, artist_id: str, evidence: IdentityEvidence, entered_at: str) -> None:
        """Record an operator-entered correction. Requires a citation.

        ``evidence`` is validated exactly like any other identity evidence —
        turning it into a :class:`~pipeline.models.Source` re-runs
        ``Source.__post_init__``, so an empty citation raises
        :class:`~pipeline.models.UnsourcedIdentityError` here too: "no
        citation, no override" is a single invariant, not one rule for live
        sources and a laxer one for corrections.
        """
        source = evidence.as_source()  # raises UnsourcedIdentityError if uncited
        if source.kind is not SourceKind.ARTIST_STATEMENT:
            raise UnsourcedIdentityError(
                "a correction must be recorded as an ARTIST_STATEMENT source"
            )
        self.conn.execute(
            "INSERT INTO corrections"
            "(artist_id, asserted_value, citation, retrieved_at, entered_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (artist_id, evidence.value, evidence.citation, evidence.retrieved_at, entered_at),
        )
        self.conn.commit()

    def get_corrections(self, artist_id: str) -> tuple[IdentityEvidence, ...]:
        """Corrections for one artist, as evidence ready to feed the resolver.

        Ordered by ``entered_at`` (then citation, for a deterministic tie
        break) so re-running resolution is reproducible.
        """
        rows = self.conn.execute(
            "SELECT asserted_value, citation, retrieved_at FROM corrections "
            "WHERE artist_id = ? ORDER BY entered_at, citation",
            (artist_id,),
        ).fetchall()
        return tuple(
            IdentityEvidence(
                kind=SourceKind.ARTIST_STATEMENT,
                value=r["asserted_value"],
                citation=r["citation"],
                retrieved_at=r["retrieved_at"],
                is_local_correction=True,
            )
            for r in rows
        )

    def list_corrections(self) -> tuple[tuple[str, IdentityEvidence, str], ...]:
        """Every correction in the ledger, as ``(artist_id, evidence, entered_at)``."""
        rows = self.conn.execute(
            "SELECT artist_id, asserted_value, citation, retrieved_at, entered_at "
            "FROM corrections ORDER BY entered_at, citation"
        ).fetchall()
        return tuple(
            (
                r["artist_id"],
                IdentityEvidence(
                    kind=SourceKind.ARTIST_STATEMENT,
                    value=r["asserted_value"],
                    citation=r["citation"],
                    retrieved_at=r["retrieved_at"],
                    is_local_correction=True,
                ),
                r["entered_at"],
            )
            for r in rows
        )
