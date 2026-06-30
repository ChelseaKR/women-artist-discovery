"""Shared fixtures — the offline demo world and a few hand-built artists."""

from __future__ import annotations

import pytest
from pipeline.demo import (
    DEMO_USER,
    demo_catalog,
    demo_enricher,
    demo_profile,
    demo_scrobbles,
    demo_source,
)
from pipeline.identity import IdentityEvidence, resolve_identity
from pipeline.models import (
    Artist,
    Gender,
    IdentityBasis,
    IdentityLabel,
    Source,
    SourceKind,
)


@pytest.fixture
def source():
    return demo_source()


@pytest.fixture
def enricher():
    return demo_enricher()


@pytest.fixture
def profile():
    return demo_profile()


@pytest.fixture
def catalog():
    return demo_catalog()


@pytest.fixture
def scrobbles():
    return demo_scrobbles()


@pytest.fixture
def demo_user():
    return DEMO_USER


@pytest.fixture
def woman_label() -> IdentityLabel:
    return resolve_identity(
        [
            IdentityEvidence(
                kind=SourceKind.WIKIDATA_P21,
                value="Q6581072",
                citation="https://www.wikidata.org/wiki/Q1",
                retrieved_at="2026-05-31",
            )
        ]
    )


@pytest.fixture
def nonbinary_label() -> IdentityLabel:
    return resolve_identity(
        [
            IdentityEvidence(
                kind=SourceKind.ARTIST_STATEMENT,
                value="nonbinary",
                citation="https://example.org/statement",
                retrieved_at="2026-05-31",
            )
        ]
    )


def make_artist(artist_id: str, gender: Gender = Gender.UNKNOWN, **kw) -> Artist:
    """Helper to build a sourced artist for re-rank/explanation tests."""
    if gender is Gender.UNKNOWN:
        identity = IdentityLabel()
    else:
        identity = IdentityLabel(
            gender=gender,
            basis=IdentityBasis.SELF_IDENTIFIED,
            sources=(
                Source(
                    kind=SourceKind.ARTIST_STATEMENT,
                    citation="https://example.org/x",
                    retrieved_at="2026-05-31",
                    detail=gender.value,
                ),
            ),
            confidence=0.9,
        )
    return Artist(artist_id=artist_id, name=artist_id.title(), identity=identity, **kw)
