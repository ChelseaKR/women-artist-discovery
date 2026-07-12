"""Property-based guardrail tests (FIX-11).

Where the other guardrail tests (``test_no_inference.py``,
``test_unknown_first_class.py``, ``test_cache_serde.py`` etc.) pin down the
invariants on hand-picked examples, this module uses Hypothesis to throw many
generated inputs at the same invariants, so the guarantees hold *for all*
inputs the strategies can produce, not just the ones a test author thought of:

1. :func:`~pipeline.identity.resolve_identity` never returns a non-``unknown``
   label without at least one source, and is deterministic.
2. :func:`~recommender.rerank.rerank` never lowers a score and never drops or
   duplicates a recommendation (boost-only, permutation-only).
3. :func:`~pipeline.serde.artist_to_dict` / ``artist_from_dict`` round-trip.
4. Arbitrary corruption of a valid artist dict either round-trips to a valid
   ``Artist`` or raises :class:`~pipeline.models.IdentityError` — it never
   silently yields a non-``unknown`` identity with no sources.
5. :func:`~recommender.rerank.sort_and_rank` is deterministic regardless of
   input order, and assigns dense 1-based ranks.

``max_examples=100`` with ``deadline=None`` keeps this within the "seconds,
not minutes" budget the project's test suite targets (see Makefile ``test``).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pipeline.identity import (
    _FREEFORM_VOCAB,
    _WIKIDATA_QID_VOCAB,
    IdentityEvidence,
    resolve_identity,
)
from pipeline.models import (
    INDIVIDUAL_IDENTITY_SOURCES,
    UNKNOWN_IDENTITY,
    Artist,
    Explanation,
    Gender,
    IdentityBasis,
    IdentityError,
    IdentityLabel,
    Recommendation,
    Signal,
    Source,
    SourceKind,
)
from pipeline.serde import artist_from_dict, artist_to_dict
from recommender.rerank import rerank, sort_and_rank

_SETTINGS = settings(max_examples=100, deadline=None)

# --- Primitive strategies ----------------------------------------------------

_IDS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=16)
_NAMES = st.text(min_size=1, max_size=20)
_TAGS = st.lists(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8), max_size=4)
_CITATIONS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/:.", min_size=1, max_size=24)
_DATES = st.sampled_from(["2020-01-01", "2023-06-15", "2026-05-31", "1999-12-31"])
_COUNTS = st.integers(min_value=0, max_value=10_000_000)
_SCORES = st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False)
_CONFIDENCES = st.one_of(
    st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
)

_ALL_SOURCE_KINDS = st.sampled_from(list(SourceKind))
_INDIVIDUAL_SOURCE_KINDS = st.sampled_from(
    sorted(INDIVIDUAL_IDENTITY_SOURCES, key=lambda k: k.value)
)
_KNOWN_FREEFORM_VALUES = st.sampled_from(sorted(_FREEFORM_VOCAB.keys()))
_KNOWN_QID_VALUES = st.sampled_from(sorted(_WIKIDATA_QID_VOCAB.keys()))
_ARBITRARY_VALUES = st.text(min_size=0, max_size=12)
_NONUNKNOWN_GENDERS = [Gender.WOMAN, Gender.MAN, Gender.NONBINARY, Gender.OTHER]


def _evidence_value_strategy(kind: SourceKind) -> st.SearchStrategy[str]:
    """Draw both known-vocab values (exercise mapping) and arbitrary text
    (exercise the ``UNKNOWN``-on-unmappable-value path)."""
    if kind is SourceKind.WIKIDATA_P21:
        return st.one_of(_KNOWN_QID_VALUES, _ARBITRARY_VALUES)
    if kind in INDIVIDUAL_IDENTITY_SOURCES:
        return st.one_of(_KNOWN_FREEFORM_VALUES, _ARBITRARY_VALUES)
    return _ARBITRARY_VALUES


@st.composite
def identity_evidence(draw: st.DrawFn) -> IdentityEvidence:
    kind = draw(_ALL_SOURCE_KINDS)
    value = draw(_evidence_value_strategy(kind))
    return IdentityEvidence(
        kind=kind, value=value, citation=draw(_CITATIONS), retrieved_at=draw(_DATES)
    )


evidence_lists = st.lists(identity_evidence(), max_size=6)


@st.composite
def sourced_identity_labels(draw: st.DrawFn) -> IdentityLabel:
    """A valid, non-``unknown`` sourced identity — never an inference."""
    gender = draw(st.sampled_from(_NONUNKNOWN_GENDERS))
    kind = draw(_INDIVIDUAL_SOURCE_KINDS)
    n_sources = draw(st.integers(min_value=1, max_value=3))
    sources = tuple(
        Source(
            kind=kind,
            citation=draw(_CITATIONS),
            retrieved_at=draw(_DATES),
            detail=gender.value,
        )
        for _ in range(n_sources)
    )
    return IdentityLabel(
        gender=gender,
        basis=IdentityBasis.SELF_IDENTIFIED,
        sources=sources,
        confidence=draw(_CONFIDENCES),
    )


identity_labels = st.one_of(st.just(UNKNOWN_IDENTITY), sourced_identity_labels())


@st.composite
def artists(draw: st.DrawFn) -> Artist:
    """Reuses the shape of ``tests/conftest.py::make_artist``: a sourced-or-
    unknown identity, no band composition (kept out of scope to keep the
    strategy focused on the identity/serde invariants under test)."""
    return Artist(
        artist_id=draw(_IDS),
        name=draw(_NAMES),
        tags=tuple(draw(_TAGS)),
        identity=draw(identity_labels),
        composition=None,
        listeners=draw(_COUNTS),
        playcount=draw(_COUNTS),
    )


@st.composite
def recommendations(draw: st.DrawFn) -> Recommendation:
    artist = draw(artists())
    explanation = Explanation(
        signals=(Signal("content", "d", 1.0),),
        identity_basis=artist.identity.basis,
        identity_sources=artist.identity.sources,
        summary="why",
    )
    return Recommendation(
        artist=artist, base_score=draw(_SCORES), rerank_delta=0.0, explanation=explanation
    )


rec_lists = st.lists(recommendations(), max_size=8)
rec_lists_unique_ids = st.lists(
    recommendations(), max_size=8, unique_by=lambda r: r.artist.artist_id
)


def _identity_dict_corruptions(artist_dict: dict[str, Any], kind: str) -> None:
    """Mutate ``artist_dict["identity"]`` in place to a chosen corruption."""
    identity = artist_dict["identity"]
    if kind == "none":
        return
    if kind == "drop_sources":
        identity.pop("sources", None)
    elif kind == "empty_sources":
        identity["sources"] = []
    elif kind == "force_gender":
        identity["gender"] = Gender.WOMAN.value
    elif kind == "force_unknown_gender":
        identity["gender"] = Gender.UNKNOWN.value
    elif kind == "force_basis_unknown":
        identity["basis"] = IdentityBasis.UNKNOWN.value


@st.composite
def maybe_corrupted_artist_dicts(draw: st.DrawFn) -> dict[str, Any]:
    d = artist_to_dict(draw(artists()))
    corruption = draw(
        st.sampled_from(
            [
                "none",
                "drop_sources",
                "empty_sources",
                "force_gender",
                "force_unknown_gender",
                "force_basis_unknown",
            ]
        )
    )
    _identity_dict_corruptions(d, corruption)
    return d


# --- Property 1: resolve_identity is never unsourced-non-unknown, and is
#     deterministic. ----------------------------------------------------------


@_SETTINGS
@given(evidence_lists)
def test_resolve_identity_never_unsourced_and_is_deterministic(
    evidence: list[IdentityEvidence],
) -> None:
    result = resolve_identity(evidence)
    if result.gender is Gender.UNKNOWN:
        assert result.sources == ()
    else:
        assert len(result.sources) >= 1
        assert result.basis is IdentityBasis.SELF_IDENTIFIED

    # Determinism: the same evidence resolves to an equal label every time.
    assert resolve_identity(evidence) == result


# --- Property 2: rerank is boost-only and a true permutation. ----------------


@_SETTINGS
@given(rec_lists, st.floats(min_value=0.0, max_value=1.0))
def test_rerank_never_lowers_score_and_is_a_permutation(
    recs: list[Recommendation], lens_strength: float
) -> None:
    out = rerank(recs, lens_strength)

    assert len(out) == len(recs)
    # Boost-only: every delta is non-negative, so score can only rise (or stay).
    for rec in out:
        assert rec.rerank_delta >= 0.0
        assert rec.score >= rec.base_score

    # Permutation: same (artist_id, base_score) multiset in and out — nothing
    # dropped, duplicated, or silently rewritten beyond the delta.
    fingerprint = lambda r: (r.artist.artist_id, r.base_score)  # noqa: E731
    assert Counter(map(fingerprint, out)) == Counter(map(fingerprint, recs))


_OUT_OF_RANGE_LENS_STRENGTHS = st.one_of(
    st.floats(min_value=-10, max_value=-0.0001),
    st.floats(min_value=1.0001, max_value=10),
)


@_SETTINGS
@given(rec_lists, _OUT_OF_RANGE_LENS_STRENGTHS)
def test_rerank_rejects_out_of_range_lens_strength(
    recs: list[Recommendation], bad_strength: float
) -> None:
    with pytest.raises(ValueError):
        rerank(recs, bad_strength)


# --- Property 3: serde round-trips. ------------------------------------------


@_SETTINGS
@given(artists())
def test_artist_serde_round_trips(artist: Artist) -> None:
    assert artist_from_dict(artist_to_dict(artist)) == artist


# --- Property 4: corrupt-dict loading either round-trips cleanly or raises
#     IdentityError — never a silent unsourced non-unknown label. ------------


@_SETTINGS
@given(maybe_corrupted_artist_dicts())
def test_corrupt_dict_never_yields_unsourced_nonunknown_identity(d: dict[str, Any]) -> None:
    try:
        artist = artist_from_dict(d)
    except IdentityError:
        return  # the guardrail rejected the corrupt row — acceptable outcome

    if artist.identity.gender is Gender.UNKNOWN:
        assert artist.identity.sources == ()
    else:
        assert len(artist.identity.sources) >= 1
        assert artist.identity.basis is IdentityBasis.SELF_IDENTIFIED


# --- Property 5: sort_and_rank is deterministic and rank-dense. -------------


@_SETTINGS
@given(rec_lists_unique_ids, st.randoms())
def test_sort_and_rank_is_order_independent_and_dense(recs: list[Recommendation], rnd: Any) -> None:
    shuffled = list(recs)
    rnd.shuffle(shuffled)

    out_a = sort_and_rank(list(recs))
    out_b = sort_and_rank(shuffled)

    signature = lambda out: [(r.artist.artist_id, r.rank) for r in out]  # noqa: E731
    assert signature(out_a) == signature(out_b)
    assert [r.rank for r in out_a] == list(range(1, len(out_a) + 1))
