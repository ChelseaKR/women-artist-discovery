"""Offline evaluation: does the hybrid beat a popularity baseline on held-out plays?

Protocol (M3 acceptance criterion):

1. Split a user's scrobbles **temporally** — earlier plays train, later plays test.
2. Ground-truth positives = artists discovered in the test window that were not
   already in the train window (genuine future discoveries).
3. Rank candidates two ways — the hybrid (pure taste, ``lens_strength = 0``) and a
   popularity baseline (most listeners first) — and score precision/recall/MAP@k.

Everything is deterministic by construction (temporal split + stable sorts), so
the eval is reproducible without a seed.

FIX-06 (de-circularize the eval): a single hand-tuned fixture proves only that
the recommender passes the fixture it was tuned against. :func:`evaluate` above
still scores one world; :func:`evaluate_worlds` runs it across every
independent fixture family in :data:`pipeline.fixtures.ALL_WORLDS` and
aggregates, so the CI gate's evidence is no longer circular. :func:`eval_real`
is the separate, human-gated real-data leg — local-only, never CI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Optional

from pipeline.ingest import build_profile
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Scrobble

from recommender.exposure import exposure_report
from recommender.hybrid import recommend

DEFAULT_LENS_SWEEP: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
DEFAULT_REGRESSION_TOLERANCE = 0.10

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pipeline.fixtures import World


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
    base_profile = build_profile(username, train)
    # Re-attach tags from the catalog so the content signal works on train data.
    train_profile = ListeningProfile(
        username=base_profile.username,
        play_counts=base_profile.play_counts,
        artist_names=base_profile.artist_names,
        tags={aid: catalog[aid].tags for aid in base_profile.play_counts if aid in catalog},
    )
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
    """Compute exposure and unknown-retention across a lens sweep."""
    train, _ = temporal_split(scrobbles, train_frac)
    base_profile = build_profile(username, train)
    train_profile = ListeningProfile(
        username=base_profile.username,
        play_counts=base_profile.play_counts,
        artist_names=base_profile.artist_names,
        tags={aid: catalog[aid].tags for aid in base_profile.play_counts if aid in catalog},
    )
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
    """Compare current hybrid metrics with a committed relative-tolerance floor."""
    detail: dict[str, dict[str, object]] = {}
    regressed = False
    for field in ("precision_at_k", "recall_at_k", "map_at_k"):
        baseline = baseline_metrics.get(field)
        if baseline is None:
            continue
        current_value = getattr(current, field)
        floor = baseline * (1.0 - tolerance)
        field_regressed = current_value < floor
        regressed = regressed or field_regressed
        detail[field] = {
            "baseline": baseline,
            "current": current_value,
            "floor": round(floor, 4),
            "regressed": field_regressed,
        }
    return {"regressed": regressed, "tolerance": tolerance, "metrics": detail}


@dataclass(frozen=True)
class EvalComparison:
    """Effect-size comparison between the hybrid and the popularity baseline.

    FIX-06: the eval must report *how much* the hybrid wins or loses by, not
    just a boolean. ``lift`` is ``None`` when the baseline's MAP@k is exactly
    0 and the hybrid's is not — the ratio is undefined/unbounded, not
    infinite-as-a-JSON-number.
    """

    k: int
    n_positives: int
    hybrid: EvalResult
    popularity: EvalResult
    map_delta: float
    recall_delta: float
    lift: Optional[float]
    hybrid_beats_popularity: bool
    verdict: str


def compare(results: dict[str, EvalResult]) -> EvalComparison:
    """Reduce a pair of :class:`EvalResult` into an effect-size comparison."""
    hybrid = results["hybrid"]
    popularity = results["popularity"]
    map_delta = round(hybrid.map_at_k - popularity.map_at_k, 4)
    recall_delta = round(hybrid.recall_at_k - popularity.recall_at_k, 4)
    lift: Optional[float]
    if popularity.map_at_k > 0:
        lift = round(hybrid.map_at_k / popularity.map_at_k, 4)
    elif hybrid.map_at_k > 0:
        lift = None  # baseline scored zero MAP — the ratio is unbounded/undefined
    else:
        lift = 1.0  # both zero: no measurable difference
    beats = hybrid.map_at_k > popularity.map_at_k or (
        hybrid.map_at_k == popularity.map_at_k and hybrid.recall_at_k >= popularity.recall_at_k
    )
    return EvalComparison(
        k=hybrid.k,
        n_positives=hybrid.n_positives,
        hybrid=hybrid,
        popularity=popularity,
        map_delta=map_delta,
        recall_delta=recall_delta,
        lift=lift,
        hybrid_beats_popularity=beats,
        verdict="hybrid" if beats else "popularity",
    )


def to_report(results: dict[str, EvalResult]) -> dict[str, object]:
    """A JSON-able report for one world (the committed eval artifact's shape).

    Carries effect sizes (``map_delta``, ``recall_delta``, ``lift``) and a
    ``verdict`` alongside the original boolean, which is kept for back-compat.
    """
    comparison = compare(results)
    return {
        "k": comparison.k,
        "n_positives": comparison.n_positives,
        "models": {name: asdict(res) for name, res in results.items()},
        "map_delta": comparison.map_delta,
        "recall_delta": comparison.recall_delta,
        "lift": comparison.lift,
        "hybrid_beats_popularity": comparison.hybrid_beats_popularity,  # back-compat
        "verdict": comparison.verdict,
    }


#: The circularity caveat, embedded directly in every aggregated report so the
#: limitation travels with the evidence rather than living only in a doc.
DEMO_WORLD_TUNING_CAVEAT = (
    "One world in this report ('demo-tuned-indie', from pipeline.demo) is "
    "hand-tuned so the hybrid recovers its held-out discoveries — see that "
    "module's docstring. It is included, and labelled, deliberately: hiding it "
    "would be worse than disclosing it. The other worlds (sparse-tags, "
    "popularity-skewed, no-collaborative-signal, adversarial-near-misses; see "
    "pipeline/fixtures.py) are independent synthetic fixtures NOT tuned to make "
    "the hybrid win. Treat the aggregate across all worlds — not any single "
    "world, and especially not 'demo-tuned-indie' alone — as the evidence. "
    "Even the aggregate is still synthetic data; the only fully de-circularized "
    "signal is the separate, human-gated real-data leg (eval_real / "
    "`make eval-real`), which is intentionally excluded from CI. "
    "See docs/ideation/02-large-scale-fixes.md FIX-06."
)


def evaluate_worlds(
    worlds: Optional[dict[str, Callable[[], World]]] = None,
    *,
    k: int = 5,
    train_frac: float = 0.7,
) -> dict[str, object]:
    """Run :func:`evaluate` across every fixture family and aggregate (FIX-06).

    Defaults to :data:`pipeline.fixtures.ALL_WORLDS` so ``make eval`` grades the
    hybrid against several structurally independent synthetic worlds instead of
    only the one hand-tuned ``pipeline.demo`` world. Returns per-world reports
    (each shaped like :func:`to_report`'s output) plus an aggregate verdict and
    the tuning caveat, embedded directly in the returned dict.
    """
    if worlds is None:
        from pipeline.fixtures import ALL_WORLDS  # local import: pipeline -> recommender, no cycle

        worlds = ALL_WORLDS

    per_world: dict[str, dict[str, object]] = {}
    wins = 0
    map_deltas: list[float] = []
    recall_deltas: list[float] = []
    for name, build in worlds.items():
        username, scrobbles, catalog, source = build()
        results = evaluate(username, scrobbles, catalog, source, k=k, train_frac=train_frac)
        report = to_report(results)
        per_world[name] = report
        if report["hybrid_beats_popularity"]:
            wins += 1
        map_deltas.append(float(report["map_delta"]))  # type: ignore[arg-type]
        recall_deltas.append(float(report["recall_delta"]))  # type: ignore[arg-type]

    n_worlds = len(per_world)
    mean_map_delta = round(sum(map_deltas) / n_worlds, 4) if n_worlds else 0.0
    mean_recall_delta = round(sum(recall_deltas) / n_worlds, 4) if n_worlds else 0.0
    # Aggregate verdict mirrors the single-world rule, applied to the mean effect
    # size across all worlds rather than to any one world's numbers.
    aggregate_beats = mean_map_delta > 0 or (mean_map_delta == 0 and mean_recall_delta >= 0)

    return {
        "k": k,
        "train_frac": train_frac,
        "n_worlds": n_worlds,
        "worlds_hybrid_wins": wins,
        "mean_map_delta": mean_map_delta,
        "mean_recall_delta": mean_recall_delta,
        "hybrid_beats_popularity": aggregate_beats,
        "verdict": "hybrid" if aggregate_beats else "popularity",
        "worlds": per_world,
        "caveats": DEMO_WORLD_TUNING_CAVEAT,
    }


def eval_real(
    username: str,
    scrobbles_db_path: str | Path,
    catalog: dict[str, Artist],
    source: ScrobbleSource,
    *,
    k: int = 10,
    train_frac: float = 0.7,
    today: Optional[str] = None,
) -> dict[str, object]:
    """The human-gated, LOCAL-ONLY real-data eval leg (FIX-06).

    Reads the operator's *own* previously-cached scrobbles from
    ``scrobbles_db_path`` (a :class:`pipeline.cache.Cache` SQLite file) — this
    function never fetches anything itself. It returns only an aggregate
    summary (metrics + a date + a play count), never the raw scrobbles, so
    nothing about *what* was played leaves this function.

    This must NEVER be called from CI, ``make eval``, ``make verify``, or
    ``make audit``. ``pipeline.cli``'s ``eval-real`` subcommand (gated behind
    an explicit ``--scrobbles PATH`` argument) and the Makefile's ``eval-real``
    target — deliberately absent from ``verify``/``audit`` — are the only
    sanctioned callers, both intended for a human to run locally.
    """
    from datetime import date as _date

    from pipeline.cache import Cache

    with Cache(scrobbles_db_path) as cache:
        scrobbles = cache.get_scrobbles(username)
    if not scrobbles:
        raise ValueError(
            f"no cached scrobbles for {username!r} at {scrobbles_db_path!r} — "
            "run live ingest first; eval_real never fetches on its own"
        )

    results = evaluate(username, scrobbles, catalog, source, k=k, train_frac=train_frac)
    report = to_report(results)
    return {
        "date": today or _date.today().isoformat(),
        "n": len(scrobbles),
        "k": report["k"],
        "n_positives": report["n_positives"],
        "map_delta": report["map_delta"],
        "recall_delta": report["recall_delta"],
        "lift": report["lift"],
        "hybrid_beats_popularity": report["hybrid_beats_popularity"],
        "verdict": report["verdict"],
        "models": report["models"],
    }
