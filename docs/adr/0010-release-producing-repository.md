# 0010. This is a release-producing repository (pipeline prepared, first tag human-gated)

Date: 2026-07-17

## Status

Accepted (backfills the REL-01 declaration made in the 2026-07-05 conformance pass)

## Context

`RELEASE-STANDARD` asks every repo to declare itself release-producing or not (REL-01). This repo
sat in an ambiguous state — `pyproject.toml` version `0.1.0` and an earlier phantom "0.1.x
current release line" claim, but zero tags or releases. The 2026-07-05 pass resolved the claim
honestly ("unreleased pre-1.0", `SECURITY.md`/`CITATION.cff`/`CHANGELOG.md`) and built a full
tag-triggered pipeline (`.github/workflows/release.yml`: re-verify at the tag → `uv build` →
CHANGELOG-section gate → CycloneDX SBOM → cosign keyless signing → GitHub Release), but the
declaration itself never got its dated decision record.

## Decision

The repo is **release-producing**: versioned artifacts (sdist/wheel with SBOM and signature) are
built by the tag-triggered pipeline, and the README conformance table answers REL-01 accordingly.
Two boundaries are part of the decision, not omissions:

1. **Cutting a tag is a deliberate human action** — `git tag -s v0.1.0 && git push origin v0.1.0`
   stays with the maintainer (it asserts release readiness and requires the signing setup;
   automation must never mint one). Until the first tag, "unreleased pre-1.0" remains the only
   honest description and CHANGELOG entries stay under `[Unreleased]`.
2. **Building is not publishing** — the pipeline attaches artifacts to a GitHub Release only.
   PyPI publication (REL-15) is a separate, undecided step; nothing may drift into it without its
   own decision record.

## Consequences

- REL-01 has a stable answer; SECURITY.md's support policy becomes true (not aspirational) at the
  first tag, when the CHANGELOG `[Unreleased]` section is cut to `[0.1.0]`.
- The release workflow remains unexercised until that first human-cut tag; its first run is the
  end-to-end proof, and any failure there is release-blocking by design.
- A future "not release-producing after all" or "publish to PyPI" decision supersedes this ADR
  explicitly rather than happening by drift.
