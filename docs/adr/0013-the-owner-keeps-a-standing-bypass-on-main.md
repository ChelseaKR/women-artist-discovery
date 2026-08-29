# 0013. The owner keeps a standing bypass on `main`

Date: 2026-08-29

## Status

Accepted; supersedes the "No bypass actors" provision of ADR 0001

## Context

ADR 0001 chose a branch-protection posture for a repository with one maintainer, and committed the
shape of it to `docs/audits/branch-ruleset.json`. That ruleset has never been applied. ADR 0001
says so itself: it "describes intent, not enforced fact". So the record is an open instruction,
and one of its provisions is wrong:

> **No bypass actors** — not even the repository owner/admin can merge around the ruleset. This is
> rulesets' equivalent of classic branch protection's `enforce_admins: true`; unlike classic branch
> protection, GitHub rulesets do not implicitly exempt admins, so an empty `bypass_actors` list is
> sufficient and was chosen deliberately over adding the owner as a bypass actor.

The mechanical half of that is accurate: rulesets really do not implicitly exempt admins, and an
empty list really is sufficient to stop them. The conclusion drawn from it is the error. An empty
`bypass_actors` list is not a stricter version of the same rules. It changes none of the rules.
What it removes is the maintainer's only route past a required check that cannot report a result,
in a repository whose whole premise is that there is no second maintainer to route around instead.

The failure mode is quiet. GitHub answers `201` when such a ruleset is applied, so nothing warns
the person applying it, and the ruleset that then blocks every merge is itself protected from
deletion by its own `deletion` rule. Automation applied exactly this configuration elsewhere in
this portfolio, locked the owner out of her own `main`, and restoring access took a sweep across
eighteen repositories. Adding the owner with `bypass_mode: pull_request` instead does not solve
it, because the thing that is wedged is usually the pull request.

ADR 0001 already noticed this shape of risk one bullet away, when it declined to require signed
commits before signing was configured because "turning this on first would lock the maintainer out
of their own repository". The same reasoning applies here and was not carried across.

## Decision

Supersede the "No bypass actors" bullet of ADR 0001. Every other provision of ADR 0001 stands: the
mandatory pull request, `required_approving_review_count: 0`, strict required status checks, and
the `non_fast_forward` and `deletion` blocks.

The `main` ruleset carries exactly one bypass actor, the repository-admin role held by the
accountable maintainer:

    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }

Nothing else: no team, no app, no named user, no second role. `bypass_mode` is `always` rather than
`pull_request`, for the reason above.

What ADR 0001 was protecting is kept, because the point of a bypass control is that a bypass is
*auditable*, not that it is unusable. The obligation therefore moves onto the record rather than
onto the actor list. A bypassed merge names the blocked check and the explicit authorization in the
pull request. A direct push to `main` is the last resort, reserved for a branch so wedged that no
pull request can merge at all, and carries the same record naming the pushed SHA. Force-push and
branch deletion stay blocked in every case, and the ruleset is never disabled or deleted to force a
merge through.

## Consequences

- `docs/audits/branch-ruleset.json` still carries `"bypass_actors": []` and is now known to be
  wrong. It is deliberately left unchanged by the commit that adds this ADR, so that correcting the
  target artifact stays a separate, visible decision by the repository owner rather than a side
  effect of a documentation change. Do not apply that file as it stands.
- Nothing live changes today. The ruleset was never applied, so this ADR corrects an instruction
  before it is followed rather than a setting that is in force.
- A repository-admin bypass exists, which is a real cost. The mitigation is the record, not the
  absence of the actor: a bypass that is never explained in a pull request is the thing this
  repository should treat as an incident.
- If a companion tag ruleset is ever added for releases, its `bypass_actors` list stays empty, and
  that difference from this ADR is deliberate. A branch ruleset governs where all work lands, so a
  wedged required check stops every merge and the maintainer must keep a way in. A tag ruleset
  governs artifacts that already shipped, where a bad release is corrected by cutting a new tag
  rather than moving an old one, and a bypass would destroy the immutability that makes a signed
  release worth anything. Do not harmonise the two in either direction.
- Once a second contributor exists, revisit this alongside ADR 0001's own review-count trigger: an
  independent human route past a wedged check makes a standing admin bypass harder to justify, and
  that would be a new superseding ADR rather than a silent edit here.
