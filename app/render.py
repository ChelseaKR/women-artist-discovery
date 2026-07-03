"""Render recommendations to accessible, semantic HTML.

This pure renderer is the single source of truth for the *content* of a why-card.
The Streamlit dashboard shows the same information interactively; this static
output is what the a11y gate (:mod:`app.a11y_check` / pa11y) audits, so the
mechanical WCAG 2.2 AA checks run in CI without a live browser server.

Accessibility decisions baked in here:

* every page has ``lang`` + a viewport meta (zoom/reflow at 320 px),
* a skip link to ``<main>`` and proper landmarks/heading order,
* identity is conveyed as **text**, never colour alone,
* the score "chart" ships with a real ``<table>`` data equivalent,
* a "Fix at source" link, where one exists, is a labelled text link — never a
  bare icon or colour cue (EXP-05).
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from pipeline.models import Recommendation
from recommender.upstream import upstream_edit_url
from recommender.why import ProvenanceItem, WhyThisArtist, why_this_artist


def _identity_line(why: WhyThisArtist) -> str:
    return f"Identity: {escape(why.identity_statement)}"


def _fix_at_source_link(p: ProvenanceItem) -> str:
    """A labelled deep link to the upstream edit UI, or "" if none applies.

    Only offered when :func:`upstream_edit_url` can build a real edit link
    from this citation (sourced-only, no guessing); the link text itself
    names the action so it never relies on an icon or colour alone (a11y).
    """
    edit_url = upstream_edit_url(p.source_kind, p.citation)
    if edit_url is None:
        return ""
    return (
        f' <a class="fix-at-source" href="{escape(edit_url)}">'
        f"Fix at source: correct this {escape(p.source_kind)} claim upstream</a>"
    )


def _provenance_html(why: WhyThisArtist, aid: str) -> str:
    """Identity provenance: each citation with the *raw value the source asserted*.

    Showing the asserted value (not just a label) is what makes "sourced, never
    inferred" auditable rather than a promise. Where the citation resolves to a
    known upstream edit surface, a "Fix at source" link is appended so a wrong
    or stale claim can be corrected at its origin (EXP-05).
    """
    if not why.provenance:
        return '<p class="sources">Sources: none — identity unknown, surfaced on merit.</p>'
    items = "".join(
        f"<li>{escape(p.source_kind)} asserted “{escape(p.asserted_value)}”: "
        f'<a href="{escape(p.citation)}">{escape(p.citation)}</a> '
        f'<span class="retrieved">(retrieved {escape(p.retrieved_at)})</span>'
        f"{_fix_at_source_link(p)}</li>"
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
    recs: Sequence[Recommendation], lens_strength: float, username: str = "demo"
) -> str:
    """Render a complete, accessible HTML document for the given recommendations."""
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
        "<h2>Recommendations</h2>"
        f"{cards}"
        "</main></body></html>"
    )
