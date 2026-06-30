"""Content signal: cosine similarity between your tag profile and a candidate's tags.

Your tag profile is the play-count-weighted sum of the tags of artists you
listen to. A candidate is scored by the cosine similarity of its tag vector to
that profile. We keep the overlapping tags so the explanation can name them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pipeline.models import Artist, ListeningProfile


@dataclass
class ContentResult:
    score: float = 0.0
    overlap_tags: list[str] = field(default_factory=list)


def _profile_tag_vector(profile: ListeningProfile) -> dict[str, float]:
    vec: dict[str, float] = {}
    for artist_id, count in profile.play_counts.items():
        for tag in profile.tags.get(artist_id, ()):
            vec[tag] = vec.get(tag, 0.0) + float(count)
    return vec


def _cosine(a: dict[str, float], b: dict[str, float]) -> tuple[float, list[str]]:
    shared = set(a) & set(b)
    if not shared:
        return 0.0, []
    dot = sum(a[t] * b[t] for t in shared)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0, []
    return dot / (na * nb), sorted(shared)


def content_scores(
    profile: ListeningProfile,
    catalog: dict[str, Artist],
    candidates: set[str],
) -> dict[str, ContentResult]:
    """Score each candidate by tag cosine similarity to the listening profile."""
    profile_vec = _profile_tag_vector(profile)
    results: dict[str, ContentResult] = {}
    for cand_id in sorted(candidates):
        artist = catalog.get(cand_id)
        if artist is None or not artist.tags:
            results[cand_id] = ContentResult()
            continue
        cand_vec = dict.fromkeys(artist.tags, 1.0)
        score, overlap = _cosine(profile_vec, cand_vec)
        results[cand_id] = ContentResult(score=score, overlap_tags=overlap)
    return results
