"""Accessibility gate (mechanical subset): the rendered cards have 0 violations.

The browser-based pa11y/axe run happens in CI via ``make a11y``; this asserts the
static-render contract that pa11y also enforces, so regressions in markup
semantics fail fast in the unit suite too.
"""

from __future__ import annotations

from app.a11y_check import check_html
from app.render import render_cards_html
from recommender.hybrid import recommend


def _html(profile, catalog, source, lens=0.5):
    recs = recommend(profile, catalog, source, k=10, lens_strength=lens)
    return render_cards_html(recs, lens_strength=lens, username="demo")


def test_rendered_dashboard_has_zero_a11y_violations(profile, catalog, source) -> None:
    violations = check_html(_html(profile, catalog, source))
    assert violations == [], violations


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


def test_checker_flags_bad_html() -> None:
    bad = "<html><body><h1>a</h1><h3>skip</h3><table><th>x</th></table></body></html>"
    violations = check_html(bad)
    assert any("lang" in v for v in violations)
    assert any("viewport" in v for v in violations)
    assert any("skip link" in v for v in violations)
    assert any("scope" in v for v in violations)
    assert any("caption" in v for v in violations)
    assert any("jumps" in v for v in violations)
