"""Local pending-corrections store (EXP-05): the local half of the round-trip.

local note -> upstream edit (human, out of band) -> `wad refresh` sees a new
`retrieved_at` -> `reconcile()` drops the now-stale pending row.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import corrections
from pipeline.ingest import IdentityLabelChange


def test_add_correction_persists_and_list_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "pending-corrections.json"
    row = corrections.add_correction(
        path,
        artist_id="mitski",
        source_kind="wikidata-p21",
        citation="https://www.wikidata.org/wiki/Q16735549",
        current_value="Q6581072",
        proposed_value="Q6581072",
        note="Wikidata P21 is stale; artist has since clarified pronouns publicly.",
        filed_at="2026-07-01",
        edit_url="https://www.wikidata.org/wiki/Q16735549#P21",
    )
    assert row.artist_id == "mitski"

    rows = corrections.list_corrections(path)
    assert len(rows) == 1
    assert rows[0] == row


def test_list_corrections_on_missing_file_is_empty(tmp_path: Path) -> None:
    assert corrections.list_corrections(tmp_path / "nope.json") == []


def test_add_correction_appends_not_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "pending-corrections.json"
    corrections.add_correction(
        path,
        artist_id="a",
        source_kind="wikidata-p21",
        citation="https://www.wikidata.org/wiki/Q1",
        current_value="x",
        proposed_value="y",
        note="",
        filed_at="2026-07-01",
    )
    corrections.add_correction(
        path,
        artist_id="b",
        source_kind="musicbrainz-gender",
        citation="https://musicbrainz.org/artist/b",
        current_value="x",
        proposed_value="y",
        note="",
        filed_at="2026-07-01",
    )
    rows = corrections.list_corrections(path)
    assert {r.artist_id for r in rows} == {"a", "b"}


def test_reconcile_drops_matching_row_and_keeps_others(tmp_path: Path) -> None:
    path = tmp_path / "pending-corrections.json"
    corrections.add_correction(
        path,
        artist_id="mitski",
        source_kind="wikidata-p21",
        citation="https://www.wikidata.org/wiki/Q16735549",
        current_value="Q6581072",
        proposed_value="Q6581072",
        note="stale retrieval date",
        filed_at="2026-07-01",
    )
    corrections.add_correction(
        path,
        artist_id="snail-mail",
        source_kind="musicbrainz-gender",
        citation="https://musicbrainz.org/artist/snail",
        current_value="female",
        proposed_value="female",
        note="unrelated pending row",
        filed_at="2026-07-01",
    )

    changes = [
        IdentityLabelChange(
            artist_id="mitski",
            source_kind="wikidata-p21",
            old_value="Q6581072",
            new_value="Q6581072",
            retrieved_at="2026-07-02",
        )
    ]
    reconciled = corrections.reconcile(path, changes)
    assert reconciled == 1

    remaining = corrections.list_corrections(path)
    assert [r.artist_id for r in remaining] == ["snail-mail"]


def test_reconcile_with_no_matching_changes_leaves_all_rows(tmp_path: Path) -> None:
    path = tmp_path / "pending-corrections.json"
    corrections.add_correction(
        path,
        artist_id="mitski",
        source_kind="wikidata-p21",
        citation="https://www.wikidata.org/wiki/Q16735549",
        current_value="Q6581072",
        proposed_value="Q6581072",
        note="",
        filed_at="2026-07-01",
    )
    changes = [
        IdentityLabelChange(
            artist_id="someone-else",
            source_kind="wikidata-p21",
            old_value="a",
            new_value="b",
            retrieved_at="2026-07-02",
        )
    ]
    assert corrections.reconcile(path, changes) == 0
    assert len(corrections.list_corrections(path)) == 1


def test_reconcile_on_empty_pending_list_is_a_noop(tmp_path: Path) -> None:
    path = tmp_path / "pending-corrections.json"
    assert corrections.reconcile(path, []) == 0


def test_reconcile_with_no_changes_at_all_is_a_noop(tmp_path: Path) -> None:
    path = tmp_path / "pending-corrections.json"
    corrections.add_correction(
        path,
        artist_id="mitski",
        source_kind="wikidata-p21",
        citation="https://www.wikidata.org/wiki/Q16735549",
        current_value="Q6581072",
        proposed_value="Q6581072",
        note="",
        filed_at="2026-07-01",
    )
    assert corrections.reconcile(path, []) == 0
    assert len(corrections.list_corrections(path)) == 1


def test_default_path_sits_alongside_the_given_db() -> None:
    assert corrections.default_path("data/cache.db") == Path("data/pending-corrections.json")
