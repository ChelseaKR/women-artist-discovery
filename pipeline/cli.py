"""Command-line entry point: ``wad eval|recommend|export|refresh`` (demo mode).

Argparse glue over the library; omitted from coverage accounting, but the gate
behaviour of ``wad eval`` (exit codes, regression/fairness blocks) and ``wad
refresh`` is exercised directly by ``tests/test_eval.py`` and
``tests/test_cache_lifecycle.py``. Live mode (a real Last.fm username) requires
``WAD_LASTFM_API_KEY`` in the environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from export.models import ExportFormat
from export.tracklist import recommendations_to_tracks, render
from recommender.eval import check_regression, evaluate, fairness_report, to_report
from recommender.hybrid import recommend
from recommender.why import why_this_artist

from pipeline.cache import DEFAULT_DB_PATH, DEFAULT_HTTP_TTL_DAYS, Cache
from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_scrobbles, demo_source
from pipeline.ingest import refresh_catalog


def _cmd_eval(args: argparse.Namespace) -> int:
    scrobbles, catalog, source = demo_scrobbles(), demo_catalog(), demo_source()
    results = evaluate(DEMO_USER, scrobbles, catalog, source, k=args.k)
    report = to_report(results)
    # FIX-05: computed exposure / rank-fairness metrics, emitted alongside the eval.
    fairness = fairness_report(DEMO_USER, scrobbles, catalog, source, k=args.k)
    report["fairness"] = fairness

    # AIEV-26/27: regression-vs-baseline, not just beats-popularity. A missing
    # baseline file is a warning, not a failure — the first `wad eval` run on a
    # fresh clone (or before docs/audits/eval-baseline.json is ever created)
    # must still pass.
    baseline_path = Path(args.baseline)
    regression: dict[str, object] | None = None
    if baseline_path.is_file():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        regression = check_regression(
            results["hybrid"],
            baseline["metrics"],
            tolerance=baseline.get("tolerance", 0.10),
        )
        report["regression_vs_baseline"] = regression
    else:
        print(f"no baseline at {baseline_path} — skipping regression check", file=sys.stderr)  # noqa: T201

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201

    beat_baseline = bool(report["hybrid_beats_popularity"])
    guarantees = cast("dict[str, object]", fairness["guarantees"])
    unknown_retained = bool(guarantees["unknown_retention_all_lenses"])
    regressed = bool(regression is not None and regression["regressed"])
    if not beat_baseline:
        print("FAIL: hybrid did not beat the popularity baseline", file=sys.stderr)  # noqa: T201
    if not unknown_retained:
        print(  # noqa: T201
            "FAIL: an unknown-identity artist lost score/rank to the values lens "
            f"(unknown-retention < 100%): {guarantees}",
            file=sys.stderr,
        )
    if regressed:
        print(  # noqa: T201
            f"FAIL: hybrid metrics regressed vs docs/audits/eval-baseline.json: {regression}",
            file=sys.stderr,
        )
    return 0 if (beat_baseline and unknown_retained and not regressed) else 1


def _cmd_refresh(args: argparse.Namespace) -> int:
    """FIX-04: force re-enrichment, report identity-label changes, expire stale http cache."""
    from datetime import date

    catalog = demo_catalog()
    if args.artist:
        catalog = {aid: a for aid, a in catalog.items() if aid == args.artist}
        if not catalog:
            print(f"no such artist: {args.artist}", file=sys.stderr)  # noqa: T201
            return 1
    today = date.today().isoformat()
    with Cache(args.db) as cache:
        expired = cache.expire_http_cache(ttl_days=args.ttl_days, now=today)
        changes = refresh_catalog(cache, catalog, fetched_at=today)
    if changes:
        for change in changes:
            print(  # noqa: T201
                f"{change.artist_id}: {change.old.gender} -> {change.new.gender} "
                f"(sources: {len(change.old.sources)} -> {len(change.new.sources)})"
            )
    else:
        print("no identity-label changes")  # noqa: T201
    print(f"expired {expired} stale http-cache row(s)")  # noqa: T201
    return 0


def _cmd_recommend(args: argparse.Namespace) -> int:
    recs = recommend(
        demo_profile(), demo_catalog(), demo_source(), k=args.k, lens_strength=args.lens
    )
    for rec in recs:
        why = why_this_artist(rec)
        print(f"{rec.rank:>2}. {rec.artist.name:<22} score={rec.score:.3f}")  # noqa: T201
        print(f"    why: {why.headline}")  # noqa: T201
        print(f"    identity: {why.identity_statement}")  # noqa: T201
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    recs = recommend(
        demo_profile(), demo_catalog(), demo_source(), k=args.k, lens_strength=args.lens
    )
    tracks = recommendations_to_tracks(recs)
    text = render(tracks, ExportFormat(args.format), playlist_name="Women-Artist Discovery")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")  # noqa: T201
    else:
        print(text)  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wad", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("eval", help="offline eval vs popularity baseline")
    p_eval.add_argument("--k", type=int, default=5)
    p_eval.add_argument("--out", default="docs/audits/eval-report.json")
    p_eval.add_argument(
        "--baseline",
        default="docs/audits/eval-baseline.json",
        help="committed baseline metrics to regression-check against (AIEV-26/27)",
    )
    p_eval.set_defaults(func=_cmd_eval)

    p_rec = sub.add_parser("recommend", help="print demo recommendations")
    p_rec.add_argument("--k", type=int, default=10)
    p_rec.add_argument("--lens", type=float, default=0.5)
    p_rec.set_defaults(func=_cmd_recommend)

    p_exp = sub.add_parser("export", help="export demo recommendations to a portable playlist file")
    p_exp.add_argument(
        "--format", choices=[str(f) for f in ExportFormat], default=str(ExportFormat.TEXT)
    )
    p_exp.add_argument("--k", type=int, default=10)
    p_exp.add_argument("--lens", type=float, default=0.5)
    p_exp.add_argument("--out", default=None, help="write to a file instead of stdout")
    p_exp.set_defaults(func=_cmd_export)

    p_ref = sub.add_parser(
        "refresh", help="re-enrich the local cache, reporting identity-label changes"
    )
    p_ref.add_argument("--db", default=str(DEFAULT_DB_PATH), help="cache database path")
    p_ref.add_argument("--artist", default=None, help="refresh only this artist_id")
    p_ref.add_argument(
        "--ttl-days",
        type=int,
        default=DEFAULT_HTTP_TTL_DAYS,
        help="expire http-cache rows older than this many days",
    )
    p_ref.set_defaults(func=_cmd_refresh)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
