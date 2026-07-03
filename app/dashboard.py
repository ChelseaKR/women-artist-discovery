"""Streamlit dashboard: enter a username, get explainable, values-aware picks.

Run with ``make dev`` (``streamlit run app/dashboard.py``). Defaults to the
offline demo world so it works with no API key; set ``WAD_LASTFM_API_KEY`` to
use a real Last.fm username.

Accessibility: the values lens is a labelled, always-visible, explained slider;
identity is shown as text + glyph (never colour alone); the score chart is paired
with a data table; sources render as real links. The committed static render
(:mod:`app.build_static`) carries the same semantics for the automated a11y gate.

Two interactive features sit on top of the core:

* **"Why this artist"** — each card surfaces the shared
  :class:`~recommender.why.WhyThisArtist`: the sourced identity (with provenance,
  never inferred) plus the hybrid + values-lens reasons.
* **Playlist export** — download a portable track list (text/CSV/M3U/JSPF) with no
  account, or connect Spotify (env-configured OAuth) to push a real playlist.
"""

from __future__ import annotations

import os
import secrets

from export.models import ExportError, ExportFormat
from export.spotify import (
    RequestsTransport,
    SpotifyClient,
    SpotifyCredentials,
    SpotifyOAuth,
    export_recommendations,
)
from export.tracklist import recommendations_to_tracks, render
from pipeline.demo import DEMO_USER, demo_catalog, demo_profile, demo_source
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Recommendation
from recommender.hybrid import recommend
from recommender.lens import VALUES_LENS
from recommender.why import why_this_artist


def _load_demo() -> tuple[ListeningProfile, dict[str, Artist], ScrobbleSource]:
    return demo_profile(), demo_catalog(), demo_source()


_FALLBACKS: tuple[tuple[str, ExportFormat, str], ...] = (
    ("Plain text", ExportFormat.TEXT, "text/plain"),
    ("CSV", ExportFormat.CSV, "text/csv"),
    ("M3U playlist", ExportFormat.M3U, "audio/x-mpegurl"),
    ("JSPF (JSON)", ExportFormat.JSPF, "application/json"),
)


def _render_export(recs: list[Recommendation], username: str) -> None:  # pragma: no cover - UI glue
    import streamlit as st

    st.subheader("Export this playlist")
    st.caption(
        "Exports are opt-in and user-initiated — the only data that leaves your "
        "machine, and only when you click. The portable formats need no account."
    )

    tracks = recommendations_to_tracks(recs)
    name = f"Women-Artist Discovery — {username}"
    cols = st.columns(len(_FALLBACKS))
    for col, (label, fmt, mime) in zip(cols, _FALLBACKS, strict=True):
        col.download_button(
            label,
            data=render(tracks, fmt, playlist_name=name),
            file_name=f"women-artist-discovery.{fmt}",
            mime=mime,
        )

    with st.expander("Connect Spotify and push a playlist"):
        try:
            creds = SpotifyCredentials.from_env(os.environ)
        except ExportError as exc:
            st.info(
                f"{exc}. Set WAD_SPOTIFY_CLIENT_ID / _SECRET / _REDIRECT_URI to enable "
                "live Spotify export. The portable formats above work without it."
            )
            return

        oauth = SpotifyOAuth(creds, RequestsTransport())
        if "spotify_state" not in st.session_state:
            st.session_state["spotify_state"] = secrets.token_urlsafe(16)
        auth_url = oauth.authorize_url(st.session_state["spotify_state"])
        st.markdown(
            f"1. [Authorize on Spotify]({auth_url}) and copy the `code` you're redirected to."
        )
        code = st.text_input("2. Paste the authorization code", type="password")
        make_public = st.checkbox("Make the playlist public", value=False)
        if st.button("Create Spotify playlist") and code:
            try:
                token = oauth.exchange_code(code)
                client = SpotifyClient(token, RequestsTransport())
                result = export_recommendations(recs, client, username=username, public=make_public)
            except ExportError as exc:
                st.error(f"Export failed: {exc}")
                return
            st.success(
                f"Created “{result.playlist_name}” with {result.matched_count}/"
                f"{result.track_count} tracks matched."
            )
            if result.playlist_url:
                st.markdown(f"[Open your playlist]({result.playlist_url})")
            if result.unmatched:
                st.caption("No Spotify match found for: " + ", ".join(result.unmatched))


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
    st.caption(f"Active lens: **{VALUES_LENS.name}**")
    with st.expander("What exactly does this lens boost, and why?"):
        st.write(VALUES_LENS.rationale)
        st.caption(VALUES_LENS.harms_note)

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
        why = why_this_artist(rec)
        with st.container(border=True):
            st.markdown(f"### {rec.rank}. {rec.artist.name}")
            st.caption(
                f"Score {rec.score:.3f} = taste {rec.base_score:.3f} "
                f"+ values lens {rec.rerank_delta:.3f}"
            )
            st.write(f"● Identity: {why.identity_statement}")
            st.markdown("**Why this artist**")
            for reason in why.reasons:
                st.markdown(f"- {reason}")
            if why.provenance:
                st.markdown("**Sources** (sourced, never inferred)")
                for p in why.provenance:
                    st.markdown(
                        f"- {p.source_kind} asserted “{p.asserted_value}”: "
                        f"[{p.citation}]({p.citation}) (retrieved {p.retrieved_at})"
                    )
            else:
                st.caption("Identity unknown — no sources, surfaced on merit.")

    _render_export(recs, username)


if __name__ == "__main__":  # pragma: no cover
    main()
