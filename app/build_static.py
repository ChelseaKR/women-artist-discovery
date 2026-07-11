"""Generate the static HTML artifact that the a11y gate audits.

``make a11y`` runs this to produce ``docs/audits/dashboard.html`` from the demo
world, then checks it with pa11y (if installed) or the built-in
:mod:`app.a11y_check`.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_source
from recommender.hybrid import recommend

from app.render import render_cards_html

DEFAULT_OUT = Path("docs/audits/dashboard.html")


def build(out: Path = DEFAULT_OUT, lens_strength: float = 0.5) -> Path:
    recs = recommend(
        demo_profile(), demo_catalog(), demo_source(), k=10, lens_strength=lens_strength
    )
    html = render_cards_html(recs, lens_strength=lens_strength, username=DEMO_USER)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
