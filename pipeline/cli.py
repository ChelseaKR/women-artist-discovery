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
from recommender.eval import eval_real, evaluate_worlds
from recommender.hybrid import recommend
from recommender.why import why_this_artist

from pipeline.demo import demo_catalog, demo_profile, demo_source


def _cmd_eval(args: argparse.Namespace) -> int:
    """Multi-world eval (FIX-06): aggregate independent fixture families —
    see ``pipeline.fixtures.ALL_WORLDS`` — instead of grading against the one
    hand-tuned ``pipeline.demo`` world alone.
    """
    report = evaluate_worlds(k=args.k)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201
    if not report["hybrid_beats_popularity"]:
        wins = report["worlds_hybrid_wins"]
        total = report["n_worlds"]
        print(  # noqa: T201
            f"FAIL: hybrid did not beat the popularity baseline on aggregate "
            f"({wins}/{total} worlds won)",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_eval_real(args: argparse.Namespace) -> int:
    """LOCAL-ONLY: the human-gated real-data eval leg (FIX-06).

    Reads the operator's OWN cached scrobbles from ``--scrobbles`` — this
    never fetches anything and is gated behind that explicit path argument, so
    it cannot run by accident. This subcommand must NEVER be invoked from CI,
    ``make verify``, or ``make audit`` — see the Makefile's ``eval-real``
    target, which is deliberately not a dependency of either.
    """
    print(  # noqa: T201
        "NOTE: artist metadata/identity enrichment still comes from the "
        "offline demo catalog — live enrichment clients (FIX-01) have not "
        "landed yet. Only the scrobble history read from --scrobbles is real.",
        file=sys.stderr,
    )
    report = eval_real(args.user, args.scrobbles, demo_catalog(), demo_source(), k=args.k)
    text = json.dumps(report, indent=2)
    print(text)  # noqa: T201
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
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

    p_eval = sub.add_parser(
        "eval", help="offline eval vs popularity baseline, aggregated across fixture worlds"
    )
    p_eval.add_argument("--k", type=int, default=5)
    p_eval.add_argument("--out", default="docs/audits/eval-report.json")
    p_eval.set_defaults(func=_cmd_eval)

    # LOCAL-ONLY (FIX-06): the human-gated real-data eval leg. Gated behind the
    # required --scrobbles path so it can never run implicitly; must never be
    # invoked from CI — see the Makefile's eval-real target and eval_real's
    # docstring in recommender/eval.py.
    p_eval_real = sub.add_parser(
        "eval-real",
        help="LOCAL-ONLY: eval against YOUR cached scrobbles; never run this in CI",
    )
    p_eval_real.add_argument(
        "--user", required=True, help="Last.fm username the cached scrobbles belong to"
    )
    p_eval_real.add_argument(
        "--scrobbles",
        required=True,
        metavar="PATH",
        help=(
            "path to a local pipeline.cache.Cache SQLite file containing YOUR "
            "own cached scrobbles (operator-run only)"
        ),
    )
    p_eval_real.add_argument("--k", type=int, default=10)
    p_eval_real.add_argument(
        "--out", default=None, help="optional path to write the summarized report"
    )
    p_eval_real.set_defaults(func=_cmd_eval_real)

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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
