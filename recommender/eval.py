"""Offline evaluation: does the hybrid beat a popularity baseline on held-out plays?

Protocol (M3 acceptance criterion):

1. Split a user's scrobbles **temporally** — earlier plays train, later plays test.
2. Ground-truth positives = artists discovered in the test window that were not
   already in the train window (genuine future discoveries).
3. Rank candidates two ways — the hybrid (pure taste, ``lens_strength = 0``) and a
   popularity baseline (most listeners first) — and score precision/recall/MAP@k.

Everything is deterministic by construction (temporal split + stable sorts), so
the eval is reproducible without a seed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from pipeline.ingest import build_profile
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Scrobble

from recommender.hybrid import recommend

#: Half-life used for the "hybrid_decay" comparison variant when the caller
#: does not specify one — chosen so a year-old play has decayed to ~13% of a
#: fresh one, which is enough to separate recency-heavy from stale-heavy
#: tastes on the held-out window without erasing older plays outright.
DEFAULT_DECAY_HALF_LIFE_DAYS = 180.0


@dataclass(frozen=True)
class EvalResult:
    model: str
    k: int
    precision_at_k: float
    recall_at_k: float
    map_at_k: float
    n_positives: int


def temporal_split(
    scrobbles: list[Scrobble], train_frac: float = 0.7
) -> tuple[list[Scrobble], list[Scrobble]]:
    """Split chronologically: first ``train_frac`` of plays train, rest test."""
    if not (0.0 < train_frac < 1.0):
        raise ValueError("train_frac must be in (0, 1)")
    ordered = sorted(scrobbles, key=lambda s: s.ts)
    cut = int(len(ordered) * train_frac)
    return ordered[:cut], ordered[cut:]


def ground_truth(train: list[Scrobble], test: list[Scrobble]) -> set[str]:
    """Artist ids first heard in the test window — the discoveries to recover."""
    train_ids = {s.artist_id or s.artist_name for s in train}
    test_ids = {s.artist_id or s.artist_name for s in test}
    return {aid for aid in test_ids if aid and aid not in train_ids}


def precision_recall_at_k(
    ranked_ids: list[str], positives: set[str], k: int
) -> tuple[float, float]:
    top = ranked_ids[:k]
    if not top:
        return 0.0, 0.0
    hits = sum(1 for aid in top if aid in positives)
    precision = hits / len(top)
    recall = hits / len(positives) if positives else 0.0
    return precision, recall


def average_precision_at_k(ranked_ids: list[str], positives: set[str], k: int) -> float:
    if not positives:
        return 0.0
    hits = 0
    cumulative = 0.0
    for i, aid in enumerate(ranked_ids[:k], start=1):
        if aid in positives:
            hits += 1
            cumulative += hits / i
    return cumulative / min(len(positives), k)


def _score(model: str, ranked_ids: list[str], positives: set[str], k: int) -> EvalResult:
    precision, recall = precision_recall_at_k(ranked_ids, positives, k)
    return EvalResult(
        model=model,
        k=k,
        precision_at_k=round(precision, 4),
        recall_at_k=round(recall, 4),
        map_at_k=round(average_precision_at_k(ranked_ids, positives, k), 4),
        n_positives=len(positives),
    )


def popularity_ranking(catalog: dict[str, Artist], exclude: set[str]) -> list[str]:
    """Baseline: candidates by listener count, descending (id tie-break)."""
    candidates = [a for aid, a in catalog.items() if aid not in exclude]
    candidates.sort(key=lambda a: (-a.listeners, a.artist_id))
    return [a.artist_id for a in candidates]


def _training_profile(
    username: str,
    train: list[Scrobble],
    catalog: dict[str, Artist],
    *,
    half_life_days: Optional[float] = None,
) -> ListeningProfile:
    """Build the train-window profile, tags re-attached from the catalog.

    ``half_life_days`` optionally applies recency decay (EXP-06 — Temporal
    taste profiles) via :func:`pipeline.ingest.build_profile`; ``None`` is the
    flat play-count profile the eval has always used. Either way ``now_ts``
    is left at its default (max ts within ``train``), so the profile — and
    therefore the eval — stays reproducible without a seed.
    """
    base_profile = build_profile(username, train, half_life_days=half_life_days)
    return ListeningProfile(
        username=base_profile.username,
        play_counts=base_profile.play_counts,
        artist_names=base_profile.artist_names,
        tags={aid: catalog[aid].tags for aid in base_profile.play_counts if aid in catalog},
    )


def evaluate(
    username: str,
    scrobbles: list[Scrobble],
    catalog: dict[str, Artist],
    source: ScrobbleSource,
    *,
    k: int = 10,
    train_frac: float = 0.7,
    half_life_days: Optional[float] = None,
) -> dict[str, EvalResult]:
    """Run hybrid, popularity, and a decay variant on a temporal hold-out.

    Returns results keyed by model: ``"hybrid"`` (flat play counts, decay
    off), ``"popularity"`` (baseline), and ``"hybrid_decay"`` (same hybrid
    ranking but trained on a recency-decayed profile, decay on) — so a report
    built from this dict can state numerically whether decay helps on this
    held-out window. ``half_life_days`` picks the decay variant's half-life;
    it defaults to :data:`DEFAULT_DECAY_HALF_LIFE_DAYS` when not given.
    """
    train, test = temporal_split(scrobbles, train_frac)
    positives = ground_truth(train, test)

    train_profile = _training_profile(username, train, catalog)
    known = train_profile.known_artist_ids

    hybrid_recs = recommend(train_profile, catalog, source, k=len(catalog), lens_strength=0.0)
    hybrid_ranked = [r.artist.artist_id for r in hybrid_recs]
    pop_ranked = popularity_ranking(catalog, exclude=set(known))

    decay_half_life = half_life_days if half_life_days is not None else DEFAULT_DECAY_HALF_LIFE_DAYS
    decay_profile = _training_profile(username, train, catalog, half_life_days=decay_half_life)
    decay_recs = recommend(decay_profile, catalog, source, k=len(catalog), lens_strength=0.0)
    decay_ranked = [r.artist.artist_id for r in decay_recs]

    return {
        "hybrid": _score("hybrid", hybrid_ranked, positives, k),
        "popularity": _score("popularity", pop_ranked, positives, k),
        "hybrid_decay": _score("hybrid_decay", decay_ranked, positives, k),
    }


def to_report(results: dict[str, EvalResult]) -> dict[str, object]:
    """A JSON-able report (the committed eval artifact)."""
    hybrid = results["hybrid"]
    popularity = results["popularity"]
    report: dict[str, object] = {
        "k": hybrid.k,
        "n_positives": hybrid.n_positives,
        "models": {name: asdict(res) for name, res in results.items()},
        "hybrid_beats_popularity": (
            hybrid.map_at_k > popularity.map_at_k
            or (
                hybrid.map_at_k == popularity.map_at_k
                and hybrid.recall_at_k >= popularity.recall_at_k
            )
        ),
    }
    decay = results.get("hybrid_decay")
    if decay is not None:
        # Numeric, not just boolean: how much (if any) recency decay moved
        # map@k on this held-out window, decay-on vs decay-off (EXP-06).
        report["decay_map_at_k_delta"] = round(decay.map_at_k - hybrid.map_at_k, 4)
        report["decay_improves_map_at_k"] = decay.map_at_k > hybrid.map_at_k
    return report
