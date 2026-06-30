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

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Optional

from pipeline.ingest import build_profile
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Scrobble

from recommender.exposure import ExposureReport, compute_exposure
from recommender.hybrid import recommend


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


def _train_profile(
    username: str, train: list[Scrobble], catalog: dict[str, Artist]
) -> ListeningProfile:
    """The held-out *train* profile, with tags re-attached from the catalog."""
    base_profile = build_profile(username, train)
    # Re-attach tags from the catalog so the content signal works on train data.
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
) -> dict[str, EvalResult]:
    """Run both models on a temporal hold-out. Returns results keyed by model."""
    train, test = temporal_split(scrobbles, train_frac)
    positives = ground_truth(train, test)
    train_profile = _train_profile(username, train, catalog)
    known = train_profile.known_artist_ids

    hybrid_recs = recommend(train_profile, catalog, source, k=len(catalog), lens_strength=0.0)
    hybrid_ranked = [r.artist.artist_id for r in hybrid_recs]
    pop_ranked = popularity_ranking(catalog, exclude=set(known))

    return {
        "hybrid": _score("hybrid", hybrid_ranked, positives, k),
        "popularity": _score("popularity", pop_ranked, positives, k),
    }


def exposure_by_lens(
    username: str,
    scrobbles: list[Scrobble],
    catalog: dict[str, Artist],
    source: ScrobbleSource,
    *,
    k: int = 5,
    train_frac: float = 0.7,
) -> dict[str, ExposureReport]:
    """Per-identity exposure of the *delivered* ranking, taste vs. the values lens.

    Returns two :class:`~recommender.exposure.ExposureReport` s — ``"taste"``
    (lens off, the pure-hybrid ranking the eval scores) and ``"values_lens"``
    (lens at full strength) — so the report shows the bounded, boost-only lens's
    effect on exposure without ever penalising or dropping the unknown segment.
    """
    train, _test = temporal_split(scrobbles, train_frac)
    train_profile = _train_profile(username, train, catalog)
    reports: dict[str, ExposureReport] = {}
    for label, lens in (("taste", 0.0), ("values_lens", 1.0)):
        recs = recommend(train_profile, catalog, source, k=len(catalog), lens_strength=lens)
        reports[label] = compute_exposure(recs, k)
    return reports


def to_report(
    results: dict[str, EvalResult],
    exposure: Optional[Mapping[str, ExposureReport]] = None,
) -> dict[str, object]:
    """A JSON-able report (the committed eval artifact).

    When ``exposure`` is supplied it is embedded under ``"exposure"`` beside the
    precision/recall/MAP models, so a single artifact carries both *quality* and
    *fairness/exposure* numbers for the run.
    """
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
    if exposure is not None:
        report["exposure"] = {label: rep.to_dict() for label, rep in exposure.items()}
    return report
