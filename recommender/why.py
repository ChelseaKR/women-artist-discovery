"""'Why this artist' — one honest, render-agnostic explanation per recommendation.

Every recommendation already carries an :class:`~pipeline.models.Explanation`
(signals + identity basis + sources). This module turns that into a single,
structured, *presentation-ready* object the dashboard, the static HTML renderer,
the CLI, and the playlist export can all share — so the identity wording and its
provenance are written **once**, not re-derived (and subtly diverged) in three UIs.

Two guarantees are made explicit in the output itself, not just in a comment:

* **Sourced, never inferred.** :class:`WhyThisArtist.inferred` is hard-coded
  ``False`` and every shown identity claim carries its citation, the *raw value
  the source asserted*, and the date it was retrieved.
* **Unknown is first-class.** An artist with no sourced identity is described as
  "surfaced on musical similarity alone" — a normal answer, never an apology and
  never a guess.

A third guarantee, added for FIX-10: **disagreement is surfaced, not hidden.**
When permitted sources disagree about an individual's gender, the resolver
still reports its highest-priority pick, but ``WhyThisArtist.conflict_note``
names every disagreeing source and what it asserted — worded neutrally, never
as an apology or a guess at who's "right".
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.models import (
    Artist,
    Gender,
    IdentityBasis,
    IdentityLabel,
    Recommendation,
    Source,
    SourceKind,
)


@dataclass(frozen=True)
class ProvenanceItem:
    """One citation behind an identity claim, made fully transparent.

    Mirrors a :class:`~pipeline.models.Source` but flattened for display: the
    ``asserted_value`` is the *raw* thing the source said (e.g. ``"female"``,
    ``"Q6581072"``) so a reader can audit the claim, not just trust the label.
    """

    source_kind: str
    asserted_value: str
    citation: str
    retrieved_at: str
    #: True when this citation is a locally-entered correction (FIX-10) rather
    #: than an upstream-fetched claim — surfaced distinctly so a reader can
    #: tell "we were told this by the artist/operator, with a citation" apart
    #: from "an external database asserted this".
    is_local_correction: bool = False

    @classmethod
    def from_source(cls, source: Source) -> ProvenanceItem:
        return cls(
            source_kind=str(source.kind),
            asserted_value=source.detail,
            citation=source.citation,
            retrieved_at=source.retrieved_at,
            is_local_correction=source.is_local_correction,
        )


@dataclass(frozen=True)
class WhyThisArtist:
    """The complete, honest justification for one recommendation.

    * ``headline`` — the single strongest reason, for a glanceable summary.
    * ``reasons`` — every "why recommended" signal, as readable lines.
    * ``identity_statement`` — the sourced identity (or the first-class unknown).
    * ``identity_basis`` — *how* the identity was established (never "inferred").
    * ``provenance`` — the citations behind the identity claim (empty if unknown).
    * ``inferred`` — always ``False``; identity in this system is never guessed.
    * ``conflict_note`` — non-empty, neutral wording of a source disagreement
      (FIX-10); empty string when sources agree (or identity is unknown).
    """

    artist_name: str
    headline: str
    reasons: tuple[str, ...]
    identity_statement: str
    identity_basis: IdentityBasis
    provenance: tuple[ProvenanceItem, ...]
    inferred: bool = False
    conflict_note: str = ""
    rank_shift: str = "the values lens did not change this pick's position"

    @property
    def identity_is_known(self) -> bool:
        return self.identity_basis is not IdentityBasis.UNKNOWN

    def to_text(self) -> str:
        """A plain-text block suitable for a CLI or an export comment."""
        lines = [
            f"Why {self.artist_name}: {self.headline}",
            f"  Identity: {self.identity_statement}",
            f"  Rank shift: {self.rank_shift}",
        ]
        if self.conflict_note:
            lines.append(f"  {self.conflict_note}")
        if self.reasons:
            lines.append("  Why recommended:")
            lines.extend(f"    - {reason}" for reason in self.reasons)
        if self.provenance:
            lines.append("  Sources (sourced, never inferred):")
            lines.extend(
                f"    - {p.source_kind} asserted {p.asserted_value!r} "
                f"({p.citation}, retrieved {p.retrieved_at})"
                for p in self.provenance
            )
        else:
            lines.append("  Sources: none — identity unknown, surfaced on merit.")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """A Markdown block (used by the CLI and any Markdown-aware surface)."""
        parts = [
            f"**Why {self.artist_name}** — {self.headline}",
            "",
            f"_Identity:_ {self.identity_statement}",
            f"_Rank shift:_ {self.rank_shift}",
        ]
        if self.conflict_note:
            parts.append("")
            parts.append(f"_{self.conflict_note}_")
        if self.reasons:
            parts.append("")
            parts.append("**Why recommended**")
            parts.extend(f"- {reason}" for reason in self.reasons)
        if self.provenance:
            parts.append("")
            parts.append("**Sources** (sourced, never inferred)")
            parts.extend(
                f"- {p.source_kind} asserted `{p.asserted_value}` — "
                f"[{p.citation}]({p.citation}) (retrieved {p.retrieved_at})"
                for p in self.provenance
            )
        else:
            parts.append("")
            parts.append("_Sources: none — identity unknown, surfaced on merit._")
        return "\n".join(parts)


def _confidence_tier(label: IdentityLabel) -> str:
    """Describe the strongest cited source without interpreting its score."""
    source_kinds = {source.kind for source in label.sources}
    if SourceKind.ARTIST_STATEMENT in source_kinds:
        return "directly stated by the artist"
    if SourceKind.WIKIDATA_P21 in source_kinds:
        return "recorded in Wikidata"
    if SourceKind.MUSICBRAINZ_GENDER in source_kinds:
        return "editorial database entry"
    return "cited source"


def artist_identity_phrase(artist: Artist) -> str:
    """The single sourced-or-unknown identity sentence, written in one place.

    Re-used by the explanation summary, the dashboard, the HTML renderer, and the
    export so the phrasing never drifts. Honest about unknown; never inferred.
    """
    label = artist.identity
    if label.gender is not Gender.UNKNOWN:
        tier = _confidence_tier(label)
        suffix = f" ({tier})" if tier else ""
        return f"{label.gender}, self-identified{suffix}"
    if artist.female_fronted is True:
        return "female-fronted band (sourced lineup), distinct from any member's gender"
    return "unknown — surfaced on musical similarity alone"


def identity_statement(rec: Recommendation) -> str:
    """Identity sentence for a whole recommendation (delegates to the artist phrase)."""
    return artist_identity_phrase(rec.artist)


def conflict_note(artist: Artist) -> str:
    """A respectful, neutral note when permitted sources disagreed (FIX-10).

    Empty string when there is no conflict. Phrasing states what each source
    asserted plus its retrieval date — never an apology, never a guess at
    which source is "right".
    """
    label = artist.identity
    if not label.conflict:
        return ""
    claims = "; ".join(
        f"{src.kind} asserted {src.detail!r} (retrieved {src.retrieved_at})"
        for src in label.conflicting_claims
    )
    return f"Sources disagree: {claims}"


def _reason_line(kind: str, detail: str) -> str:
    return f"{kind}: {detail}"


def rank_shift_statement(rank: int, base_rank: int) -> str:
    """Explain lens movement against the pure-taste counterfactual."""
    if base_rank == 0 or rank == base_rank:
        return "the values lens did not change this pick's position"
    return f"the values lens moved this pick from #{base_rank} to #{rank}"


def why_this_artist(rec: Recommendation) -> WhyThisArtist:
    """Build the shared, transparent 'why this artist' view for a recommendation."""
    expl = rec.explanation
    reasons = tuple(_reason_line(s.kind, s.detail) for s in expl.signals)
    headline = expl.signals[0].detail if expl.signals else "in your discovery catalog"
    provenance = tuple(ProvenanceItem.from_source(s) for s in expl.identity_sources)
    return WhyThisArtist(
        artist_name=rec.artist.name,
        headline=headline,
        reasons=reasons,
        identity_statement=identity_statement(rec),
        identity_basis=expl.identity_basis,
        provenance=provenance,
        inferred=False,
        conflict_note=conflict_note(rec.artist),
        rank_shift=rank_shift_statement(rec.rank, rec.base_rank),
    )
