"""Exposure segmentation + the checked unknown-retention guarantee (EXP-10).

The values lens (:mod:`recommender.rerank`) is *boost-only by construction*:
:func:`recommender.rerank.rerank` only ever adds a non-negative ``rerank_delta``,
so an artist whose identity is ``unknown`` can never have its score lowered by
the lens. That is a true statement about the code — but "true by construction"
and "true of what actually got emitted" are different claims. This module makes
the second one checkable: :func:`assert_unknown_retained` inspects the *emitted*
recommendation lists at each lens strength and raises if the guarantee was
ever violated in practice, not just in the rerank function's math.

``docs/writeup/methods.md`` cites this module (not just ``rerank.py``) as the
proof for its "unknown-retention == 1.0" claim — see ``tests/test_exposure.py``
for the check exercised on real reranked output, and ``make audit`` (which runs
the test suite) as the command that regenerates that proof.
"""

from __future__ import annotations

from pipeline.models import Artist, Gender, Recommendation

#: Identity segments (sourced-only). ``unknown`` is first-class — it is always
#: present in :data:`SEGMENTS` and is never folded into another bucket or
#: silently dropped.
WOMAN = "woman"
NONBINARY = "nonbinary"
FEMALE_FRONTED = "female-fronted"
MAN = "man"
OTHER = "other"
UNKNOWN = "unknown"

#: Emitted/iterated in a fixed order for a stable, diffable report.
SEGMENTS: tuple[str, ...] = (WOMAN, NONBINARY, FEMALE_FRONTED, MAN, OTHER, UNKNOWN)


class FairnessAssertionError(AssertionError):
    """Raised when emitted output violates the unknown-retention guarantee."""


def identity_segment(artist: Artist) -> str:
    """The identity segment for an artist — sourced gender, then composition.

    Mirrors the re-rank layer's own precedence (:mod:`recommender.rerank`): a
    sourced individual gender wins; absent that, a sourced female-fronted
    composition; otherwise the first-class ``unknown``. Nothing here is
    inferred — it only reads labels the identity resolver already sourced.
    """
    gender = artist.identity.gender
    if gender is Gender.WOMAN:
        return WOMAN
    if gender is Gender.NONBINARY:
        return NONBINARY
    if gender is Gender.MAN:
        return MAN
    if gender is Gender.OTHER:
        return OTHER
    if artist.female_fronted is True:  # sourced band composition, not a personal claim
        return FEMALE_FRONTED
    return UNKNOWN


def _unknown_scores(recs: list[Recommendation]) -> dict[str, float]:
    """artist_id -> score for every ``unknown``-segment artist in the output."""
    return {r.artist.artist_id: r.score for r in recs if identity_segment(r.artist) == UNKNOWN}


def unknown_retention(
    recs_by_lens: dict[float, list[Recommendation]], *, base_lens: float = 0.0
) -> dict[float, float]:
    """Per-lens fraction of pure-taste ``unknown`` artists retained with an unchanged score.

    Computed over the *full emitted output* at each lens (presence + score), not
    on the rerank function's math. ``1.0`` means every unknown artist that pure
    taste (``base_lens``) surfaced is still present and un-penalised at that
    lens strength.
    """
    base = _unknown_scores(recs_by_lens[base_lens])
    out: dict[float, float] = {}
    for lens, recs in recs_by_lens.items():
        if not base:
            out[lens] = 1.0
            continue
        present = _unknown_scores(recs)
        retained = sum(1 for aid, score in base.items() if present.get(aid) == score)
        out[lens] = round(retained / len(base), 4)
    return out


def assert_unknown_retained(
    recs_by_lens: dict[float, list[Recommendation]], *, base_lens: float = 0.0
) -> None:
    """Merge-blocking guarantee, checked on emitted output: unknown is never penalised.

    Raises :class:`FairnessAssertionError` if, at any lens strength, an
    ``unknown``-identity artist surfaced by pure taste (``base_lens``) is
    either dropped from the output or has its score lowered. Boost-only
    reranking makes this hold by construction; this verifies it on the
    *numbers the emitted output actually carries*.
    """
    base = _unknown_scores(recs_by_lens[base_lens])
    for lens, recs in recs_by_lens.items():
        present = _unknown_scores(recs)
        for aid, base_score in base.items():
            if aid not in present:
                raise FairnessAssertionError(
                    f"unknown artist {aid!r} dropped from output at lens {lens}"
                )
            if present[aid] < base_score:
                raise FairnessAssertionError(
                    f"unknown artist {aid!r} was down-ranked by the lens at {lens}: "
                    f"score {base_score} -> {present[aid]}"
                )
