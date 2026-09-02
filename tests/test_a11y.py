"""Accessibility gate (mechanical subset): the rendered cards have 0 violations.

The browser-based pa11y/axe run happens in CI via ``make a11y``; this asserts the
static-render contract that pa11y also enforces, so regressions in markup
semantics fail fast in the unit suite too.
"""

from __future__ import annotations

from app.a11y_check import check_html
from app.a11y_check import main as a11y_main
from app.render import render_cards_html
from pipeline.models import Explanation, IdentityBasis, Recommendation, Signal
from recommender.exposure import observability_panel
from recommender.hybrid import recommend


def _html(profile, catalog, source, lens=0.5):
    recs = recommend(profile, catalog, source, k=10, lens_strength=lens)
    return render_cards_html(recs, lens_strength=lens, username="demo")


def _html_with_observability(profile, catalog, source, lens=0.5):
    recs_by_lens = {
        value: recommend(profile, catalog, source, k=10, lens_strength=value)
        for value in {0.0, 0.25, 0.5, 0.75, 1.0, lens}
    }
    panel = observability_panel(recs_by_lens, current_lens=lens, k=10)
    return render_cards_html(
        recs_by_lens[lens], lens_strength=lens, username="demo", exposure_panel=panel
    )


def _wrap_as_recommendation(artist, rank: int = 1) -> Recommendation:
    """Wrap a catalog artist in a minimal Recommendation, honestly carrying its
    actual sourced identity basis/sources — used to exercise a specific
    artist's provenance in isolation, independent of who `recommend()`
    happens to surface for the default demo profile."""
    if artist.identity.is_known:
        basis = IdentityBasis.SELF_IDENTIFIED
        sources = artist.identity.sources
    elif artist.composition is not None and artist.sourced_front_genders:
        basis = IdentityBasis.BAND_COMPOSITION
        sources = artist.composition.sources
    else:
        basis = IdentityBasis.UNKNOWN
        sources = ()
    expl = Explanation(
        signals=(Signal(kind="content", detail="test fixture signal", weight=1.0),),
        identity_basis=basis,
        identity_sources=sources,
        summary=f"test summary for {artist.name}",
    )
    return Recommendation(
        artist=artist, base_score=1.0, rerank_delta=0.0, explanation=expl, rank=rank
    )


def test_rendered_dashboard_has_zero_a11y_violations(profile, catalog, source) -> None:
    violations = check_html(_html(profile, catalog, source))
    assert violations == [], violations


def test_observability_panel_is_table_first_and_accessible(profile, catalog, source) -> None:
    html = _html_with_observability(profile, catalog, source)
    assert check_html(html) == []
    assert "Fairness observability" in html
    assert "exposure share by identity segment" in html
    assert "Rank-protected retention" in html
    # Both rank-protected segments get a row, not just unknown (#68).
    assert '<th scope="row">unknown</th>' in html
    assert '<th scope="row">other</th>' in html
    assert html.count("<table>") >= 3


def test_identity_is_text_not_colour_only(profile, catalog, source) -> None:
    html = _html(profile, catalog, source)
    assert "Identity:" in html
    assert "unknown — surfaced on musical similarity alone" in html


def test_score_chart_has_data_table_equivalent(profile, catalog, source) -> None:
    html = _html(profile, catalog, source)
    assert "<table>" in html and "<caption>" in html
    assert 'scope="col"' in html


def test_sources_render_as_links(profile, catalog, source) -> None:
    html = _html(profile, catalog, source)
    assert 'href="https://' in html


def test_fix_at_source_link_appears_for_individual_identity_sources(catalog) -> None:
    """A sourced individual identity (wikidata/musicbrainz) gets a labelled
    "Fix at source" link — descriptive text, never colour/icon alone."""
    recs = [
        _wrap_as_recommendation(catalog["mitski"], rank=1),  # wikidata-p21 + musicbrainz-gender
        _wrap_as_recommendation(catalog["snail-mail"], rank=2),  # musicbrainz-gender
    ]
    html = render_cards_html(recs, lens_strength=0.5, username="demo")
    assert check_html(html) == []
    assert 'class="fix-at-source"' in html
    assert "Fix at source: correct this wikidata-p21 claim upstream" in html
    assert "Fix at source: correct this musicbrainz-gender claim upstream" in html


