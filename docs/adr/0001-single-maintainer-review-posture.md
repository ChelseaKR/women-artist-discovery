# 0001. Single-maintainer branch-protection posture

Date: 2026-07-05

## Status

Accepted; the Python-version matrix provision is superseded by ADR 0004

## Context

The audit (`audit-2026-07-05/women-artist-discovery-AUDIT.md`, P0-2) found a direct-to-main push
(commit `56628ee`, 2026-07-02) proving no merge gate was enforced — every AUTO gate in `ci.yml` was
advisory. The standard CI/CD posture (CICD-11 through CICD-18) assumes at least one independent
reviewer; this repo has exactly one maintainer, so "require ≥1 approving review" is unworkable —
it would either block all solo merges or force a meaningless self-approval.

## Decision

Adopt this posture for the `main` branch, expressed as a GitHub ruleset (not classic branch
protection), committed as the target configuration in `docs/audits/branch-ruleset.json`:

- **Require a pull request** to reach `main` — direct pushes are blocked, full stop.
- **Required approving review count: 0.** A PR is mandatory; a second human approver is not, since
  there isn't one. Review substance is enforced by the same person doing a deliberate PR-diff read
  before merging, not by a second reviewer.
- **All four `verify` matrix legs (Python 3.10–3.13) are required status checks**, strictly
  up-to-date with the base branch before merge.
- **No bypass actors** — not even the repository owner/admin can merge around the ruleset. This is
  rulesets' equivalent of classic branch protection's `enforce_admins: true`; unlike classic branch
  protection, GitHub rulesets do not implicitly exempt admins, so an empty `bypass_actors` list is
  sufficient and was chosen deliberately over adding the owner as a bypass actor.
- **Force-push and branch-deletion are blocked** (`non_fast_forward`, `deletion` rules).
- **Signed commits are not required yet** — see the alternative considered below.

## Alternatives considered

- **Require ≥1 approving review anyway**, satisfied by a second GitHub account or an external
  collaborator. Rejected for now: no second maintainer exists, and inventing one for compliance
  theater would be worse than an honest, documented single-maintainer posture.
- **Require signed commits immediately.** Rejected until commit signing (SSH or gitsign) is
  configured locally (tracked as P3, `CQ-41`/`REL-08`) — turning this on first would lock the
  maintainer out of their own repository.
- **Leave branch protection off entirely** (status quo). Rejected — this is exactly the P0 finding
  the audit raised; a documented, applied ruleset is strictly better even without a second
  reviewer.

## Consequences

- Every change to `main`, including the maintainer's own, must go through a PR with green required
  checks. This is a process cost accepted deliberately for the discipline it buys back.
- `docs/audits/branch-ruleset.json` is the **target** configuration; applying it live requires a
  `gh api` call with `admin:repo` write scope, which the standards-remediation pass that produced
  this ADR deliberately did not execute (out of scope for an automated pass — see the remediation
  log for the exact command). Until it is applied, this ADR describes intent, not enforced fact.
- Once a second contributor exists, revisit `required_approving_review_count` and
  `require_code_owner_review` upward; this ADR should be superseded, not silently edited, when that
  happens.
