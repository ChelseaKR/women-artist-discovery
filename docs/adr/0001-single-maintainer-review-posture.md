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
  **Reversed 2026-08-28 — see "Update 2026-08-28" below. This bullet is the one part of this
  decision that turned out to be wrong, and the reason is in the Alternatives section already:
  the same lockout risk this ADR foresaw for `required_signatures` applies to an empty bypass
  list, and it was not foreseen there.**
- **Force-push and branch-deletion are blocked** (`non_fast_forward`, `deletion` rules).
- **Signed commits are not required yet** — see the alternative considered below.

## Update 2026-08-28 — the "no bypass actors" bullet is reversed

Everything else in the Decision above stands. What is reversed is the fourth bullet.

`docs/audits/branch-ruleset.json` now records the bypass actors the live ruleset actually
carries, and the load-bearing one is the repository owner's standing bypass:

```json
{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
```

That is deliberate and permanent. **An agent applied a ruleset with no bypass and locked the owner
out of their own repository**, and restoring access took a sweep across eighteen repositories in
this portfolio. The owner's standing instruction since is that they must always be able to bypass,
in any repository. An empty `bypass_actors` list is therefore not the stricter posture this ADR
assumed; it is the lockout.

This ADR had already reasoned its way to the same hazard from the other direction, and stopped one
step short. The Alternatives section rejects requiring signed commits immediately because "turning
this on first would lock the maintainer out of their own repository". An empty bypass list is the
same failure with no `--no-verify` equivalent: there is no local configuration change that gets you
back in.

What the bullet was protecting is unaffected. The direct-to-main push the audit found (`56628ee`)
is blocked by the pull-request rule, not by the bypass list; the four `verify` legs are still
required and still strict. The bypass is the way back in when a required check is wedged, not a
routine merge path.

**A second entry is also recorded, and it is the same person.** The live ruleset carries
`{"actor_id": 3114598, "actor_type": "User", "bypass_mode": "pull_request"}` alongside the role
entry. Actor 3114598 is the maintainer's own user account; that grant is a weaker legacy one
(`pull_request` mode does not cover a direct push) and it is *not* a substitute for the
`RepositoryRole` entry. Both are recorded because the file is meant to be re-appliable without
changing what is live. If either is ever removed, remove the `User` one.

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
