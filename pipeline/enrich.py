"""Enrichment adapters: turn external metadata into *permitted-source evidence*.

Each parser validates the untrusted external payload before trusting it (security
posture: cache-poisoning resistance — RESPONSIBLE-TECH-AUDITS §F) and emits
:class:`~pipeline.identity.IdentityEvidence`, which the resolver alone turns into
labels. Parsers are pure and unit-tested from fixtures; live fetches are thin
wrappers excluded from coverage.

Provenance is preserved end to end: every emitted evidence carries the source
kind, a citation, and the fetch date.
"""

from __future__ import annotations

from typing import Optional, Protocol

from pipeline.identity import IdentityEvidence, resolve_identity
from pipeline.models import FrontPerson, SourceKind

# MusicBrainz gender field — the only values we accept; anything else is ignored
# (treated as unknown) rather than coerced.
_MB_GENDER_ALLOWED = {"male", "female", "other", "non-binary"}


class EnrichmentSource(Protocol):
    """Yields permitted-source evidence for an artist."""

    def gender_evidence(self, artist_id: str) -> list[IdentityEvidence]: ...

    def composition_evidence(
        self, artist_id: str
    ) -> tuple[list[FrontPerson], list[IdentityEvidence]]: ...


def parse_musicbrainz_gender(
    payload: object, citation: str, retrieved_at: str
) -> Optional[IdentityEvidence]:
    """Parse a MusicBrainz artist object's ``gender`` field, with validation."""
    if not isinstance(payload, dict):
        raise ValueError("musicbrainz payload must be an object")
    gender = payload.get("gender")
    if not isinstance(gender, str):
        return None
    value = gender.strip().lower()
    if value not in _MB_GENDER_ALLOWED:
        return None  # unrecognised → unknown, never guessed
    return IdentityEvidence(
        kind=SourceKind.MUSICBRAINZ_GENDER,
        value=value,
        citation=citation,
        retrieved_at=retrieved_at,
    )


def parse_wikidata_p21(
    payload: object, citation: str, retrieved_at: str
) -> Optional[IdentityEvidence]:
    """Parse a Wikidata entity's P21 ('sex or gender') claim into a QID evidence."""
    if not isinstance(payload, dict):
        raise ValueError("wikidata payload must be an object")
    claims = payload.get("claims", {})
    if not isinstance(claims, dict):
        return None
    p21 = claims.get("P21", [])
    if not isinstance(p21, list) or not p21:
        return None
    try:
        qid = p21[0]["mainsnak"]["datavalue"]["value"]["id"]
    except (KeyError, TypeError, IndexError):
        return None
    if not isinstance(qid, str) or not qid.startswith("Q"):
        return None
    return IdentityEvidence(
        kind=SourceKind.WIKIDATA_P21,
        value=qid,
        citation=citation,
        retrieved_at=retrieved_at,
    )


def parse_discogs_lineup(
    payload: object, citation: str, retrieved_at: str
) -> tuple[list[FrontPerson], list[IdentityEvidence]]:
    """Parse a Discogs lineup into sourced front-people + composition evidence.

    Each band member can carry their *own* sourced gender evidence (e.g. a member
    who has a self-statement); a member without it stays unknown. Returns the
    front-people plus one band-composition evidence row attesting the lineup.
    """
    if not isinstance(payload, dict):
        raise ValueError("discogs payload must be an object")
    members = payload.get("members", [])
    if not isinstance(members, list):
        return [], []
    fronts: list[FrontPerson] = []
    for m in members:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "")).strip().lower()
        # "Fronting" = lead vocals / frontperson, per the source's stated role.
        if not any(k in role for k in ("vocal", "front", "lead singer")):
            continue
        member_evidence: list[IdentityEvidence] = []
        statement = m.get("identity_statement")
        if isinstance(statement, dict) and statement.get("value"):
            member_evidence.append(
                IdentityEvidence(
                    kind=SourceKind.ARTIST_STATEMENT,
                    value=str(statement["value"]).strip().lower(),
                    citation=str(statement.get("citation", citation)),
                    retrieved_at=retrieved_at,
                )
            )
        fronts.append(
            FrontPerson(
                name=str(m.get("name", "")).strip(),
                role=role or "vocals",
                identity=resolve_identity(member_evidence),
            )
        )
    composition_evidence = (
        [
            IdentityEvidence(
                kind=SourceKind.DISCOGS_LINEUP,
                value="lineup",
                citation=citation,
                retrieved_at=retrieved_at,
            )
        ]
        if fronts
        else []
    )
    return fronts, composition_evidence


class FixtureEnricher:
    """Offline enrichment backed by pre-parsed evidence dicts."""

    def __init__(
        self,
        gender: dict[str, list[IdentityEvidence]],
        composition: dict[str, tuple[list[FrontPerson], list[IdentityEvidence]]],
    ) -> None:
        self._gender = gender
        self._composition = composition

    def gender_evidence(self, artist_id: str) -> list[IdentityEvidence]:
        return list(self._gender.get(artist_id, []))

    def composition_evidence(
        self, artist_id: str
    ) -> tuple[list[FrontPerson], list[IdentityEvidence]]:
        return self._composition.get(artist_id, ([], []))
