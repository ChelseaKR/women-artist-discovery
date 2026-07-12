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

from pipeline.ingest import build_profile
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Scrobble

from recommender.exposure import exposure_report
from recommender.hybrid import recommend

#: Lens strengths swept for the fairness report (spans 0 -> 1 so retention is
#: exercised "as lens strength varies", per FIX-05).
DEFAULT_LENS_SWEEP: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)

#: Default allowed relative drop vs the committed baseline before `wad eval`
#: fails (AIEV-26/27): a metric more than this fraction below its baseline
#: value is a regression, not noise.
DEFAULT_REGRESSION_TOLERANCE = 0.10


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
    scrobbles: list[Scrobble],
    catalog: dict[str, Artist],
    train_frac: float,
) -> tuple[list[Scrobble], list[Scrobble], ListeningProfile]:
    """Temporal train/test split plus the train-window profile with catalog tags.

    Re-attaches tags from the catalog so the content signal works on train data.
    Shared by :func:`evaluate` and :func:`fairness_report` so both grade the exact
    same held-out world.
    """
    train, test = temporal_split(scrobbles, train_frac)
    base_profile = build_profile(username, train)
    train_profile = ListeningProfile(
        username=base_profile.username,
        play_counts=base_profile.play_counts,
        artist_names=base_profile.artist_names,
        tags={aid: catalog[aid].tags for aid in base_profile.play_counts if aid in catalog},
    )
    return train, test, train_profile


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
    train, test, train_profile = _training_profile(username, scrobbles, catalog, train_frac)
    positives = ground_truth(train, test)
    known = train_profile.known_artist_ids

    hybrid_recs = recommend(train_profile, catalog, source, k=len(catalog), lens_strength=0.0)
    hybrid_ranked = [r.artist.artist_id for r in hybrid_recs]
    pop_ranked = popularity_ranking(catalog, exclude=set(known))

    return {
        "hybrid": _score("hybrid", hybrid_ranked, positives, k),
        "popularity": _score("popularity", pop_ranked, positives, k),
    }


def fairness_report(
    username: str,
    scrobbles: list[Scrobble],
    catalog: dict[str, Artist],
    source: ScrobbleSource,
    *,
    k: int = 10,
    train_frac: float = 0.7,
    lens_strengths: tuple[float, ...] = DEFAULT_LENS_SWEEP,
) -> dict[str, object]:
    """Compute the exposure / rank-fairness block for ``eval-report.json`` (FIX-05).

    Ranks the *full* held-out candidate set at each lens strength and hands the
    results to :func:`recommender.exposure.exposure_report`, which computes
    exposure-by-identity, the unknown-retention curve, per-segment rank shift, and
    the popularity x identity cross-tab. The ``guarantees`` sub-block is the
    merge-blocking unknown-retention signal.
    """
    _, _, train_profile = _training_profile(username, scrobbles, catalog, train_frac)
    recs_by_lens = {
        lens: recommend(train_profile, catalog, source, k=len(catalog), lens_strength=lens)
        for lens in lens_strengths
    }
    return exposure_report(recs_by_lens, k=k)


def check_regression(
    current: EvalResult,
    baseline_metrics: dict[str, float],
    *,
    tolerance: float = DEFAULT_REGRESSION_TOLERANCE,
) -> dict[str, object]:
    """Compare the hybrid model's current metrics against a committed baseline.

    Complements ``hybrid_beats_popularity`` (which only checks *this run's*
    popularity baseline): this catches the hybrid quietly getting worse release
    over release even while it still beats popularity. A metric absent from
    ``baseline_metrics`` is skipped, so extending the metric set later doesn't
    require rewriting the baseline file. Returns a JSON-able detail block with
    an overall ``regressed`` flag.
    """
    fields = ("precision_at_k", "recall_at_k", "map_at_k")
    detail: dict[str, dict[str, object]] = {}
    regressed = False
    for field in fields:
        base = baseline_metrics.get(field)
        if base is None:
            continue
        cur = getattr(current, field)
        floor = base * (1.0 - tolerance)
        field_regressed = cur < floor
        regressed = regressed or field_regressed
        detail[field] = {
            "baseline": base,
            "current": cur,
            "floor": round(floor, 4),
            "regressed": field_regressed,
        }
    return {"regressed": regressed, "tolerance": tolerance, "metrics": detail}


def to_report(results: dict[str, EvalResult]) -> dict[str, object]:
    """A JSON-able report (the committed eval artifact)."""
    hybrid = results["hybrid"]
    popularity = results["popularity"]
    return {
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
