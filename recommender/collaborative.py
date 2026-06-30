"""Collaborative signal: similar-artist edges weighted by how much you listen.

For each artist you play (weighted by play count), its similar artists accrue
score proportional to ``your_play_weight * similarity``. Artists you already know
are excluded. We keep the contributing seeds so the explanation can say *why*
("because you listen to X and Y").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.lastfm import ScrobbleSource
from pipeline.models import ListeningProfile


@dataclass
class Contributor:
    seed_id: str
    seed_name: str
    similarity: float
    seed_weight: float


@dataclass
class CollabResult:
    score: float = 0.0
    contributors: list[Contributor] = field(default_factory=list)

    def top_contributors(self, n: int = 3) -> list[Contributor]:
        return sorted(
            self.contributors,
            key=lambda c: (-(c.similarity * c.seed_weight), c.seed_id),
        )[:n]


def collaborative_scores(
    profile: ListeningProfile, source: ScrobbleSource
) -> dict[str, CollabResult]:
    """Score unknown candidates from the similar-artist graph. Deterministic."""
    total_plays = sum(profile.play_counts.values()) or 1
    known = profile.known_artist_ids
    results: dict[str, CollabResult] = {}

    # Iterate seeds in a stable order for reproducibility.
    for seed_id in sorted(profile.play_counts):
        seed_weight = profile.play_counts[seed_id] / total_plays
        seed_name = profile.artist_names.get(seed_id, seed_id)
        for cand_id, similarity in source.similar_artists(seed_id):
            if cand_id in known or cand_id == seed_id:
                continue
            res = results.setdefault(cand_id, CollabResult())
            res.score += seed_weight * similarity
            res.contributors.append(Contributor(seed_id, seed_name, similarity, seed_weight))
    return results
