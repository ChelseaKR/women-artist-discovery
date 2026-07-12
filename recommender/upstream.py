"""Deep links to the *upstream, human-facing edit UI* for a sourced citation.

Part of EXP-05 ("Fix it at the source"): when a provenance item is wrong or
stale, the honest fix is to correct it at the source it came from, not to
quietly override it locally. This module is a pure, egress-free mapping from
a :class:`~recommender.why.ProvenanceItem` (or the
:class:`~pipeline.models.Source` it mirrors) to the edit page a person can
open in their own browser.

Guardrails, mirrored from the identity invariant (README / CONTRIBUTING):

* **String parsing only, no network.** This module never fetches anything —
  it only recognises the shape of a citation URL this project already
  produces and rewrites it to the corresponding edit surface.
* **Never an auto-edit or API-write link.** Only the ordinary, human-facing
  edit UI is linked — Wikidata's own page (anchored at the relevant
  statement) or MusicBrainz's `/edit` form. There is no code path here that
  writes to an upstream source; a person always reviews and submits the edit
  themselves.
* **No guessing.** A citation that doesn't parse, or a source kind with no
  defined upstream edit surface (e.g. a Discogs lineup page has no single
  canonical "edit this claim" URL we can safely construct), returns ``None``
  rather than fabricating a link that might be wrong or misleading.
"""

from __future__ import annotations

import re

#: Wikidata QID, e.g. the "Q12345" in https://www.wikidata.org/wiki/Q12345
_WIKIDATA_QID = re.compile(r"(Q\d+)")

#: The artist-id path segment in a MusicBrainz artist URL, e.g.
#: https://musicbrainz.org/artist/<mbid-or-slug>. Real MusicBrainz artist ids
#: are UUIDs; fixture/demo citations in this project use readable slugs
#: instead, so this deliberately accepts either — it is a URL-shape parse,
#: not a validator of what MusicBrainz itself would accept.
_MUSICBRAINZ_ARTIST = re.compile(r"musicbrainz\.org/artist/([^/?#\s]+)")

#: Source kinds whose citation is a MusicBrainz artist page. Both the
#: individual-identity kind (``musicbrainz-gender``) and the
#: band-composition kind (``musicbrainz-relationship``) point at the same
#: kind of citation URL, so they share the same edit-link shape.
_MUSICBRAINZ_KINDS = frozenset({"musicbrainz-gender", "musicbrainz-relationship"})


def upstream_edit_url(source_kind: str, citation: str) -> str | None:
    """Return the upstream *edit-UI* URL for one sourced citation, or ``None``.

    * ``wikidata-p21`` — the entity's own page, anchored at the P21 ("sex or
      gender") statement: ``https://www.wikidata.org/wiki/{Qid}#P21``. This is
      the safe choice: Wikidata does not honour a query-string that opens an
      edit form pre-filled for a specific claim, so this anchors the reader at
      the right statement on the entity page instead of fabricating one.
    * ``musicbrainz-gender`` / ``musicbrainz-relationship`` — the artist's
      ``/edit`` page: ``https://musicbrainz.org/artist/{id}/edit``.
    * Anything else (an unknown kind, a Discogs-lineup-only citation, or a
      citation that does not parse as one of the two shapes above) —
      ``None``. No link is offered rather than a guessed one.
    """
    if source_kind == "wikidata-p21":
        match = _WIKIDATA_QID.search(citation)
        if match is None:
            return None
        return f"https://www.wikidata.org/wiki/{match.group(1)}#P21"
    if source_kind in _MUSICBRAINZ_KINDS:
        match = _MUSICBRAINZ_ARTIST.search(citation)
        if match is None:
            return None
        return f"https://musicbrainz.org/artist/{match.group(1)}/edit"
    return None
