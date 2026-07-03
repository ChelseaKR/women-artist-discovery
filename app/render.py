"""Render recommendations to accessible, semantic HTML.

This pure renderer is the single source of truth for the *content* of a why-card.
The Streamlit dashboard shows the same information interactively; this static
output is what the a11y gate (:mod:`app.a11y_check` / pa11y) audits, so the
mechanical WCAG 2.2 AA checks run in CI without a live browser server.

Accessibility decisions baked in here:

* every page has ``lang`` + a viewport meta (zoom/reflow at 320 px),
* a skip link to ``<main>`` and proper landmarks/heading order,
* identity is conveyed as **text**, never colour alone,
* the score "chart" ships with a real ``<table>`` data equivalent.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from typing import cast

from pipeline.models import Recommendation
from recommender.why import WhyThisArtist, why_this_artist


def _identity_line(why: WhyThisArtist) -> str:
    return f"Identity: {escape(why.identity_statement)}"


def _provenance_html(why: WhyThisArtist, aid: str) -> str:
    """Identity provenance: each citation with the *raw value the source asserted*.

    Showing the asserted value (not just a label) is what makes "sourced, never
    inferred" auditable rather than a promise.
    """
    if not why.provenance:
        return '<p class="sources">Sources: none — identity unknown, surfaced on merit.</p>'
    items = "".join(
        f"<li>{escape(p.source_kind)} asserted “{escape(p.asserted_value)}”: "
        f'<a href="{escape(p.citation)}">{escape(p.citation)}</a> '
        f'<span class="retrieved">(retrieved {escape(p.retrieved_at)})</span></li>'
        for p in why.provenance
    )
    return (
        f'<p class="sources" id="src-{aid}">Sources (sourced, never inferred):</p><ul>{items}</ul>'
    )


def _reasons_html(why: WhyThisArtist) -> str:
    items = "".join(f"<li>{escape(r)}</li>" for r in why.reasons)
    return f"<ul>{items}</ul>"


def _card_html(rec: Recommendation) -> str:
    why = why_this_artist(rec)
    basis = escape(str(why.identity_basis))
    aid = escape(rec.artist.artist_id)
    return (
        f'<article class="card" aria-labelledby="h-{aid}">'
        f'<h3 id="h-{aid}">{rec.rank}. {escape(rec.artist.name)}</h3>'
        f'<p class="score">Score: {rec.score:.3f} '
        f"(taste {rec.base_score:.3f} + values lens {rec.rerank_delta:.3f})</p>"
        f'<p class="identity" data-basis="{basis}" data-inferred="false">'
        f"{_identity_line(why)}</p>"
        f"<h4>Why this artist</h4>{_reasons_html(why)}"
        f"{_provenance_html(why, aid)}"
        f'<p class="summary">{escape(rec.explanation.summary)}</p>'
        f"</article>"
    )


def _row_html(r: Recommendation) -> str:
    return (
        f"<tr><td>{r.rank}</td>"
        f'<th scope="row">{escape(r.artist.name)}</th>'
        f"<td>{r.base_score:.3f}</td><td>{r.rerank_delta:.3f}</td>"
        f"<td>{r.score:.3f}</td>"
        f"<td>{escape(str(r.explanation.identity_basis))}</td></tr>"
    )


def _table_html(recs: Sequence[Recommendation]) -> str:
    rows = "".join(_row_html(r) for r in recs)
    return (
        "<table><caption>Recommendation scores (data-table equivalent of "
        "the score chart)</caption><thead><tr>"
        '<th scope="col">Rank</th><th scope="col">Artist</th>'
        '<th scope="col">Taste score</th><th scope="col">Values boost</th>'
        '<th scope="col">Total</th><th scope="col">Identity basis</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _exposure_share_table_html(panel: dict[str, object]) -> str:
    """The primary, table-first equivalent of the exposure-share chart."""
    rows = cast("list[dict[str, object]]", panel["exposure_rows"])
    base_pct = f"{cast(float, panel['base_lens']):.0%}"
    current_pct = f"{cast(float, panel['current_lens']):.0%}"
    body = "".join(
        f'<tr><th scope="row">{escape(str(row["segment"]))}</th>'
        f"<td>{cast(float, row['base_share']):.0%}</td>"
        f"<td>{cast(float, row['current_share']):.0%}</td></tr>"
        for row in rows
    )
    return (
        "<table><caption>Exposure share by identity segment — base lens "
        f"({base_pct}) vs current lens ({current_pct})</caption><thead><tr>"
        '<th scope="col">Identity segment</th>'
        f'<th scope="col">Base lens ({base_pct})</th>'
        f'<th scope="col">Current lens ({current_pct})</th>'
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def _retention_table_html(panel: dict[str, object]) -> str:
    """The unknown-retention curve, table-first (should read 100% throughout)."""
    retention_row = cast("dict[str, object]", panel["retention_row"])
    by_lens = cast("dict[str, float]", retention_row["by_lens"])
    lens_keys = list(by_lens)
    header = "".join(f'<th scope="col">Lens {escape(key)}</th>' for key in lens_keys)
    cells = "".join(f"<td>{by_lens[key]:.0%}</td>" for key in lens_keys)
    segment = escape(str(retention_row["segment"]))
    return (
        "<table><caption>Unknown-identity retention across the lens (pinned "
        "at 100% — the merge-blocking fairness guarantee)</caption><thead><tr>"
        f'<th scope="col">Identity segment</th>{header}'
        f'</tr></thead><tbody><tr><th scope="row">{segment}</th>{cells}</tr>'
        "</tbody></table>"
    )


def _exposure_panel_html(panel: dict[str, object] | None) -> str:
    """The fairness-observability section: table-first, chart optional (omitted).

    ``panel`` is the output of :func:`recommender.exposure.observability_panel`.
    Defaults to nothing rendered so existing callers/tests are unaffected.
    """
    if panel is None:
        return ""
    return (
        "<h2>Fairness observability</h2>"
        "<p>Moving the lens changes exposure shares across identity segments; "
        "unknown-retention stays pinned at 100% — the boost-only lens never "
        "displaces artists with unknown identity from the results.</p>"
        f"{_exposure_share_table_html(panel)}{_retention_table_html(panel)}"
    )


_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; max-width: 70ch; margin: 0 auto; padding: 1rem; }
.card { border: 1px solid; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
.identity { font-weight: 600; }
.identity::before { content: "\\25CF  "; }  /* glyph paired with text, not colour-only */
a:focus, .skip:focus { outline: 3px solid; }
.skip { position: absolute; left: -999px; }
.skip:focus { left: 1rem; top: 1rem; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid; padding: 0.4rem; text-align: left; }
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


def render_cards_html(
    recs: Sequence[Recommendation],
    lens_strength: float,
    username: str = "demo",
    exposure_panel: dict[str, object] | None = None,
) -> str:
    """Render a complete, accessible HTML document for the given recommendations.

    ``exposure_panel`` is the optional output of
    :func:`recommender.exposure.observability_panel` — the fairness
    observability section (table-first). It defaults to ``None`` so existing
    callers render exactly as before.
    """
    cards = "".join(_card_html(r) for r in recs)
    lens_pct = f"{lens_strength:.0%}"
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Women-Artist Discovery — recommendations</title>"
        f"<style>{_STYLE}</style></head><body>"
        '<a class="skip" href="#main">Skip to recommendations</a>'
        "<header><h1>Women-Artist Discovery</h1>"
        f"<p>Recommendations for <strong>{escape(username)}</strong>. "
        f"The values lens is set to <strong>{lens_pct}</strong>: it only ever "
        "<em>boosts</em> artists whose identity is sourced as a woman, nonbinary "
        "person, or a sourced female-fronted band. It never lowers anyone's "
        "score, and artists with unknown identity are surfaced on musical merit "
        "alone.</p></header>"
        '<main id="main">'
        "<h2>Score summary</h2>"
        f"{_table_html(recs)}"
        f"{_exposure_panel_html(exposure_panel)}"
        "<h2>Recommendations</h2>"
        f"{cards}"
        "</main></body></html>"
    )
