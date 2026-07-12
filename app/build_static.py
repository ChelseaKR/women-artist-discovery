"""Generate the static HTML artifact that the a11y gate audits.

``make a11y`` runs this to produce ``docs/audits/dashboard.html`` (the shipped,
``prefers-color-scheme``-responsive artifact) plus a light-pinned and a
dark-pinned variant, then checks them with pa11y (if installed) or the built-in
:mod:`app.a11y_check`. Auditing both pinned schemes makes the gate
scheme-complete on any machine — a Dark-Mode Mac and light-mode CI check the
same two palettes (BUG-1 / A11Y-03 local-CI divergence fix).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_source
from pipeline.models import Recommendation
from recommender.exposure import observability_panel
from recommender.hybrid import recommend

from app.render import SCHEMES, render_cards_html

DEFAULT_OUT = Path("docs/audits/dashboard.html")
LENS_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)


def build(out: Path = DEFAULT_OUT, lens_strength: float = 0.5, scheme: str = "auto") -> Path:
    profile, catalog, source = demo_profile(), demo_catalog(), demo_source()
    recs_by_lens: dict[float, list[Recommendation]] = {
        lens: recommend(profile, catalog, source, k=10, lens_strength=lens)
        for lens in sorted({*LENS_GRID, lens_strength})
    }
    panel = observability_panel(recs_by_lens, current_lens=lens_strength, k=10)
    html = render_cards_html(
        recs_by_lens[lens_strength],
        lens_strength=lens_strength,
        username=DEMO_USER,
        scheme=scheme,
        exposure_panel=panel,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--scheme",
        choices=SCHEMES,
        default="auto",
        help="auto = responsive to prefers-color-scheme; light/dark pin one palette",
    )
    args = parser.parse_args(argv)
    path = build(out=args.out, scheme=args.scheme)
    print(f"wrote {path} (scheme={args.scheme})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
