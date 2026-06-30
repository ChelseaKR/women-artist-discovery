"""Core domain models — where the project's hard guardrails live as invariants.

The README guardrails are enforced *here*, in the type system, not merely in tests:

1. Identity is **sourced, never inferred.** A non-``unknown`` gender cannot be
   constructed without at least one citation (:class:`Source`). There is no code
   path that derives gender from a name, voice, image, or genre — and there is no
   :class:`SourceKind` member that represents such a thing.
2. ``unknown`` is **first-class.** It is a real :class:`Gender` member and the
   default for every artist. Downstream code must never penalise it; the re-rank
   layer is boost-only (see :mod:`recommender.rerank`).
3. **"Female-fronted" is band-composition metadata**, kept distinct from any
   individual's gender. It is a *tri-state, sourced* property on
   :class:`BandComposition`, never an inference and never a claim about a person.
4. Every recommendation carries an :class:`Explanation` with non-empty signals,
   an identity basis, and the sources behind that basis.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from typing import Optional


class IdentityError(Exception):
    """Base class for identity-guardrail violations."""


class UnsourcedIdentityError(IdentityError):
    """Raised when a non-unknown identity is constructed without a citation."""


class InferenceForbiddenError(IdentityError):
    """Raised if a forbidden (inferred) basis is ever used for an identity."""


class Gender(enum.Enum):
    """Controlled self-identification vocabulary. ``UNKNOWN`` is first-class.

    These map to *sourced self-identification only*. They are never assigned by
    guessing. ``OTHER`` exists so that a sourced self-identification outside the
    common terms is representable rather than being flattened to ``UNKNOWN``.
    """

    WOMAN = "woman"
    MAN = "man"
    NONBINARY = "nonbinary"
    OTHER = "other"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


#: Genders the values-lens is configured to surface (sourced only). Note this is
#: a *re-rank* concern, not an identity concern: ``UNKNOWN`` is deliberately absent
#: here yet is never penalised — see :mod:`recommender.rerank`.
VALUES_ALIGNED_GENDERS: frozenset[Gender] = frozenset({Gender.WOMAN, Gender.NONBINARY})


class IdentityBasis(enum.Enum):
    """*How* an identity label was established — never *guessed*."""

    SELF_IDENTIFIED = "self-identified"
    BAND_COMPOSITION = "band-composition"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


class SourceKind(enum.Enum):
    """The **only** permitted provenance kinds.

    Crucially, there is no member here for a name, a voice, an image, a genre,
    or any other heuristic. The no-inference guardrail test asserts that this
    enum contains none of those and that the resolver accepts nothing else.
    """

    # --- About an individual's self-identified gender -------------------------
    WIKIDATA_P21 = "wikidata-p21"  # "sex or gender" claim
    MUSICBRAINZ_GENDER = "musicbrainz-gender"  # editorial / self-reported field
    ARTIST_STATEMENT = "artist-statement"  # a cited public self-identification
    # --- About band lineup / role (composition only, NOT individual gender) ---
    DISCOGS_LINEUP = "discogs-lineup"
    MUSICBRAINZ_RELATIONSHIP = "musicbrainz-relationship"

    def __str__(self) -> str:
        return self.value


#: Sources that may establish an *individual's* gender.
INDIVIDUAL_IDENTITY_SOURCES: frozenset[SourceKind] = frozenset(
    {SourceKind.WIKIDATA_P21, SourceKind.MUSICBRAINZ_GENDER, SourceKind.ARTIST_STATEMENT}
)
#: Sources that may establish *band composition / lineup*.
BAND_COMPOSITION_SOURCES: frozenset[SourceKind] = frozenset(
    {SourceKind.DISCOGS_LINEUP, SourceKind.MUSICBRAINZ_RELATIONSHIP, SourceKind.ARTIST_STATEMENT}
)
#: Every permitted source kind. Equal to the enum's members, by construction.
PERMITTED_SOURCES: frozenset[SourceKind] = INDIVIDUAL_IDENTITY_SOURCES | BAND_COMPOSITION_SOURCES


@dataclass(frozen=True)
class Source:
    """A single citation for an identity claim, with a retrieval timestamp.

    The ``retrieved_at`` field gives every label data lineage (Quality §9).
    """

    kind: SourceKind
    citation: str  # stable reference: URL, Wikidata QID, MBID, etc.
    retrieved_at: str  # ISO-8601 date the claim was fetched
    detail: str = ""  # the raw value the source asserted (e.g. "female")

    def __post_init__(self) -> None:
        if not self.citation.strip():
            raise UnsourcedIdentityError("a Source must carry a non-empty citation")
        if self.kind not in PERMITTED_SOURCES:  # pragma: no cover - enum-exhaustive
            raise InferenceForbiddenError(f"{self.kind!r} is not a permitted source")


@dataclass(frozen=True)
class IdentityLabel:
    """An artist's identity as *sourced*. Defaults to first-class ``UNKNOWN``.

    Invariants (checked at construction):

    * A non-``UNKNOWN`` gender requires at least one :class:`Source`.
    * That source must be an *individual-identity* source — a band-composition
      source can never establish a person's gender.
    * A non-``UNKNOWN`` gender's basis must be ``SELF_IDENTIFIED``.
    """

    gender: Gender = Gender.UNKNOWN
    basis: IdentityBasis = IdentityBasis.UNKNOWN
    sources: tuple[Source, ...] = ()
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        if self.gender is Gender.UNKNOWN:
            # Unknown is first-class: no source required, basis must be UNKNOWN.
            if self.basis is not IdentityBasis.UNKNOWN:
                raise IdentityError("unknown gender must carry UNKNOWN basis")
            return
        if not self.sources:
            raise UnsourcedIdentityError(
                f"gender {self.gender} has no source — identity is never inferred"
            )
        if self.basis is not IdentityBasis.SELF_IDENTIFIED:
            raise InferenceForbiddenError("an individual gender must have a SELF_IDENTIFIED basis")
        for src in self.sources:
            if src.kind not in INDIVIDUAL_IDENTITY_SOURCES:
                raise InferenceForbiddenError(
                    f"{src.kind} cannot establish an individual's gender; "
                    "it is a band-composition source"
                )
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise IdentityError("confidence must be in [0, 1]")

    @property
    def is_known(self) -> bool:
        return self.gender is not Gender.UNKNOWN


#: The singleton "we don't know, and that's fine" label.
UNKNOWN_IDENTITY = IdentityLabel()


@dataclass(frozen=True)
class FrontPerson:
    """A sourced member of a band's fronting lineup.

    Their ``identity`` is itself an :class:`IdentityLabel` — sourced or unknown.
    We never collapse a band-level property into a personal gender claim.
    """

    name: str
    role: str  # as stated by the source, e.g. "lead vocals"
    identity: IdentityLabel = field(default_factory=IdentityLabel)


@dataclass(frozen=True)
class BandComposition:
    """Sourced lineup/role info. ``female_fronted`` is tri-state and sourced.

    This is *band-composition metadata*, explicitly not a claim about any
    member's gender. ``female_fronted`` is:

    * ``True``  — there is a sourced front-person whose own sourced identity is a
      woman or nonbinary person;
    * ``None``  — unknown (no sources, or no front-person with a known identity).

    It is **never** ``False`` by inference: the absence of a sourced
    woman/nonbinary front is "unknown", not "male-fronted".
    """

    members_fronting: tuple[FrontPerson, ...] = ()
    sources: tuple[Source, ...] = ()

    def __post_init__(self) -> None:
        for src in self.sources:
            if src.kind not in BAND_COMPOSITION_SOURCES:
                raise InferenceForbiddenError(
                    f"{src.kind} is not a permitted band-composition source"
                )

    @property
    def female_fronted(self) -> Optional[bool]:
        if not self.sources or not self.members_fronting:
            return None
        for person in self.members_fronting:
            if person.identity.gender in VALUES_ALIGNED_GENDERS:
                return True
        return None


@dataclass(frozen=True)
class Artist:
    """An artist/band as known to the system. ``artist_id`` is a stable key."""

    artist_id: str
    name: str
    tags: tuple[str, ...] = ()
    identity: IdentityLabel = field(default_factory=IdentityLabel)
    composition: Optional[BandComposition] = None
    listeners: int = 0  # popularity proxy, for the baseline + debias check
    playcount: int = 0

    @property
    def female_fronted(self) -> Optional[bool]:
        return self.composition.female_fronted if self.composition else None

    @property
    def values_aligned(self) -> bool:
        """True iff *sourced* identity OR *sourced* composition aligns with the lens.

        Unknown returns ``False`` here — but "not aligned" must never translate
        into a penalty; it only means "received no boost". See the re-rank layer.
        """
        if self.identity.gender in VALUES_ALIGNED_GENDERS:
            return True
        return self.female_fronted is True


@dataclass(frozen=True)
class Scrobble:
    """A single play event from listening history."""

    artist_id: str
    artist_name: str
    track: str
    ts: int  # unix seconds


@dataclass(frozen=True)
class ListeningProfile:
    """A user's listening history, reduced to per-artist play weights + tags."""

    username: str
    play_counts: dict[str, int]  # artist_id -> total plays
    artist_names: dict[str, str]  # artist_id -> display name
    tags: dict[str, tuple[str, ...]]  # artist_id -> tags

    @property
    def known_artist_ids(self) -> frozenset[str]:
        return frozenset(self.play_counts)

    def top_artists(self, n: int) -> list[str]:
        """Artist ids by play count, descending, with id as a stable tie-break."""
        return [
            aid for aid, _ in sorted(self.play_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
        ]


@dataclass(frozen=True)
class Signal:
    """One reason a recommendation surfaced (the "why")."""

    kind: str  # "collaborative" | "content" | "rerank" | "popularity"
    detail: str
    weight: float


@dataclass(frozen=True)
class Explanation:
    """The full, human-readable justification attached to every recommendation."""

    signals: tuple[Signal, ...]
    identity_basis: IdentityBasis
    identity_sources: tuple[Source, ...]
    summary: str

    def __post_init__(self) -> None:
        if not self.signals:
            raise ValueError("every recommendation must carry at least one signal")
        if not self.summary.strip():
            raise ValueError("every recommendation must carry a non-empty summary")


@dataclass(frozen=True)
class Recommendation:
    """A scored, explained recommendation. Immutable; re-ranking returns copies."""

    artist: Artist
    base_score: float  # hybrid score before the values lens
    rerank_delta: float  # boost applied by the lens (>= 0, never negative)
    explanation: Explanation
    rank: int = 0

    @property
    def score(self) -> float:
        return self.base_score + self.rerank_delta

    def with_rank(self, rank: int) -> Recommendation:
        return replace(self, rank=rank)
