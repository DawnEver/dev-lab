---
name: forge-protection-is-declared-and-the-probe-watches-it
description: Parity gaps 3 and 7 -- branch protection rendered from [tool.dev_lab.protection] by `forge protect plan|check|apply` (GitHub ruleset, Gitea branch protection), and an ops probe role alerting drift and failed scheduled/integration CI runs once.
metadata:
  type: project
created: 2026-11-04
accessed: 2026-11-04
---

# Forge protection is declared, and the probe watches it (parity gaps 3 and 7)

- DECLARATION (`dev_lab.dev.forgeprotect`): branches from `[tool.dev_lab.integrator]`; required contexts DERIVED from
  the rendered workflows (a forge whose workflows post `tests/merge-ready` requires it on integration, else what the
  serve merge reads: `tests/base`, `tests/security`, `tests/review` when the review is a status; the trunk requires
  the base part's rows of the promotion event -- `tests/base@macos|@windows` where `ci.yml` fans parts per OS); the
  approver is `[tool.dev_lab.review] judge_login`, and approvals > 0 without a judge are REFUSED (nobody approves, so
  every merge would wait). Declared once in `[tool.dev_lab.protection.forges."<host>"]`: `breakglass` (the ONE bypass)
  and, on Gitea, `promote` (the trunk's push whitelist).
- GITHUB renders a ruleset per branch (`dev-lab integration`, `dev-lab trunk`), enforcement active, bypass in
  `pull_request` mode only, and DELETES classic protection (a second rule). A ruleset cannot name a USER: bypass is
  `role:<admin|maintain|write>`, `app:<id>` or `team:<id>`. On a personal repo (DawnEver/*) that leaves `role:admin`:
  an admin may still MERGE a PR past the rules (audited by GitHub as a bypass) but can no longer PUSH past them. Only
  a dedicated GitHub App (`app:<id>`) as the break-glass identity narrows it to break-glass alone.
- GITEA renders one protection per branch: integration takes no push (bypass allowlist = breakglass), trunk push
  whitelist = promote, trunk merge whitelist enabled and empty, `block_admin_merge_override` on.
- Live 2026-11-04: `forge protect plan` on DawnEver/dev-lab says 4 differences (two rulesets to create, two classic
  protections to delete); motronics' rules, read read-only from Gitea's database, differ on status checks,
  `mingyangbao-admin` in main's push/merge whitelists and `block_admin_merge_override`. The `/etc/breakglass/github-token`
  on the forge host answered "Bad credentials" -- the GitHub break-glass identity is unverified.
- PROBE (`dev_lab.ops.probe`, `[ops.probe] repos/tokens/state/schedule/user`): per repo reads the declaration at the
  integration branch through the forge, plans protection, reads the latest completed run per workflow among
  `schedule` and integration `push` runs; drift, a failed run and an unreadable forge are each ONE alert (state in
  `<state>/probe.json`, key + mark; cleared when it clears; an undelivered alert is resent). Token: GitHub
  `Administration: read`; Gitea an admin token scoped `read:repository` (a non-admin gets 403 on branch_protections).
- Left: `dev_lab.dev.forge.Protection/assess/apply_protection` (Gitea push whitelist only) is superseded; its one caller
  is motronics' `scripts/repo/forge_protect.py` -- retire both when motronics adopts `forge protect` and declares its
  `[tool.dev_lab.protection]`.
