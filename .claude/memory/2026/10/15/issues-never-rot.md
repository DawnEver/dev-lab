---
name: issues-never-rot
description: forge tidy runs in forge serve for every served repo with every rule on by default, deletes comments of a retired marker kind (kinds = forgepulls.Marker) and closes work issues idle past work_max_idle_days
created: 2026-10-15
---
# Issues never rot (2026-10-15)

User ruling 2026-10-15: build a mechanism so issues do not age. Audit found four kinds of rot.

- **Where it runs.** `forge tidy` moved from `forge integration` (one integrator, only repos declaring a table)
  to `forge serve` (`forgeserve._hygiene`, any host, every tick: a pass is idempotent). Every rule is ON by
  default (`forgetidy.Hygiene`); `[tool.lab_commons.forge.issue_hygiene]` only tunes. lab-commons dropped its
  table (it equalled the defaults). A downstream repo needs no line.
- **Retired machine comments.** `forgepulls.Marker` (StrEnum) is the one registry of hidden-marker kinds;
  `marker(kind, key)` and `comment_upsert(kind=, key=)` take only a member, so the live set IS the writers'.
  A comment on an open issue whose marker kind is no member is deleted (was: 4 `reserve:` comments on the
  hosts issue, removed by hand). Comments are read per open issue with `comments > 0`, not the repo-wide
  listing (bounded at 5000 by `pages`).
- **Idle work issues.** `work_max_idle_days = 14` closes an open issue no machinery keeps (not hosts, not
  `area:`, not a request, not `<kind>: ` for `forgealarm.ISSUE_KINDS`, no marker in its body) by `updated_at`.
  `raise_once` refuses a kind outside `ISSUE_KINDS`, so tidy's exemption cannot drift from the writers.
- **BLOCKED integration issues** already closed themselves: `forgeroute.reconcile` closes every open
  `integration: ` issue the queue no longer derives, each serve tick (`test_reconcile_keeps_one_issue_per_title...`).
- Retired: `forgetidy.SUBJECT`, `forgeintegration.SUBJECT`, `hygiene.any`, "run by `forge integration`".
