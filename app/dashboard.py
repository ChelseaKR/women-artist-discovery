"""Streamlit dashboard: enter a username, get explainable, values-aware picks.

Run with ``make dev`` (``streamlit run app/dashboard.py``). Defaults to the
offline demo world so it works with no API key; set ``WAD_LASTFM_API_KEY`` to
use a real Last.fm username.

Accessibility: the values lens is a labelled, always-visible, explained slider;
identity is shown as text + glyph (never colour alone); the score chart is paired
with a data table; sources render as real links. The committed static render
(:mod:`app.build_static`) carries the same semantics for the automated a11y gate.
"""

from __future__ import annotations

import os

from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_source
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, IdentityBasis, ListeningProfile, Recommendation
from recommender.hybrid import recommend


def _load_demo() -> tuple[ListeningProfile, dict[str, Artist], ScrobbleSource]:
    return demo_profile(), demo_catalog(), demo_source()


def _identity_text(rec: Recommendation) -> str:
    label = rec.artist.identity
    if label.is_known:
        conf = f" · confidence {label.confidence:.0%}" if label.confidence else ""
        return f"● Identity: {label.gender} — self-identified{conf}"
    if rec.artist.female_fronted is True:
        return "● Identity: female-fronted band (sourced lineup) — distinct from member gender"
    return "● Identity: unknown — surfaced on musical similarity alone"


def main() -> None:  # pragma: no cover - exercised via the live Streamlit runtime
    import streamlit as st

    st.set_page_config(page_title="Women-Artist Discovery", layout="centered")
    st.title("Women-Artist Discovery")
    st.write(
        "Discovery with a values lens, done right: identity is **sourced, never "
        "inferred**, and **unknown is first-class** — never down-ranked."
    )

    username = st.text_input("Last.fm username", value=DEMO_USER)
    lens = st.slider(
        "Values lens strength",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05,
        help=(
            "How strongly to boost artists whose identity is sourced as a woman, "
            "nonbinary person, or sourced female-fronted band. The lens only ever "
            "boosts — it never lowers anyone's score, and never penalises unknown."
        ),
    )

    if os.environ.get("WAD_LASTFM_API_KEY") and username != DEMO_USER:
        st.info("Live mode would fetch this user; this demo build uses cached data.")
    profile, catalog, source = _load_demo()
    recs = recommend(profile, catalog, source, k=10, lens_strength=lens)

    st.subheader("Score summary")
    st.table(
        {
            "Rank": [r.rank for r in recs],
            "Artist": [r.artist.name for r in recs],
            "Taste": [round(r.base_score, 3) for r in recs],
            "Values boost": [round(r.rerank_delta, 3) for r in recs],
            "Total": [round(r.score, 3) for r in recs],
            "Identity basis": [str(r.explanation.identity_basis) for r in recs],
        }
    )

    st.subheader("Recommendations")
    for rec in recs:
        with st.container(border=True):
            st.markdown(f"### {rec.rank}. {rec.artist.name}")
            st.caption(
                f"Score {rec.score:.3f} = taste {rec.base_score:.3f} "
                f"+ values lens {rec.rerank_delta:.3f}"
            )
            st.write(_identity_text(rec))
            st.markdown("**Why recommended**")
            for sig in rec.explanation.signals:
                st.markdown(f"- {sig.kind}: {sig.detail}")
            if rec.explanation.identity_basis is not IdentityBasis.UNKNOWN:
                st.markdown("**Sources**")
                for src in rec.explanation.identity_sources:
                    st.markdown(
                        f"- {src.kind}: [{src.citation}]({src.citation}) "
                        f"(retrieved {src.retrieved_at})"
                    )
            else:
                st.caption("Identity unknown — no sources, surfaced on merit.")


if __name__ == "__main__":  # pragma: no cover
    main()
