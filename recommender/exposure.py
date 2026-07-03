"""Fairness observability: exposure share by identity segment, and retention.

This is the aggregate counterpart to :mod:`recommender.rerank`. Where the
re-rank layer guarantees a *single* recommendation's own score never drops
because its identity is unknown, this module measures the *aggregate* effect
of the lens on the result set: which identity segment holds which share of
the top-``k`` exposure, and whether unknown-identity artists are ever
displaced out of the results as the lens strength changes (they must not be
— this is the same boost-only guarantee, proven in aggregate).

Segmentation is by *identity basis* — self-identified / band-composition /
unknown — exactly the basis every :class:`~pipeline.models.Explanation`
already carries. No new classification happens here: unknown stays
first-class and nothing is inferred, this module only aggregates what is
already sourced.

Pure and UI-agnostic (no Streamlit import) so it is unit-testable without a
live dashboard, and shared by both the interactive dashboard
(:mod:`app.dashboard`) and the static, a11y-audited HTML render
(:mod:`app.render`, :mod:`app.build_static`).
"""

from __future__ import annotations

from typing import cast

from pipeline.models import IdentityBasis, Recommendation

#: Stable segment order for every table/report in this module. Unknown is
#: first-class and always present — never inferred into one of the other two.
SEGMENTS: tuple[str, ...] = (
    str(IdentityBasis.SELF_IDENTIFIED),
    str(IdentityBasis.BAND_COMPOSITION),
    str(IdentityBasis.UNKNOWN),
)

_UNKNOWN_SEGMENT = str(IdentityBasis.UNKNOWN)


def identity_segment(rec: Recommendation) -> str:
    """The sourced identity-basis segment for a recommendation. Never inferred."""
    return str(rec.explanation.identity_basis)


def exposure_at_k(recs: list[Recommendation], k: int) -> dict[str, float]:
    """Each segment's share of the top-``k`` slots.

    Shares sum to 1.0 when there is at least one recommendation; an empty
    top-``k`` reports 0.0 for every segment rather than dividing by zero.
    """
    top = recs[:k]
    counts: dict[str, int] = dict.fromkeys(SEGMENTS, 0)
    for rec in top:
        seg = identity_segment(rec)
        counts[seg] = counts.get(seg, 0) + 1
    total = len(top)
    if total == 0:
        return dict.fromkeys(SEGMENTS, 0.0)
    return {seg: counts.get(seg, 0) / total for seg in SEGMENTS}


def unknown_retention(base: list[Recommendation], current: list[Recommendation], k: int) -> float:
    """Fraction of the base top-``k``'s unknown-segment artists still present.

    The aggregate form of the boost-only guarantee (:mod:`recommender.rerank`):
    raising the lens must never displace an unknown-identity artist out of the
    results. ``1.0`` means every unknown artist surfaced at ``base`` is still
    surfaced at ``current`` — the value the merge-blocking test pins.
    """
    base_unknown_ids = {
        r.artist.artist_id for r in base[:k] if identity_segment(r) == _UNKNOWN_SEGMENT
    }
    if not base_unknown_ids:
        return 1.0
    current_ids = {r.artist.artist_id for r in current[:k]}
    retained = base_unknown_ids & current_ids
    return len(retained) / len(base_unknown_ids)


def rank_shift(base: list[Recommendation], current: list[Recommendation]) -> dict[str, int]:
    """Per-artist rank delta between two rankings (positive = moved up).

    Reported for artists present in both rankings, keyed by ``artist_id``.
    """
    base_ranks = {r.artist.artist_id: r.rank for r in base}
    current_ranks = {r.artist.artist_id: r.rank for r in current}
    shared = base_ranks.keys() & current_ranks.keys()
    return {aid: base_ranks[aid] - current_ranks[aid] for aid in shared}


def exposure_report(
    recs_by_lens: dict[float, list[Recommendation]],
    k: int,
    *,
    base_lens: float | None = None,
) -> dict[str, object]:
    """A JSON-able exposure report across every lens in ``recs_by_lens``.

    Keyed (as strings, ``%g``-formatted) by each lens value present; each
    entry carries that lens's segment exposure shares plus unknown retention
    measured against ``base_lens`` (defaults to the smallest lens present —
    typically ``0.0``, the pure-taste ranking).

    Raises ``ValueError`` if ``base_lens`` is given but absent from
    ``recs_by_lens``.
    """
    if not recs_by_lens:
        return {"k": k, "base_lens": base_lens, "lenses": {}}
    if base_lens is None:
        base_lens = min(recs_by_lens)
    elif base_lens not in recs_by_lens:
        raise ValueError(f"base_lens {base_lens!r} not present in recs_by_lens")

    base_recs = recs_by_lens[base_lens]
    lenses: dict[str, object] = {}
    for lens, recs in recs_by_lens.items():
        lenses[f"{lens:g}"] = {
            "exposure": exposure_at_k(recs, k),
            "unknown_retention": unknown_retention(base_recs, recs, k),
        }
    return {"k": k, "base_lens": base_lens, "lenses": lenses}


def observability_panel(
    recs_by_lens: dict[float, list[Recommendation]],
    current_lens: float,
    *,
    k: int,
    base_lens: float = 0.0,
) -> dict[str, object]:
    """Display-ready rows for the fairness-observability panel (table-first).

    Reuses :func:`exposure_report` / :func:`exposure_at_k` / :func:`rank_shift`
    rather than duplicating their aggregation — this function only reshapes
    those results into rows aligned to :data:`SEGMENTS`, so a UI (Streamlit or
    static HTML) can render a table with no further computation and stay
    unit-testable independent of any UI framework.

    ``recs_by_lens`` must contain both ``base_lens`` and ``current_lens`` (the
    caller — the dashboard or static-build glue — computes recommendations at
    a fixed lens grid plus whatever lens is currently selected).

    Returns a dict with:

    * ``exposure_rows`` — per-segment exposure_at_k at ``base_lens`` vs
      ``current_lens``, aligned to :data:`SEGMENTS`.
    * ``retention_row`` — unknown retention at every lens present in
      ``recs_by_lens`` (should be pinned at 1.0 — the merge-blocking
      guarantee mirroring the excellence bar).
    * ``rank_shift_row`` — per-artist rank shift, current vs base.
    """
    if current_lens not in recs_by_lens:
        raise ValueError(f"current_lens {current_lens!r} not present in recs_by_lens")

    report = exposure_report(recs_by_lens, k, base_lens=base_lens)
    lenses_report = cast("dict[str, dict[str, object]]", report["lenses"])

    base_recs = recs_by_lens[base_lens]
    current_recs = recs_by_lens[current_lens]

    base_exposure = exposure_at_k(base_recs, k)
    current_exposure = exposure_at_k(current_recs, k)
    exposure_rows: list[dict[str, object]] = [
        {
            "segment": seg,
            "base_share": base_exposure[seg],
            "current_share": current_exposure[seg],
        }
        for seg in SEGMENTS
    ]

    by_lens: dict[str, float] = {
        f"{lens:g}": cast(float, lenses_report[f"{lens:g}"]["unknown_retention"])
        for lens in sorted(recs_by_lens)
    }
    retention_row: dict[str, object] = {"segment": _UNKNOWN_SEGMENT, "by_lens": by_lens}

    return {
        "k": k,
        "base_lens": base_lens,
        "current_lens": current_lens,
        "segments": list(SEGMENTS),
        "exposure_rows": exposure_rows,
        "retention_row": retention_row,
        "rank_shift_row": rank_shift(base_recs, current_recs),
    }
