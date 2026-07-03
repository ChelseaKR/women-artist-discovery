"""Command-line entry point: ``wad eval``, ``wad recommend`` (demo mode), etc.

Thin argparse glue over the library; excluded from coverage. Live mode (a real
Last.fm username) requires ``WAD_LASTFM_API_KEY`` in the environment.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from export.models import ExportFormat
from export.tracklist import recommendations_to_tracks, render
from recommender.eval import evaluate, to_report
from recommender.feedback import Feedback
from recommender.hybrid import recommend
from recommender.why import why_this_artist

from pipeline.cache import DEFAULT_DB_PATH, Cache
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
    with Cache(DEFAULT_DB_PATH) as cache:
        feedbacks = cache.load_feedback(DEMO_USER)
    recs = recommend(
        demo_profile(),
        demo_catalog(),
        demo_source(),
        k=args.k,
        lens_strength=args.lens,
        feedbacks=feedbacks,
    )
    for rec in recs:
        why = why_this_artist(rec)
        print(f"{rec.rank:>2}. {rec.artist.name:<22} score={rec.score:.3f}")  # noqa: T201
        print(f"    why: {why.headline}")  # noqa: T201
        print(f"    identity: {why.identity_statement}")  # noqa: T201
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    with Cache(DEFAULT_DB_PATH) as cache:
        feedbacks = cache.load_feedback(DEMO_USER)
    recs = recommend(
        demo_profile(),
        demo_catalog(),
        demo_source(),
        k=args.k,
        lens_strength=args.lens,
        feedbacks=feedbacks,
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


def _cmd_feedback(args: argparse.Namespace) -> int:
    """Record one thumbs vote on an artist — tunes future ``recommend``/``export``."""
    vote = 1 if args.up else -1
    fb = Feedback(username=args.user, artist_id=args.artist, vote=vote, ts=int(time.time()))
    with Cache(DEFAULT_DB_PATH) as cache:
        cache.record_feedback(fb, fetched_at=time.strftime("%Y-%m-%d", time.gmtime()))
    direction = "up" if vote == 1 else "down"
    print(f"recorded thumbs-{direction} for {args.artist} ({args.user})")  # noqa: T201
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

    p_exp = sub.add_parser("export", help="export demo recommendations to a portable playlist file")
    p_exp.add_argument(
        "--format", choices=[str(f) for f in ExportFormat], default=str(ExportFormat.TEXT)
    )
    p_exp.add_argument("--k", type=int, default=10)
    p_exp.add_argument("--lens", type=float, default=0.5)
    p_exp.add_argument("--out", default=None, help="write to a file instead of stdout")
    p_exp.set_defaults(func=_cmd_export)

    p_fb = sub.add_parser("feedback", help="record a thumbs vote to tune future rankings")
    p_fb.add_argument("--artist", required=True, help="artist_id to vote on")
    p_fb.add_argument("--user", default=DEMO_USER, help="username the vote is recorded under")
    vote_group = p_fb.add_mutually_exclusive_group(required=True)
    vote_group.add_argument("--up", action="store_true", help="thumbs-up (boost this artist)")
    vote_group.add_argument("--down", action="store_true", help="thumbs-down (lower this artist)")
    p_fb.set_defaults(func=_cmd_feedback)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
