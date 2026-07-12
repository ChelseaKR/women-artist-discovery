# 0000. Record architecture decisions

Date: 2026-07-05

## Status

Accepted

## Context

Decision content for this repo has existed since the start, but only inline (`docs/ROADMAP.md` §6
"Key decisions (ADRs)", build-log addenda, and code comments) rather than as discoverable,
individually-dated records. `CQ-44`/`DOC-04` in the standards audit ask for a real ADR log.

## Decision

We will use lightweight MADR-style ADRs, one file per decision, numbered sequentially in
`docs/adr/NNNN-title.md`, with sections: Status, Context, Decision, Consequences. Superseding a
decision adds a new ADR and marks the old one `Superseded by NNNN` rather than editing history.

## Consequences

- Decisions get a stable, linkable record instead of being buried in ROADMAP prose.
- ROADMAP §6 remains the human-readable narrative; ADRs are the dated, individually-referenceable
  backing record. Existing ROADMAP decision content is backfilled as ADRs opportunistically
  (tracked in the remediation plan's P2-1), not all at once.
