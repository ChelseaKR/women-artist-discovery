"""Scaling benchmark for the scoring path (FIX-13).

Generates a synthetic ~5k-candidate-artist catalog and a ~50k-scrobble
listening profile via a *seeded* :class:`random.Random`, so the synthetic
world is reproducible run-to-run. That randomness is confined entirely to
world generation — the scored path (``collaborative_scores``,
``content_scores``, ``recommend``) never consults the RNG, so this script
cannot perturb ``tests/test_reproducibility.py``'s byte-stable snapshots.

Usage::

    python scripts/bench.py
    make bench

Prints p50/p95 wall-clock for ``collaborative_scores``, ``content_scores``,
and the full ``recommend()`` path. Exits non-zero if the end-to-end p95
misses the "excellent looks like" target of < 2s (FIX-13).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from pipeline.ingest import build_profile
from pipeline.lastfm import FixtureLastfm
from pipeline.models import Artist, ListeningProfile, Scrobble
from recommender.collaborative import collaborative_scores
from recommender.content import content_scores
from recommender.hybrid import recommend

SEED = 20260703
NUM_KNOWN = 200  # artists the synthetic listener already knows
NUM_CANDIDATES = 5_000  # unheard candidate artists in the catalog
TOTAL_SCROBBLES = 50_000  # total play events, distributed across known artists
TAG_POOL_SIZE = 150
TAGS_PER_ARTIST = (3, 6)  # inclusive range
EDGES_PER_KNOWN_ARTIST = (20, 60)  # similar-artist fan-out per seed, inclusive range
ITERATIONS = 20
RECOMMEND_TARGET_SECONDS = 2.0  # FIX-13 "excellent looks like" bar


def _random_tags(rng: random.Random, pool: list[str]) -> tuple[str, ...]:
    n = rng.randint(*TAGS_PER_ARTIST)
    return tuple(sorted(rng.sample(pool, n)))


def _distribute(total: int, weights: list[float]) -> list[int]:
    """Split ``total`` across ``weights`` (proportionally, remainder-safe)."""
    weight_sum = sum(weights) or 1.0
    counts: list[int] = []
    remaining = total
    for i, w in enumerate(weights):
        left = len(weights) - i - 1
        if left == 0:
            count = remaining
        else:
            count = max(1, round(total * w / weight_sum))
            count = min(count, remaining - left)
        counts.append(count)
        remaining -= count
    return counts


def _generate_scrobbles(rng: random.Random, known_ids: list[str], total: int) -> list[Scrobble]:
    """A skewed (few heavy-rotation artists) synthetic scrobble history."""
    weights = [rng.random() ** 2 for _ in known_ids]
    counts = _distribute(total, weights)
    scrobbles: list[Scrobble] = []
    ts = 1_700_000_000
    for artist_id, count in zip(known_ids, counts, strict=True):
        for _ in range(count):
            scrobbles.append(
                Scrobble(
                    artist_id=artist_id, artist_name=artist_id, track=f"{artist_id}-track", ts=ts
                )
            )
            ts += 1
    return scrobbles


def build_world(
    seed: int = SEED,
) -> tuple[ListeningProfile, dict[str, Artist], FixtureLastfm]:
    """Build a deterministic (seeded) synthetic profile, catalog, and source.

    All randomness lives here, in world generation. Nothing downstream in the
    scoring path consumes ``rng`` — that is what keeps ``make bench`` from
    ever being able to disturb the reproducibility snapshots.
    """
    rng = random.Random(seed)  # noqa: S311 - world-generation only, not scored/security-sensitive
    tag_pool = [f"tag-{i}" for i in range(TAG_POOL_SIZE)]

    known_ids = [f"known-{i}" for i in range(NUM_KNOWN)]
    candidate_ids = [f"cand-{i}" for i in range(NUM_CANDIDATES)]

    tags_by_artist: dict[str, tuple[str, ...]] = {}
    catalog: dict[str, Artist] = {}
    for artist_id in known_ids + candidate_ids:
        tags = _random_tags(rng, tag_pool)
        tags_by_artist[artist_id] = tags
        catalog[artist_id] = Artist(
            artist_id=artist_id,
            name=artist_id,
            tags=tags,
            listeners=rng.randint(1_000, 5_000_000),
        )

    scrobbles = _generate_scrobbles(rng, known_ids, TOTAL_SCROBBLES)
    raw_profile = build_profile("bench-user", scrobbles)
    profile = ListeningProfile(
        username=raw_profile.username,
        play_counts=raw_profile.play_counts,
        artist_names=raw_profile.artist_names,
        tags={aid: tags_by_artist[aid] for aid in raw_profile.play_counts},
    )

    # Similar-artist graph: each known artist links to a random slice of candidates.
    similar: dict[str, list[tuple[str, float]]] = {}
    for artist_id in known_ids:
        n_edges = rng.randint(*EDGES_PER_KNOWN_ARTIST)
        targets = rng.sample(candidate_ids, min(n_edges, len(candidate_ids)))
        similar[artist_id] = [(t, round(rng.uniform(0.1, 1.0), 4)) for t in targets]

    source = FixtureLastfm(scrobbles={}, tags=tags_by_artist, similar=similar)
    return profile, catalog, source


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _time_calls[T](fn: Callable[[], T], iterations: int) -> list[float]:
    timings: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        timings.append(time.perf_counter() - start)
    timings.sort()
    return timings


def _report(label: str, timings: list[float]) -> tuple[float, float]:
    p50 = _percentile(timings, 0.50)
    p95 = _percentile(timings, 0.95)
    print(  # noqa: T201
        f"  {label:24s} p50={p50 * 1000:8.2f} ms   p95={p95 * 1000:8.2f} ms   "
        f"(min={timings[0] * 1000:.2f} ms, max={timings[-1] * 1000:.2f} ms, n={len(timings)})"
    )
    return p50, p95


def main() -> None:
    print(  # noqa: T201
        f"Building synthetic world: {NUM_KNOWN} known + {NUM_CANDIDATES} candidate artists, "
        f"{TOTAL_SCROBBLES} scrobbles (seed={SEED})..."
    )
    profile, catalog, source = build_world()
    candidates = {aid for aid in catalog if aid not in profile.known_artist_ids}
    total_plays = sum(profile.play_counts.values())
    print(  # noqa: T201
        f"World built: {len(catalog)} catalog artists, {len(profile.play_counts)} known "
        f"({total_plays} plays), {len(candidates)} candidates.\n"
    )

    print(f"Timing over {ITERATIONS} iterations each:\n")  # noqa: T201
    collab_timings = _time_calls(lambda: collaborative_scores(profile, source), ITERATIONS)
    content_timings = _time_calls(lambda: content_scores(profile, catalog, candidates), ITERATIONS)
    recommend_timings = _time_calls(
        lambda: recommend(profile, catalog, source, k=20, lens_strength=0.5), ITERATIONS
    )

    _report("collaborative_scores", collab_timings)
    _report("content_scores", content_timings)
    _, recommend_p95 = _report("recommend (end-to-end)", recommend_timings)

    status = "OK" if recommend_p95 < RECOMMEND_TARGET_SECONDS else "OVER TARGET"
    print(  # noqa: T201
        f"\nrecommend() p95 = {recommend_p95 * 1000:.1f} ms "
        f"(target: < {RECOMMEND_TARGET_SECONDS * 1000:.0f} ms)  [{status}]"
    )
    if recommend_p95 >= RECOMMEND_TARGET_SECONDS:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
