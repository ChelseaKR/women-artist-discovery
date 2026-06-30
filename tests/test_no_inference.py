"""THE guardrail test — written first, the centrepiece of the project.

The hard rule (README): *never infer an artist's gender or identity from name,
voice, image, genre, or any heuristic.* This test proves the inference path does
not exist, three ways:

1. **Vocabulary** — the permitted source kinds contain nothing name/voice/
   image/genre-derived, and there is no ``IdentityBasis`` for "inferred".
2. **Structure** — the resolver's inputs (``IdentityEvidence``) expose no name,
   image, audio, or genre field; its signature takes nothing forbidden.
3. **Code** — an AST scan of the resolver's own functions proves they never read
   a forbidden attribute (``genre``, ``tags``, ``voice``, ``image`` …).

Plus a behavioural proof: an artist with a feminine-coded name and a
"female vocalists" tag, but no identity evidence, resolves to UNKNOWN.

Mapped to the merge-blocking metric: *Inferred identity labels = 0*.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from pipeline import identity
from pipeline.identity import IdentityEvidence, resolve_identity
from pipeline.models import (
    PERMITTED_SOURCES,
    Artist,
    Gender,
    IdentityBasis,
    SourceKind,
)

FORBIDDEN_TOKENS = frozenset(
    {
        "name",
        "voice",
        "vocal",
        "image",
        "photo",
        "picture",
        "face",
        "genre",
        "sound",
        "audio",
        "appearance",
        "pitch",
        "timbre",
        "guess",
        "infer",
        "predict",
        "heuristic",
    }
)

RESOLVER_FUNCTIONS = frozenset(
    {"resolve_identity", "_map_value", "resolve_composition", "_compute_confidence"}
)


def test_no_source_kind_is_inference_derived() -> None:
    """No permitted source kind is derived from name/voice/image/genre."""
    for kind in SourceKind:
        haystack = f"{kind.name} {kind.value}".lower()
        for token in FORBIDDEN_TOKENS:
            assert token not in haystack, f"{kind!r} looks inference-derived"


def test_no_inferred_identity_basis_exists() -> None:
    """There is deliberately no 'inferred'/'guessed' identity basis."""
    bases = {b.value.lower() for b in IdentityBasis}
    assert bases == {"self-identified", "band-composition", "unknown"}
    for token in ("infer", "guess", "predict", "heuristic"):
        assert all(token not in b for b in bases)


def test_resolver_signature_takes_nothing_forbidden() -> None:
    """resolve_identity exposes no name/image/audio/genre parameter."""
    params = set(inspect.signature(resolve_identity).parameters)
    assert params == {"evidence"}, params
    # And the evidence record itself exposes no forbidden field.
    ev_fields = set(IdentityEvidence.__dataclass_fields__)
    assert ev_fields == {"kind", "value", "citation", "retrieved_at"}, ev_fields
    assert not (ev_fields & FORBIDDEN_TOKENS)


def test_resolver_code_never_reads_a_forbidden_attribute() -> None:
    """AST scan: the resolver functions never touch a forbidden attribute/name.

    This catches a future regression where someone wires ``artist.tags`` or
    ``artist.genre`` into the gender decision. Comments and docstrings are
    ignored — only real code is inspected.
    """
    source = Path(identity.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in RESOLVER_FUNCTIONS:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute):
                    referenced.add(sub.attr.lower())
                elif isinstance(sub, ast.Name):
                    referenced.add(sub.id.lower())

    # The only "value" allowed is enum/evidence ``.value``; assert specifically
    # that the dangerous discriminators never appear.
    dangerous = {"tags", "genre", "genres", "voice", "image", "audio", "photo", "face"}
    leaked = referenced & dangerous
    assert not leaked, f"resolver code references forbidden attributes: {leaked}"


def test_name_and_genre_do_not_influence_resolution() -> None:
    """An artist coded feminine by name + tags still resolves to UNKNOWN.

    No identity evidence is supplied, so the only thing that *could* sway the
    result is the (forbidden) name/genre — and it must not.
    """
    artist = Artist(
        artist_id="mbid-x",
        name="Florence Songbird",  # feminine-coded name — must be ignored
        tags=("female vocalists", "dream pop", "she"),  # coded tags — ignored
    )
    # The resolver takes evidence, not the artist; there is no way to pass the
    # name or tags in. With no evidence the answer is the first-class UNKNOWN.
    label = resolve_identity(evidence=[])
    assert label.gender is Gender.UNKNOWN
    assert label.basis is IdentityBasis.UNKNOWN
    assert label.sources == ()
    # The artist as constructed is also unknown by default.
    assert artist.identity.gender is Gender.UNKNOWN


def test_band_composition_evidence_cannot_set_individual_gender() -> None:
    """Lineup evidence alone never establishes a *person's* gender."""
    lineup_only = [
        IdentityEvidence(
            kind=SourceKind.DISCOGS_LINEUP,
            value="female",  # even if the raw value looks like a gender
            citation="https://www.discogs.com/artist/123",
            retrieved_at="2026-05-31",
        )
    ]
    label = resolve_identity(lineup_only)
    assert label.gender is Gender.UNKNOWN, "composition source must not set gender"


def test_permitted_sources_is_closed_and_documented() -> None:
    """The permitted set equals exactly the enum members — no hidden kinds."""
    assert frozenset(SourceKind) == PERMITTED_SOURCES


def test_assert_permitted_only_rejects_unknown_kind() -> None:
    """The explicit defensive guard raises on a non-permitted source kind."""
    from unittest.mock import patch

    from pipeline.identity import assert_permitted_only

    # A genuinely-permitted kind passes.
    assert_permitted_only(
        [IdentityEvidence(SourceKind.WIKIDATA_P21, "Q6581072", "c", "2026-05-31")]
    )
    # Simulate a future, non-permitted kind sneaking through by faking membership.
    bad = IdentityEvidence(SourceKind.WIKIDATA_P21, "x", "c", "2026-05-31")
    with (
        patch("pipeline.identity.INDIVIDUAL_IDENTITY_SOURCES", frozenset()),
        patch("pipeline.identity.BAND_COMPOSITION_SOURCES", frozenset()),
        pytest.raises(identity.InferenceForbiddenError),
    ):
        assert_permitted_only([bad])


@pytest.mark.parametrize("token", sorted(FORBIDDEN_TOKENS))
def test_evidence_value_field_is_opaque_not_a_feature(token: str) -> None:
    """A forbidden token as a raw value never maps to a gender by itself."""
    ev = IdentityEvidence(
        kind=SourceKind.MUSICBRAINZ_GENDER,
        value=token,
        citation="mb://artist/abc",
        retrieved_at="2026-05-31",
    )
    # Tokens like "voice"/"genre" are not in the controlled vocab, so they map
    # to nothing — UNKNOWN. Only genuine sourced self-ID values ever map.
    assert resolve_identity([ev]).gender is Gender.UNKNOWN