def _card(html: str, needle: str) -> str:
    # The score-summary table repeats every artist name before the card list
    # does, so search only within the cards section (after the section
    # heading) to land on the actual <article> card, not the table row.
    cards_start = html.index("<h2>Recommendations</h2>")
    idx = html.index(needle, cards_start)
    end = html.index("</article>", idx)
    return html[idx:end]


def test_fix_at_source_link_absent_for_unknown_identity_card(profile, catalog, source) -> None:
    """ "Mystery Act" (first-class unknown) carries no provenance, so no fix link."""
    html = _html(profile, catalog, source, lens=1.0)
    assert "Mystery Act" in html
    card = _card(html, "Mystery Act")
    assert "none — identity unknown, surfaced on merit" in card
    assert "fix-at-source" not in card


def test_fix_at_source_link_absent_for_band_composition_only_source(
    profile, catalog, source
) -> None:
    """ "boygenius" is sourced only via Discogs lineup — no defined edit surface."""
    html = _html(profile, catalog, source)
    assert "boygenius" in html
    card = _card(html, "boygenius")
    assert "discogs-lineup" in card
    assert "fix-at-source" not in card


def test_checker_flags_bad_html() -> None:
    bad = "<html><body><h1>a</h1><h3>skip</h3><table><th>x</th></table></body></html>"
    violations = check_html(bad)
    assert any("lang" in v for v in violations)
    assert any("viewport" in v for v in violations)
    assert any("skip link" in v for v in violations)
    assert any("scope" in v for v in violations)
    assert any("caption" in v for v in violations)
    assert any("jumps" in v for v in violations)


# --- The fallback gate's own entry point ------------------------------------
#
# `make a11y` prefers pa11y and falls back to `python -m app.a11y_check FILE`
# when it is not installed, which is the ordinary case on a fresh machine. That
# fallback *is* the accessibility gate there, and until this block nothing
# executed its `main()`: not one test called it, and `app/` was outside the
# coverage measurement entirely (`addopts` had no `--cov=app`), so the absence
# did not show up as a gap either. A `main()` that returned 0 unconditionally
# would have made `make a11y` green on every page forever, and the suite would
# have agreed. Three of the checker's own violation detectors — empty `href`,
# missing `alt`, empty link text — and the h1-count check were unexercised for
# the same reason.


def test_checker_flags_a_missing_alt_attribute() -> None:
    assert "img without alt attribute" in check_html('<img src="x.png">')
    # An explicitly empty alt is the correct markup for a decorative image and
    # must not be reported; asserting this is what stops the detector being
    # "flag every img", which would fail the real render and get deleted.
    assert "img without alt attribute" not in check_html('<img src="x.png" alt="">')
    assert "img without alt attribute" not in check_html('<img src="x.png" alt="a chart">')


def test_checker_flags_an_anchor_with_no_href_and_no_text() -> None:
    violations = check_html("<a></a>")
    assert "anchor with empty href" in violations
    assert "link with no accessible text" in violations
    assert "link with no accessible text" not in check_html('<a href="/x">Read more</a>')
    assert "anchor with empty href" not in check_html('<a href="/x">Read more</a>')


def test_checker_flags_the_wrong_number_of_h1s() -> None:
    assert any("found 0" in v for v in check_html("<p>no heading at all</p>"))
    assert any("found 2" in v for v in check_html("<h1>a</h1><h1>b</h1>"))


def test_checker_flags_a_missing_main_landmark() -> None:
    assert "no <main> landmark" in check_html("<h1>a</h1>")
    assert "no <main> landmark" not in check_html("<main><h1>a</h1></main>")
    assert "no <main> landmark" not in check_html('<div role="main"><h1>a</h1></div>')


def test_the_fallback_gate_entry_point_exits_non_zero_on_a_violation(tmp_path) -> None:
    """The check that `make a11y` actually runs when pa11y is absent.

    Asserted in both directions on purpose: a gate only ever shown passing is
    indistinguishable from one that cannot fail.
    """
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body><h1>a</h1></body></html>", encoding="utf-8")
    assert a11y_main([str(bad)]) == 1


def test_the_fallback_gate_entry_point_exits_zero_on_the_real_render(
    tmp_path, profile, catalog, source
) -> None:
    page = tmp_path / "dashboard.html"
    page.write_text(_html(profile, catalog, source), encoding="utf-8")
    assert a11y_main([str(page)]) == 0


def test_the_fallback_gate_entry_point_reports_usage_with_no_argument() -> None:
    assert a11y_main([]) == 2
