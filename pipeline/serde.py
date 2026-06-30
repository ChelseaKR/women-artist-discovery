"""(De)serialisation of domain models to/from plain JSON-able dicts.

Used by the cache and by fixtures. Enums round-trip via their ``.value``; the
model invariants re-run on the way back in, so a corrupted cache row that would
violate a guardrail (e.g. a sourceless non-unknown gender) raises on load rather
than silently producing an unsourced label.
"""

from __future__ import annotations

from typing import Any, Optional

from pipeline.models import (
    Artist,
    BandComposition,
    FrontPerson,
    Gender,
    IdentityBasis,
    IdentityLabel,
    Source,
    SourceKind,
)


def source_to_dict(s: Source) -> dict[str, Any]:
    return {
        "kind": s.kind.value,
        "citation": s.citation,
        "retrieved_at": s.retrieved_at,
        "detail": s.detail,
    }


def source_from_dict(d: dict[str, Any]) -> Source:
    return Source(
        kind=SourceKind(d["kind"]),
        citation=d["citation"],
        retrieved_at=d["retrieved_at"],
        detail=d.get("detail", ""),
    )


def identity_to_dict(label: IdentityLabel) -> dict[str, Any]:
    return {
        "gender": label.gender.value,
        "basis": label.basis.value,
        "sources": [source_to_dict(s) for s in label.sources],
        "confidence": label.confidence,
    }


def identity_from_dict(d: dict[str, Any]) -> IdentityLabel:
    return IdentityLabel(
        gender=Gender(d["gender"]),
        basis=IdentityBasis(d["basis"]),
        sources=tuple(source_from_dict(s) for s in d.get("sources", [])),
        confidence=d.get("confidence"),
    )


def composition_to_dict(comp: BandComposition) -> dict[str, Any]:
    return {
        "members_fronting": [
            {"name": p.name, "role": p.role, "identity": identity_to_dict(p.identity)}
            for p in comp.members_fronting
        ],
        "sources": [source_to_dict(s) for s in comp.sources],
    }


def composition_from_dict(d: dict[str, Any]) -> BandComposition:
    return BandComposition(
        members_fronting=tuple(
            FrontPerson(
                name=p["name"],
                role=p["role"],
                identity=identity_from_dict(p["identity"]),
            )
            for p in d.get("members_fronting", [])
        ),
        sources=tuple(source_from_dict(s) for s in d.get("sources", [])),
    )


def artist_to_dict(a: Artist) -> dict[str, Any]:
    return {
        "artist_id": a.artist_id,
        "name": a.name,
        "tags": list(a.tags),
        "identity": identity_to_dict(a.identity),
        "composition": composition_to_dict(a.composition) if a.composition else None,
        "listeners": a.listeners,
        "playcount": a.playcount,
    }


def artist_from_dict(d: dict[str, Any]) -> Artist:
    comp: Optional[BandComposition] = (
        composition_from_dict(d["composition"]) if d.get("composition") else None
    )
    return Artist(
        artist_id=d["artist_id"],
        name=d["name"],
        tags=tuple(d.get("tags", [])),
        identity=identity_from_dict(d["identity"]) if d.get("identity") else IdentityLabel(),
        composition=comp,
        listeners=d.get("listeners", 0),
        playcount=d.get("playcount", 0),
    )
