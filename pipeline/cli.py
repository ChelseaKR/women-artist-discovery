"""Command-line entry point: ``wad eval`` and ``wad recommend`` (demo mode).

Thin argparse glue over the library; excluded from coverage. Live mode (a real
Last.fm username) requires ``WAD_LASTFM_API_KEY`` in the environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from export.models import ExportFormat
from export.tracklist import recommendations_to_tracks, render
from recommender.eval import evaluate, to_report
from recommender.hybrid import recommend
from recommender.why import why_this_artist

from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_scrobbles, demo_source
from pipeline.doctor import run_diagnostics
from pipeline.logconfig import configure_logging


def _cmd_eval(args: argparse.Namespace) -> int:
    results = evaluate(DEMO_USER, demo_scrobbles(), demo_catalog(), demo_source(), k=args.k)
    report = to_report(results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201
    if not report["hybrid_beats_popularity"]:
        print("FAIL: hybrid did not beat the popularity baseline", file=sys.stderr)  # noqa: T201
        return 1
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


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = run_diagnostics(check_upstream=args.check_upstream)
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")  # noqa: T201
    print(f"doctor: {'OK' if report.ok else 'FAIL'}")  # noqa: T201
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="wad", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("eval", help="offline eval vs popularity baseline")
    p_eval.add_argument("--k", type=int, default=5)
    p_eval.add_argument("--out", default="docs/audits/eval-report.json")
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

    p_doc = sub.add_parser("doctor", help="diagnose env, data location, and cache health")
    p_doc.add_argument(
        "--check-upstream",
        action="store_true",
        help="also ping the four upstream APIs (opt-in, off by default; makes network calls)",
    )
    p_doc.set_defaults(func=_cmd_doctor)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
