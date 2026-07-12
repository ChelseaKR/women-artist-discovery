"""A local pending-corrections list — the other half of "fix it at the source".

EXP-05's round-trip is: a provenance item is wrong or stale -> the reader
opens the pre-filled upstream edit link (:mod:`recommender.upstream`) ->
they file a *local* note of what they proposed here -> they make the real
edit on Wikidata/MusicBrainz themselves -> the next ``wad refresh`` re-fetches
and reports the change (:class:`~pipeline.ingest.IdentityLabelChange`) ->
:func:`reconcile` clears the matching pending row.

This module never talks to a network. It is a small JSON file next to the
local cache (Quality §9's data-lineage discipline extended to corrections:
every row records what was filed, when, and against which citation).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from pipeline.cache import DEFAULT_DB_PATH
from pipeline.ingest import IdentityLabelChange

#: Conventional location: alongside the cache db, e.g. ``data/pending-corrections.json``.
DEFAULT_CORRECTIONS_PATH: Path = DEFAULT_DB_PATH.parent / "pending-corrections.json"


@dataclass(frozen=True)
class PendingCorrection:
    """One filed-but-not-yet-reconciled correction request.

    Filing this never edits anything — it is a local note of *what a person
    believes is right and why*, made the moment they open the upstream edit
    link. The actual edit happens in the upstream UI, by that person, in
    their own browser. ``edit_url`` records which link was offered so the
    round-trip is auditable end to end.
    """

    artist_id: str
    source_kind: str
    citation: str
    current_value: str
    proposed_value: str
    note: str
    filed_at: str
    edit_url: Optional[str] = None


def default_path(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    """The conventional corrections-file location alongside a given cache db."""
    return Path(db_path).parent / "pending-corrections.json"


def _read_all(path: str | Path) -> list[PendingCorrection]:
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [PendingCorrection(**row) for row in raw]


def _write_all(path: str | Path, corrections: Sequence[PendingCorrection]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps([asdict(c) for c in corrections], indent=2) + "\n",
        encoding="utf-8",
    )


def add_correction(
    path: str | Path,
    *,
    artist_id: str,
    source_kind: str,
    citation: str,
    current_value: str,
    proposed_value: str,
    note: str,
    filed_at: str,
    edit_url: Optional[str] = None,
) -> PendingCorrection:
    """File and persist a new pending correction. Returns the stored row."""
    corrections = _read_all(path)
    row = PendingCorrection(
        artist_id=artist_id,
        source_kind=source_kind,
        citation=citation,
        current_value=current_value,
        proposed_value=proposed_value,
        note=note,
        filed_at=filed_at,
        edit_url=edit_url,
    )
    corrections.append(row)
    _write_all(path, corrections)
    return row


def list_corrections(path: str | Path) -> list[PendingCorrection]:
    """Return every pending correction currently on file (empty if none)."""
    return _read_all(path)


def reconcile(path: str | Path, changes: Iterable[IdentityLabelChange]) -> int:
    """Clear pending corrections whose upstream value has since moved.

    A pending correction is reconciled (dropped from the file) when a change
    in ``changes`` — normally the list a ``wad refresh`` pass just produced —
    shares its ``(artist_id, source_kind)``: that is the observable evidence
    the upstream edit landed and a fresh ``retrieved_at`` now reflects it.
    Rows that don't match are left untouched. Returns the number reconciled.
    """
    pending = _read_all(path)
    if not pending:
        return 0
    changed_keys = {(c.artist_id, c.source_kind) for c in changes}
    if not changed_keys:
        return 0
    kept = [c for c in pending if (c.artist_id, c.source_kind) not in changed_keys]
    reconciled = len(pending) - len(kept)
    if reconciled:
        _write_all(path, kept)
    return reconciled
