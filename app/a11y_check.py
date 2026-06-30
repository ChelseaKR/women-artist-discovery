"""A dependency-free, offline checker for the mechanical WCAG 2.2 AA subset.

This is the fallback a11y gate when a browser-based runner (pa11y/axe) is not
available in the environment. It is intentionally conservative — it only asserts
things that are unambiguously checkable from static HTML — and ``make a11y``
prefers pa11y when it is installed. Run as ``python -m app.a11y_check FILE``;
exits non-zero on any violation.
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path


class _A11yParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.violations: list[str] = []
        self.html_lang = False
        self.has_viewport = False
        self.h1_count = 0
        self.heading_levels: list[int] = []
        self.has_main = False
        self.has_skip = False
        self._in_table = False
        self._table_has_caption = False
        self._tables = 0
        self._captions = 0
        self._a_stack: list[bool] = []  # tracks whether current <a> has text
        self._open_a = False
        self._a_text = ""

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        if tag == "html" and attrs.get("lang"):
            self.html_lang = True
        if tag == "meta" and attrs.get("name") == "viewport":
            self.has_viewport = True
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self.heading_levels.append(level)
            if level == 1:
                self.h1_count += 1
        if tag == "main" or attrs.get("role") == "main":
            self.has_main = True
        if tag == "a":
            href = attrs.get("href") or ""
            if href.startswith("#") and ("skip" in (attrs.get("class") or "")):
                self.has_skip = True
            self._open_a = True
            self._a_text = ""
            if not href.strip():
                self.violations.append("anchor with empty href")
        if tag == "img" and not attrs.get("alt") and attrs.get("alt") != "":
            self.violations.append("img without alt attribute")
        if tag == "table":
            self._in_table = True
            self._tables += 1
            self._table_has_caption = False
        if tag == "caption":
            self._captions += 1
            self._table_has_caption = True
        if tag == "th" and not attrs.get("scope"):
            self.violations.append("th without scope attribute")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            if self._open_a and not self._a_text.strip():
                self.violations.append("link with no accessible text")
            self._open_a = False
        if tag == "table":
            if not self._table_has_caption:
                self.violations.append("table without caption")
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._open_a:
            self._a_text += data


def check_html(html: str) -> list[str]:
    """Return a list of accessibility violations (empty == passing)."""
    parser = _A11yParser()
    parser.feed(html)
    v = list(parser.violations)
    if not parser.html_lang:
        v.append("<html> missing lang attribute")
    if not parser.has_viewport:
        v.append("missing viewport meta (zoom/reflow)")
    if parser.h1_count != 1:
        v.append(f"expected exactly one <h1>, found {parser.h1_count}")
    if not parser.has_main:
        v.append("no <main> landmark")
    if not parser.has_skip:
        v.append("no skip link to main content")
    # Heading order: never skip a level going deeper.
    prev = 0
    for level in parser.heading_levels:
        if prev and level > prev + 1:
            v.append(f"heading level jumps from h{prev} to h{level}")
        prev = level
    return v


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m app.a11y_check FILE.html", file=sys.stderr)
        return 2
    html = Path(args[0]).read_text(encoding="utf-8")
    violations = check_html(html)
    if violations:
        print(f"{len(violations)} accessibility violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print("a11y: 0 violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
