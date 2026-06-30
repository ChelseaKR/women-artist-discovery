"""R4: the exposure / rank-fairness metric measures where each identity lands.

It is descriptive (it never sets a quota) and it must keep both invariants: the
``unknown`` segment is always reported, and the boost-only lens never drops or
penalises a segment — it can only *raise* aligned artists, which these tests
verify by comparing taste vs. values-lens exposure.
"""

from __future__ import annotations

import pytest
from pipeline.models import (
    Explanation,
    Gender,
    IdentityBasis,
    Recommendation,
    Signal,
)
from recommender.eval import evaluate, exposure_by_lens, to_report
from recommender.exposure import SEGMENTS, compute_exposure, segment_of

from .conftest import make_artist


def _ranked(segments_in_order: list[str]) -> list[Recommendation]:
    """Build a ranked rec list whose segments follow ``segments_in_order``."""
    gender_for = {
        "woman": Gender.WOMAN,
        "nonbinary": Gender.NONBINARY,
        "man": Gender.MAN,
        "other": Gender.OTHER,
        "unknown": Gender.UNKNOWN,
    }
    recs: list[Recommendation] = []
    for i, seg in enumerate(segments_in_order, start=1):
        artist = make_artist(f"a{i}", gender=gender_for[seg])
        basis = IdentityBasis.UNKNOWN if seg == "unknown" else IdentityBasis.SELF_IDENTIFIED
        expl = Explanation(
            signals=(Signal("content", "t", 1.0),),
            identity_basis=basis,
            identity_sources=artist.identity.sources,
            summary="why",
        )
        recs.append(
            Recommendation(
                artist=artist, base_score=1.0 - i * 0.01, rerank_delta=0.0, explanation=expl
            ).with_rank(i)
        )
    return recs


def test_segment_of_reads_sourced_labels(catalog) -> None:
    assert segment_of(make_artist("w", gender=Gender.WOMAN)) == "woman"
    assert segment_of(make_artist("nb", gender=Gender.NONBINARY)) == "nonbinary"
    assert segment_of(make_artist("m", gender=Gender.MAN)) == "man"
    assert segment_of(make_artist("o", gender=Gender.OTHER)) == "other"
    assert segment_of(make_artist("u")) == "unknown"
    # A sourced female-fronted band with an unknown individual gender.
    assert segment_of(catalog["big-thief"]) == "female-fronted"
    assert segment_of(catalog["mystery-act"]) == "unknown"


def test_compute_exposure_math() -> None:
    recs = _ranked(["woman", "man", "woman", "unknown", "man"])
    rep = compute_exposure(recs, k=3)
    assert rep.total == 5
    assert {s.segment for s in rep.segments} == set(SEGMENTS)  # all segments present
    woman = rep.by_segment("woman")
    assert woman.count == 2
    assert woman.share == pytest.approx(2 / 5)
    assert woman.first_rank == 1
    assert woman.mean_rank == pytest.approx((1 + 3) / 2)
    assert woman.top_k_share == pytest.approx(2 / 3)  # ranks 1 and 3 are in the top-3
    unknown = rep.by_segment("unknown")
    assert unknown.count == 1 and unknown.first_rank == 4


def test_absent_segments_are_reported_as_zero() -> None:
    rep = compute_exposure(_ranked(["woman", "woman"]), k=2)
    unknown = rep.by_segment("unknown")
    assert unknown.count == 0 and unknown.first_rank == 0 and unknown.mean_rank == 0.0
    assert unknown.top_k_share == 0.0


def test_compute_exposure_rejects_nonpositive_k() -> None:
    with pytest.raises(ValueError):
        compute_exposure(_ranked(["woman"]), k=0)


def test_by_segment_rejects_unknown_segment_name() -> None:
    rep = compute_exposure(_ranked(["woman"]), k=1)
    with pytest.raises(KeyError):
        rep.by_segment("not-a-segment")


def test_values_lens_lifts_women_and_nonbinary_without_dropping_unknown(
    demo_user, scrobbles, catalog, source
) -> None:
    reports = exposure_by_lens(demo_user, scrobbles, catalog, source, k=5)
    assert set(reports) == {"taste", "values_lens"}
    taste, lens = reports["taste"], reports["values_lens"]

    # Boost-only: aligned segments can only move *up* (rank decreases or holds).
    assert lens.by_segment("woman").mean_rank <= taste.by_segment("woman").mean_rank
    assert lens.by_segment("nonbinary").first_rank <= taste.by_segment("nonbinary").first_rank

    # Nobody is dropped: every segment keeps its count under the lens.
    for seg in SEGMENTS:
        assert lens.by_segment(seg).count == taste.by_segment(seg).count

    # Unknown is present and first-class in both rankings.
    assert taste.by_segment("unknown").count >= 1
    assert lens.by_segment("unknown").count == taste.by_segment("unknown").count


def test_to_report_embeds_exposure_when_supplied(demo_user, scrobbles, catalog, source) -> None:
    results = evaluate(demo_user, scrobbles, catalog, source, k=5)
    plain = to_report(results)
    assert "exposure" not in plain  # additive: absent by default, test_eval unaffected

    exposure = exposure_by_lens(demo_user, scrobbles, catalog, source, k=5)
    enriched = to_report(results, exposure)
    assert set(enriched["exposure"]) == {"taste", "values_lens"}
    woman_row = next(
        s for s in enriched["exposure"]["values_lens"]["segments"] if s["segment"] == "woman"
    )
    assert woman_row["count"] >= 1
