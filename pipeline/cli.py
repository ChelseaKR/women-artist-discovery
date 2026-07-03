"""Command-line entry point: ``wad eval`` and ``wad recommend`` (demo mode).

Thin argparse glue over the library; excluded from coverage. Live mode (a real
Last.fm username) requires ``WAD_LASTFM_API_KEY`` in the environment.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from export.models import ExportFormat
from export.tracklist import recommendations_to_tracks, render
from recommender.eval import evaluate, to_report
from recommender.hybrid import recommend
from recommender.upstream import upstream_edit_url
from recommender.why import why_this_artist

from pipeline import corrections
from pipeline.cache import DEFAULT_DB_PATH, Cache
from pipeline.demo import (
    DEMO_USER,
    demo_catalog,
    demo_enricher,
    demo_profile,
    demo_scrobbles,
    demo_source,
)
from pipeline.ingest import refresh_catalog


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


def _cmd_refresh(args: argparse.Namespace) -> int:
    """Re-enrich the local cache; report identity changes; reconcile corrections.

    On a first run against an empty cache, seeds it with the demo catalog so
    the command is smoke-testable with no external credentials — the same
    "demo mode" posture as ``recommend``/``export``. A real deployment points
    ``--db`` at a cache already populated by ``wad`` ingest.
    """
    db_path = Path(args.db)
    fetched_at = args.fetched_at or datetime.date.today().isoformat()
    corrections_path = args.corrections or str(corrections.default_path(db_path))
    with Cache(db_path) as cache:
        if not cache.list_artist_ids():
            for artist in demo_catalog().values():
                cache.put_artist(artist, fetched_at=fetched_at)
            print(f"seeded empty cache with {len(cache.list_artist_ids())} demo artists")  # noqa: T201
        changes = refresh_catalog(cache, demo_source(), demo_enricher(), fetched_at=fetched_at)
        for c in changes:
            print(  # noqa: T201
                f"identity change: {c.artist_id} [{c.source_kind}] "
                f"{c.old_value!r} -> {c.new_value!r} (retrieved {c.retrieved_at})"
            )
        reconciled = corrections.reconcile(corrections_path, changes)
        print(  # noqa: T201
            f"refresh complete: {len(changes)} identity change(s), "
            f"{reconciled} pending correction(s) reconciled"
        )
    return 0


def _cmd_corrections(args: argparse.Namespace) -> int:
    path = args.path or str(corrections.default_path(Path(args.db)))
    if getattr(args, "corrections_command", None) == "add":
        edit_url = upstream_edit_url(args.source_kind, args.citation)
        row = corrections.add_correction(
            path,
            artist_id=args.artist,
            source_kind=args.source_kind,
            citation=args.citation,
            current_value=args.current,
            proposed_value=args.proposed,
            note=args.note,
            filed_at=datetime.date.today().isoformat(),
            edit_url=edit_url,
        )
        print(f"filed pending correction for {row.artist_id} ({row.source_kind})")  # noqa: T201
        if row.edit_url:
            print(f"  fix at source: {row.edit_url}")  # noqa: T201
        return 0

    rows = corrections.list_corrections(path)
    if not rows:
        print("no pending corrections")  # noqa: T201
        return 0
    for r in rows:
        print(  # noqa: T201
            f"{r.artist_id} [{r.source_kind}] {r.current_value!r} -> {r.proposed_value!r} "
            f"— filed {r.filed_at}: {r.note}"
        )
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

    p_refresh = sub.add_parser(
        "refresh", help="re-enrich the local cache and reconcile pending corrections"
    )
    p_refresh.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_refresh.add_argument("--fetched-at", default=None, help="lineage date (default: today)")
    p_refresh.add_argument(
        "--corrections", default=None, help="corrections file (default: alongside --db)"
    )
    p_refresh.set_defaults(func=_cmd_refresh)

    p_corr = sub.add_parser("corrections", help="list or file local pending upstream corrections")
    p_corr.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_corr.add_argument("--path", default=None, help="corrections file (default: alongside --db)")
    corr_sub = p_corr.add_subparsers(dest="corrections_command")
    p_corr_add = corr_sub.add_parser("add", help="file a new pending correction")
    p_corr_add.add_argument("--artist", required=True, help="artist_id")
    p_corr_add.add_argument("--source-kind", required=True, help="e.g. wikidata-p21")
    p_corr_add.add_argument("--citation", required=True, help="the source's citation URL")
    p_corr_add.add_argument("--current", default="", help="the asserted value believed wrong")
    p_corr_add.add_argument("--proposed", required=True, help="the value you're correcting it to")
    p_corr_add.add_argument("--note", default="", help="why — kept with the pending row")
    p_corr.set_defaults(func=_cmd_corrections)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
