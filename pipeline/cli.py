"""Command-line entry point: ``wad eval`` and ``wad recommend`` (demo mode).

Thin argparse glue over the library; excluded from coverage. Live mode (a real
Last.fm username) requires ``WAD_LASTFM_API_KEY`` in the environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from recommender.eval import evaluate, to_report
from recommender.hybrid import recommend

from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_scrobbles, demo_source


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
        print(f"{rec.rank:>2}. {rec.artist.name:<22} score={rec.score:.3f}")  # noqa: T201
        print(f"    {rec.explanation.summary}")  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
