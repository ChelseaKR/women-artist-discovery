# Identity Data Ethics

> Instantiates RESPONSIBLE-TECH-AUDITS §A/§B for the distinctive risk of this
> project: doing values-aware recommendation without inferring, essentializing,
> or building a misusable gender database.
> **Last verified: 2026-05-31 · Recheck cadence: per identity-source API change.**

## Permitted identity sources (the *only* ones)

| Source | Establishes | Provenance | Known limits |
|--------|-------------|------------|--------------|
| Wikidata **P21** ("sex or gender") | individual gender | QID claim + entity URL | sparse; occasionally wrong/out of date |
| MusicBrainz **gender** field | individual gender | editorial / self-reported | editorial; "Not applicable" → unknown |
| **Artist statement** (cited) | individual gender | public self-identification + citation | requires a real, linkable source |
| Discogs **lineup** / MusicBrainz **relationship** | band composition (who fronts) | lineup URL | composition only — never a person's gender |

These map 1:1 to `SourceKind` in `pipeline/models.py`. There is deliberately **no**
source kind for a name, voice, image, or genre. Code: `pipeline/identity.py`.

## Policies

- **No inference, ever.** Gender is read only from the sources above. Enforced by
  `IdentityLabel.__post_init__` (a non-unknown gender without an individual-source
  citation raises) and proven by `tests/test_no_inference.py` (vocabulary check +
  AST scan of the resolver + behavioural checks). → metric *Inferred labels = 0*.
- **Unknown is first-class.** Default everywhere; never penalised. See
  `fairness-identity.md` and `tests/test_unknown_first_class.py`.
- **Provenance is mandatory.** Every known label carries its citations + fetch
  date. `tests/test_provenance.py`. → metric *Labels with a cited source = 100%*.
- **Female-fronted ≠ a member's gender.** It is a sourced, tri-state band property
  (`BandComposition.female_fronted`), kept separate from any individual's label.
  `tests/test_identity_model.py::test_female_fronted_is_distinct_from_member_gender`.
- **Trans inclusion.** Trans women are women; trans men are men (Wikidata QID map
  in `pipeline/identity.py`). Intersex/third-gender are represented, not flattened.
- **Correctability.** Labels are cache rows keyed to a citation; a wrong source is
  corrected at the source and re-enriched. Corrupt rows that violate a guardrail
  fail closed on load (`tests/test_cache_serde.py`).
- **Confidence is a tier, never a percentage.** `IdentityLabel.confidence` is an
  internal float used only to order/prioritise sources
  (`pipeline/identity.py::_SOURCE_BASE_CONFIDENCE`: 0.95 artist statement, 0.80
  Wikidata P21, 0.70 MusicBrainz gender); it is never rendered as a number. Any
  surface that shows identity confidence uses the qualitative tier vocabulary
  from `recommender/why.py::_confidence_tier`, derived from the actual citation:

  | Cited source | Rendered tier |
  |---|---|
  | Artist statement | "directly stated by the artist" |
  | Wikidata P21 | "recorded in Wikidata" |
  | MusicBrainz gender | "editorial database entry" |

  The numeric value cannot change the wording; no identity statement ever
  shows an unexplained number. → FIX-14.

## Non-redistribution

This repo ships **no** bulk musician-identity dataset. Identity is resolved
on-demand from upstream sources and cached locally only (`data/cache.db`, git-
ignored). MusicBrainz/Wikidata content is CC0 (attribution given); Discogs is used
under its API terms. The worst-case misuse — a scraped "gender of musicians"
dataset — is structurally prevented: there is no export of identity data and the
cache is personal/local. See `LICENSE` (data note) and `privacy-notes.md`.

## Enforcement summary

| Commitment | Gate | Where |
|------------|------|-------|
| No inferred labels | auto | `tests/test_no_inference.py` |
| 100% sourced labels | auto | `tests/test_provenance.py` |
| Unknown never penalised | auto | `tests/test_unknown_first_class.py` |
| Female-fronted distinct | auto | `tests/test_identity_model.py` |
| Identity-ethics framing | review | this document, sign-off on change |
