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
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from app.render import render_cards_html
from export.models import ExportFormat
from export.tracklist import recommendations_to_tracks, render
from recommender.eval import check_regression, evaluate, fairness_report, to_report
from recommender.hybrid import recommend
from recommender.upstream import upstream_edit_url
from recommender.why import why_this_artist

from pipeline import corrections as pending_corrections
from pipeline.cache import DEFAULT_DB_PATH, DEFAULT_HTTP_TTL_DAYS, Cache
from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_scrobbles, demo_source
from pipeline.doctor import run_diagnostics
from pipeline.identity import IdentityEvidence
from pipeline.ingest import diff_identity_labels, refresh_catalog
from pipeline.logconfig import configure_logging
from pipeline.models import SourceKind, UnsourcedIdentityError


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
    source_changes = [
        source_change
        for change in changes
        for source_change in diff_identity_labels(change.artist_id, change.old, change.new)
    ]
    pending_path = getattr(args, "pending_corrections", None) or pending_corrections.default_path(
        args.db
    )
    reconciled = pending_corrections.reconcile(pending_path, source_changes)
    if changes:
        for change in changes:
            print(  # noqa: T201
                f"{change.artist_id}: {change.old.gender} -> {change.new.gender} "
                f"(sources: {len(change.old.sources)} -> {len(change.new.sources)})"
            )
    else:
        print("no identity-label changes")  # noqa: T201
    print(f"expired {expired} stale http-cache row(s)")  # noqa: T201
    print(f"reconciled {reconciled} pending upstream correction(s)")  # noqa: T201
    return 0


def _cmd_corrections(args: argparse.Namespace) -> int:
    """List the local corrections ledger, or add one (citation required)."""
    with Cache(args.db) as cache:
        if args.artist or args.value or args.citation:
            if not (args.artist and args.value and args.citation):
                print(  # noqa: T201
                    "error: adding a correction requires --artist, --value, and --citation",
                    file=sys.stderr,
                )
                return 1
            today = datetime.now(timezone.utc).date().isoformat()
            evidence = IdentityEvidence(
                kind=SourceKind.ARTIST_STATEMENT,
                value=args.value,
                citation=args.citation,
                retrieved_at=args.retrieved_at or today,
            )
            try:
                cache.put_correction(args.artist, evidence, entered_at=today)
            except UnsourcedIdentityError as exc:
                print(f"error: {exc}", file=sys.stderr)  # noqa: T201
                return 1
            print(  # noqa: T201
                f"recorded correction for {args.artist}: {args.value!r} ({args.citation})"
            )
            return 0
        corrections = cache.list_corrections()
        if not corrections:
            print("no corrections recorded")  # noqa: T201
            return 0
        for artist_id, evidence, entered_at in corrections:
            print(  # noqa: T201
                f"{artist_id}: {evidence.value!r} — {evidence.citation} "
                f"(retrieved {evidence.retrieved_at}, entered {entered_at})"
            )
    return 0


def _cmd_pending_corrections(args: argparse.Namespace) -> int:
    """List or file human upstream edits awaiting a future refresh."""
    path = args.path or str(pending_corrections.default_path(Path(args.db)))
    if args.pending_command == "add":
        edit_url = upstream_edit_url(args.source_kind, args.citation)
        row = pending_corrections.add_correction(
            path,
            artist_id=args.artist,
            source_kind=args.source_kind,
            citation=args.citation,
            current_value=args.current,
            proposed_value=args.proposed,
            note=args.note,
            filed_at=datetime.now(timezone.utc).date().isoformat(),
            edit_url=edit_url,
        )
        print(f"filed pending correction for {row.artist_id} ({row.source_kind})")  # noqa: T201
        if row.edit_url:
            print(f"  fix at source: {row.edit_url}")  # noqa: T201
        return 0
    rows = pending_corrections.list_corrections(path)
    if not rows:
        print("no pending corrections")  # noqa: T201
        return 0
    for row in rows:
        print(  # noqa: T201
            f"{row.artist_id} [{row.source_kind}] {row.current_value!r} -> "
            f"{row.proposed_value!r} — filed {row.filed_at}: {row.note}"
        )
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
        print(f"    rank shift: {why.rank_shift}")  # noqa: T201
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


def _cmd_report(args: argparse.Namespace) -> int:
    recs = recommend(
        demo_profile(), demo_catalog(), demo_source(), k=args.k, lens_strength=args.lens
    )
    html = render_cards_html(recs, lens_strength=args.lens, username=DEMO_USER)
    privacy_footer = (
        "<footer><p><strong>Privacy note:</strong> this report contains listening "
        "taste and recommendation data. Share it only with people you intend to.</p></footer>"
    )
    html = html.replace("</body>", f"{privacy_footer}</body>")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")  # noqa: T201
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

    p_report = sub.add_parser(
        "report", help="write a self-contained, accessible HTML discovery report"
    )
    p_report.add_argument("--k", type=int, default=10)
    p_report.add_argument("--lens", type=float, default=0.5)
    p_report.add_argument("--out", default="my-discoveries.html")
    p_report.set_defaults(func=_cmd_report)

    p_doctor = sub.add_parser("doctor", help="diagnose env, data location, and cache health")
    p_doctor.add_argument(
        "--check-upstream",
        action="store_true",
        help="also probe upstream APIs (opt-in; makes network calls)",
    )
    p_doctor.set_defaults(func=_cmd_doctor)

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
    p_ref.add_argument(
        "--pending-corrections",
        default=None,
        help="pending upstream corrections file to reconcile",
    )
    p_ref.set_defaults(func=_cmd_refresh)

    p_corr = sub.add_parser(
        "corrections", help="list the local corrections ledger, or add one (FIX-10)"
    )
    p_corr.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_corr.add_argument("--artist", default=None, help="artist_id to correct")
    p_corr.add_argument("--value", default=None, help="asserted gender value, e.g. 'woman'")
    p_corr.add_argument("--citation", default=None, help="citation (required to add)")
    p_corr.add_argument("--retrieved-at", default=None, help="ISO date; defaults to today")
    p_corr.set_defaults(func=_cmd_corrections)

    p_pending = sub.add_parser(
        "pending-corrections", help="list or file pending human upstream edits (EXP-05)"
    )
    p_pending.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_pending.add_argument("--path", default=None, help="pending JSON file (default: beside --db)")
    pending_sub = p_pending.add_subparsers(dest="pending_command")
    p_pending_add = pending_sub.add_parser("add", help="file a pending upstream correction")
    p_pending_add.add_argument("--artist", required=True)
    p_pending_add.add_argument("--source-kind", required=True)
    p_pending_add.add_argument("--citation", required=True)
    p_pending_add.add_argument("--current", default="")
    p_pending_add.add_argument("--proposed", required=True)
    p_pending_add.add_argument("--note", default="")
    p_pending.set_defaults(func=_cmd_pending_corrections)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
