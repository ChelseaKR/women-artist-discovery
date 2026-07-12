# 0003. Build backend: setuptools → hatchling

Date: 2026-07-05

## Status

Accepted

## Context

`CQ-10` in the standards audit flagged that this repo built no real wheel in CI and used
setuptools as its build backend with no dedicated build step. A tag-triggered release workflow
(`.github/workflows/release.yml`, this pass) needs a working `uv build`/`python -m build` step to
produce the sdist + wheel that get SBOM'd, signed, and attached to a GitHub Release.

## Decision

Switch `[build-system]` to `hatchling` (`requires = ["hatchling>=1.27"]`,
`build-backend = "hatchling.build"`). Replace `[tool.setuptools]`/`[tool.setuptools.package-data]`
with `[tool.hatch.build.targets.wheel] packages = ["pipeline", "recommender", "app", "export"]`;
`py.typed` markers need no separate package-data declaration under hatchling — they're included
automatically as tracked files inside an included package directory.

Verified locally: `uv build` produces a correct wheel (37 files: all four packages' `.py` files
plus `py.typed` in `pipeline`/`recommender`/`export`, matching the prior setuptools output) and
sdist; `uv lock` regenerated cleanly; a full `make verify` re-run (lint, `mypy --strict`, 168
tests, security, eval, i18n) stayed green on the new backend.

## Alternatives considered

- **Stay on setuptools, add an explicit build step.** Rejected — setuptools' `pyproject.toml`-only
  configuration for a multi-package flat layout is more verbose than hatchling's, and hatchling is
  the same backend `uv build`'s own defaults assume, so it's the smaller-friction choice given a
  release workflow was being built in the same pass anyway.
- **Do nothing until the first release.** Rejected — building this out now, while the release
  workflow is being scaffolded end-to-end, is cheaper than doing it later as a second pass; the
  change is low-risk (verified) and self-contained.

## Consequences

- `CQ-10` closes.
- `[tool.hatch.build.targets.wheel]` is now the place to update if a new top-level package is
  added (mirrors the old `[tool.setuptools] packages` list).
- No behavior change for `uv sync`/editable-install workflows (`make install`, CI) — this only
  affects `uv build`/`python -m build`, exercised so far only by `release.yml` (not yet triggered;
  see the remediation log for why).
