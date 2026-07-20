"""Serendipity control — MMR-style, identity-blind tag-space diversification.

An "explore ↔ exploit" slider (``explore`` in ``[0, 1]``) that re-orders an
already-ranked list to trade relevance for tag-space diversity, using the
classic greedy Maximal Marginal Relevance (MMR) algorithm:

    MMR(c) = (1 - explore) * relevance(c) - explore * max_{s in S} sim(c, s)

``relevance`` is the recommendation's already-computed ``score`` (base_score +
rerank_delta from the values lens); nothing here recomputes or touches that
score. ``sim`` is Jaccard similarity over ``Artist.tags`` only.

This is deliberately a *pure re-ordering* pass, like :func:`recommender.rerank
.sort_and_rank` — it reads relevance and tags, and nothing else. In
particular it never reads ``artist.identity``, ``artist.composition``,
``artist.values_aligned``, or any gender-shaped field: diversity here is a
serendipity knob, not a values lens, and the two must stay structurally
separate. ``tests/test_diversify.py`` proves this with an AST guard in the
spirit of ``tests/test_no_inference.py``.

The hybrid orchestrator passes only candidates that are eligible to move and
reconstructs protected unknown slots afterward. This module remains a generic,
identity-blind ranking primitive.
"""

from __future__ import annotations

from pipeline.models import Recommendation


def _tag_set(rec: Recommendation) -> frozenset[str]:
    return frozenset(rec.artist.tags)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity over two tag sets; 0 if either is empty."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def diversify(
    recs: list[Recommendation], explore: float, *, k: int | None = None
) -> list[Recommendation]:
    """Greedy MMR re-order over ``Artist.tags``. Deterministic; score-preserving.

    ``explore`` ∈ [0, 1]: 0 = identical to input order (pure relevance), 1 =
    maximum tag-space diversity. Raises ``ValueError`` outside that range.

    The first pick is always the highest-relevance candidate (an empty
    selected set has no similarity penalty, so the MMR score reduces to pure
    relevance). Ties — in the first pick and every subsequent one — break on
    ``artist_id`` ascending, for determinism.

    This is a re-ordering pass only: it never mutates ``base_score`` or
    ``rerank_delta``, only re-assigns 1-based ``rank`` via
    :meth:`Recommendation.with_rank`. The output is a permutation of the
    input (same artist_ids, same multiset of scores).
    """
    if not (0.0 <= explore <= 1.0):
        raise ValueError("explore must be in [0, 1]")

    limit = len(recs) if k is None else max(0, min(k, len(recs)))
    if limit == 0:
        return []
    # A ranked input came from the values lens and can contain protected unknown
    # slots, so it must be a true no-op. Preserve the historical convenience for
    # direct callers that pass unranked (rank=0) recommendations by sorting those.
    if explore == 0.0:
        has_complete_ranks = [rec.rank for rec in recs] == list(range(1, len(recs) + 1))
        ordered = (
            recs
            if has_complete_ranks
            else sorted(recs, key=lambda rec: (-rec.score, rec.artist.artist_id))
        )
        return [rec.with_rank(i + 1) for i, rec in enumerate(ordered[:limit])]

    remaining = list(recs)
    if not remaining:
        return []

    tags_by_id = {rec.artist.artist_id: _tag_set(rec) for rec in remaining}

    # First pick: pure relevance. With an empty selected set the marginal
    # -relevance term has nothing to diversify against, so — independent of
    # ``explore`` — the opening pick is simply the highest-scoring candidate
    # (ties broken by artist_id ascending).
    first_idx = 0
    for idx, cand in enumerate(remaining):
        current_best = remaining[first_idx]
        if cand.score > current_best.score or (
            cand.score == current_best.score
            and cand.artist.artist_id < current_best.artist.artist_id
        ):
            first_idx = idx

    selected: list[Recommendation] = [remaining.pop(first_idx)]
    selected_tags: list[frozenset[str]] = [tags_by_id[selected[0].artist.artist_id]]

    while remaining and len(selected) < limit:
        best_idx = 0
        best_mmr: float | None = None
        for idx, cand in enumerate(remaining):
            cand_tags = tags_by_id[cand.artist.artist_id]
            max_sim = max(_jaccard(cand_tags, s) for s in selected_tags)
            mmr = (1 - explore) * cand.score - explore * max_sim
            current_best = remaining[best_idx]
            if (
                best_mmr is None
                or mmr > best_mmr
                or (mmr == best_mmr and cand.artist.artist_id < current_best.artist.artist_id)
            ):
                best_idx = idx
                best_mmr = mmr

        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        selected_tags.append(tags_by_id[chosen.artist.artist_id])

    return [rec.with_rank(i + 1) for i, rec in enumerate(selected)]
