"""Generate the static HTML artifact that the a11y gate audits.

``make a11y`` runs this to produce ``docs/audits/dashboard.html`` from the demo
world, then checks it with pa11y (if installed) or the built-in
:mod:`app.a11y_check`.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_source
from pipeline.models import Recommendation
from recommender.exposure import observability_panel
from recommender.hybrid import recommend

from app.render import render_cards_html

DEFAULT_OUT = Path("docs/audits/dashboard.html")

#: Fixed lens grid the fairness-observability panel is computed across, mirroring
#: the live dashboard's grid (app/dashboard.py). 0.0 is the panel's base lens —
#: the pure-taste ranking every exposure/retention comparison is measured against.
LENS_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)


def build(out: Path = DEFAULT_OUT, lens_strength: float = 0.5) -> Path:
    profile, catalog, source = demo_profile(), demo_catalog(), demo_source()

    lens_values = sorted({*LENS_GRID, lens_strength})
    recs_by_lens: dict[float, list[Recommendation]] = {
        lens: recommend(profile, catalog, source, k=10, lens_strength=lens) for lens in lens_values
    }
    recs = recs_by_lens[lens_strength]
    panel = observability_panel(recs_by_lens, current_lens=lens_strength, k=10, base_lens=0.0)

    html = render_cards_html(
        recs, lens_strength=lens_strength, username=DEMO_USER, exposure_panel=panel
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
