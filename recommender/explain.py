"""Build the human-readable explanation attached to every recommendation.

Every recommendation must show *why* (the signals), the *identity basis*, and the
*source* of that basis (README + Transparency audit §D). The summary is honest
about unknown: an unknown artist is described as "surfaced on musical similarity
alone", never apologised for and never hidden.
"""

from __future__ import annotations

from pipeline.models import (
    Artist,
    Explanation,
    Gender,
    IdentityBasis,
    Signal,
    Source,
)

from recommender.collaborative import CollabResult
from recommender.content import ContentResult


def _identity_phrase(artist: Artist) -> str:
    label = artist.identity
    if label.gender is not Gender.UNKNOWN:
        conf = f" (confidence {label.confidence:.2f})" if label.confidence else ""
        return f"identifies as {label.gender}{conf}, per {label.basis}"
    if artist.female_fronted is True:
        return "female-fronted band (sourced lineup), distinct from any member's gender"
    return "identity unknown — surfaced on musical similarity alone"


def build_explanation(
    artist: Artist,
    collab: CollabResult,
    content: ContentResult,
    rerank_delta: float,
    lens_strength: float,
) -> Explanation:
    """Assemble signals + identity basis + sources into an :class:`Explanation`."""
    signals: list[Signal] = []

    for c in collab.top_contributors(3):
        signals.append(
            Signal(
                kind="collaborative",
                detail=f"similar to {c.seed_name} ({c.similarity:.0%} match)",
                weight=round(c.similarity * c.seed_weight, 4),
            )
        )
    if content.overlap_tags:
        shown = ", ".join(content.overlap_tags[:4])
        signals.append(
            Signal(
                kind="content",
                detail=f"shared tags: {shown}",
                weight=round(content.score, 4),
            )
        )
    if rerank_delta > 0.0:
        signals.append(
            Signal(
                kind="rerank",
                detail=f"values lens boost (strength {lens_strength:.0%})",
                weight=round(rerank_delta, 4),
            )
        )

    # Guarantee a non-empty "why" even for a thin candidate.
    if not signals:
        signals.append(
            Signal(kind="content", detail="appears in your discovery catalog", weight=0.0)
        )

    # Identity basis + the *actual* citations behind it.
    if artist.identity.gender is not Gender.UNKNOWN:
        basis = IdentityBasis.SELF_IDENTIFIED
        sources: tuple[Source, ...] = artist.identity.sources
    elif artist.female_fronted is True and artist.composition is not None:
        basis = IdentityBasis.BAND_COMPOSITION
        sources = artist.composition.sources
    else:
        basis = IdentityBasis.UNKNOWN
        sources = ()

    summary = f"Recommended because {signals[0].detail}; {_identity_phrase(artist)}."
    return Explanation(
        signals=tuple(signals),
        identity_basis=basis,
        identity_sources=sources,
        summary=summary,
    )
