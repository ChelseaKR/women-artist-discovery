"""Hybrid recommender: combine collaborative + content, then apply the values lens.

The base score is a convex blend ``alpha * collaborative + (1 - alpha) * content``,
each signal min-max normalised across candidates so neither dominates by scale.
The values lens is then applied **boost-only** (see :mod:`recommender.rerank`),
and every result is explained.

At ``lens_strength = 0`` the output is the pure-taste hybrid ranking — which is
what the offline eval compares against the popularity baseline.
"""

from __future__ import annotations

from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Recommendation

from recommender.collaborative import CollabResult, collaborative_scores
from recommender.content import ContentResult, content_scores
from recommender.explain import build_explanation
from recommender.rerank import sort_and_rank, values_boost_for_artist


def _normalise(value: float, peak: float) -> float:
    return value / peak if peak > 0.0 else 0.0


def recommend(
    profile: ListeningProfile,
    catalog: dict[str, Artist],
    source: ScrobbleSource,
    *,
    k: int = 20,
    alpha: float = 0.5,
    lens_strength: float = 0.0,
) -> list[Recommendation]:
    """Produce the top-``k`` explained recommendations.

    ``alpha`` weights collaborative vs content (0 = content only, 1 = collab only).
    ``lens_strength`` ∈ [0, 1] controls the values lens; 0 = pure taste ranking.
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be in [0, 1]")

    collab = collaborative_scores(profile, source)
    known = profile.known_artist_ids
    # Candidates must be enriched (present in catalog) and not already known.
    candidates = {
        aid for aid in (set(collab) | set(catalog)) if aid in catalog and aid not in known
    }
    content = content_scores(profile, catalog, candidates)

    collab_peak = max((collab[a].score for a in candidates if a in collab), default=0.0)
    content_peak = max((content[a].score for a in candidates), default=0.0)

    recs: list[Recommendation] = []
    for aid in sorted(candidates):
        artist = catalog[aid]
        c_res = collab.get(aid, CollabResult())
        t_res = content.get(aid, ContentResult())
        base = alpha * _normalise(c_res.score, collab_peak) + (1 - alpha) * _normalise(
            t_res.score, content_peak
        )
        delta = values_boost_for_artist(artist, lens_strength)
        explanation = build_explanation(artist, c_res, t_res, delta, lens_strength)
        recs.append(
            Recommendation(
                artist=artist,
                base_score=round(base, 6),
                rerank_delta=round(delta, 6),
                explanation=explanation,
            )
        )

    return sort_and_rank(recs)[:k]
