"""Exposure / rank-fairness metric — *measure* where each identity lands.

Collaborative-filtering recommenders are documented to **amplify** the gender
gap: on data that is roughly a quarter women, the first recommended woman has
been found to land several ranks below the first man, and a feedback loop makes
it worse over time. The project's answer is a bounded, boost-only values lens —
but "fair by design" is only credible if it is also *reported as a number*.

This module computes, for a ranked run, per-identity-segment **exposure**:

* ``count`` / ``share`` — how many picks, and what fraction of the run;
* ``first_rank`` — where the *first* artist of that segment appears (directly the
  "first woman at rank 6–7" finding);
* ``mean_rank`` — the average position of the segment;
* ``top_k_share`` — the segment's share of the top-``k`` slots actually shown.

The metric is deliberately **descriptive, not target-driven** (the roadmap warns
that over-instrumenting fairness can turn a respectful tool into a quota-counter):
it reports the gap and the lens's effect on it; it never sets or enforces a quota,
and ``unknown`` is reported as a first-class segment, never folded away.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pipeline.models import Artist, Gender, Recommendation

#: The fixed segment vocabulary, in a stable reporting order. ``unknown`` is
#: always present so the first-class common case is never hidden by omission.
SEGMENTS: tuple[str, ...] = (
    "woman",
    "nonbinary",
    "man",
    "other",
    "female-fronted",
    "unknown",
)


def segment_of(artist: Artist) -> str:
    """The identity segment for an artist — sourced gender, then composition.

    Mirrors the recommender's own precedence: an individual's *sourced* gender
    wins; absent that, a *sourced* female-fronted composition; otherwise the
    first-class ``unknown``. Nothing here is inferred — it only reads sourced
    labels the resolver already produced.
    """
    gender = artist.identity.gender
    if gender is Gender.WOMAN:
        return "woman"
    if gender is Gender.NONBINARY:
        return "nonbinary"
    if gender is Gender.MAN:
        return "man"
    if gender is Gender.OTHER:
        return "other"
    if artist.female_fronted is True:
        return "female-fronted"
    return "unknown"


@dataclass(frozen=True)
class SegmentExposure:
    """Exposure stats for one identity segment within a ranked run."""

    segment: str
    count: int
    share: float  # count / total
    first_rank: int  # 1-based rank of the first occurrence; 0 if absent
    mean_rank: float  # mean 1-based rank of the segment; 0.0 if absent
    top_k_share: float  # fraction of the top-k slots held by this segment

    def to_dict(self) -> dict[str, object]:
        return {
            "segment": self.segment,
            "count": self.count,
            "share": round(self.share, 4),
            "first_rank": self.first_rank,
            "mean_rank": round(self.mean_rank, 4),
            "top_k_share": round(self.top_k_share, 4),
        }


@dataclass(frozen=True)
class ExposureReport:
    """Per-segment exposure for one ranked run, at a given ``k``."""

    k: int
    total: int
    segments: tuple[SegmentExposure, ...]

    def by_segment(self, name: str) -> SegmentExposure:
        for seg in self.segments:
            if seg.segment == name:
                return seg
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "k": self.k,
            "total": self.total,
            "segments": [seg.to_dict() for seg in self.segments],
        }


def _rank_of(rec: Recommendation, fallback: int) -> int:
    """The pick's 1-based rank, falling back to position when not yet assigned."""
    return rec.rank if rec.rank > 0 else fallback


def compute_exposure(recs: Sequence[Recommendation], k: int) -> ExposureReport:
    """Compute per-segment exposure over a *ranked* recommendation list.

    Every canonical segment in :data:`SEGMENTS` is reported, with zeroes when
    absent, so ``unknown`` (and any under-represented segment) is always visible
    rather than silently missing.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    total = len(recs)
    top_k_cutoff = min(k, total)
    ranks: dict[str, list[int]] = {seg: [] for seg in SEGMENTS}
    top_k_counts: dict[str, int] = dict.fromkeys(SEGMENTS, 0)

    for position, rec in enumerate(recs, start=1):
        seg = segment_of(rec.artist)
        rank = _rank_of(rec, position)
        ranks[seg].append(rank)
        if position <= top_k_cutoff:
            top_k_counts[seg] += 1

    segments: list[SegmentExposure] = []
    for seg in SEGMENTS:
        seg_ranks = ranks[seg]
        count = len(seg_ranks)
        segments.append(
            SegmentExposure(
                segment=seg,
                count=count,
                share=(count / total) if total else 0.0,
                first_rank=min(seg_ranks) if seg_ranks else 0,
                mean_rank=(sum(seg_ranks) / count) if count else 0.0,
                top_k_share=(top_k_counts[seg] / top_k_cutoff) if top_k_cutoff else 0.0,
            )
        )
    return ExposureReport(k=k, total=total, segments=tuple(segments))
