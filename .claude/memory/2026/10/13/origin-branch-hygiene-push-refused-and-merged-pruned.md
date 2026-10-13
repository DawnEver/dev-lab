---
name: origin-branch-hygiene-push-refused-and-merged-pruned
description: why an agent's lane push reached origin (base.toml had no branchset-push row since the TOML hook move) and the forge prune that deletes merged idle origin branches when a repo opts in
created: 2026-10-13
---
# Origin branch hygiene: refused at push, pruned by the forge

User ruling 2026-10-13: "origin should not carry this much garbage -- build the mechanism".

- **Why `git push -u origin lane/compute-*` was not refused.** When hooks moved from pre-commit YAML to TOML
  (2026-10-11, lab-commons 900c5bf), `base.toml` got no `branchset-push` row. Consumers' YAML entries were
  dropped (consumer-a d765934bbf), and lab-commons itself never wired one. The declared set was right:
  lane/* was undeclared. Nothing at pre-push ever consulted it. The planted control wrote the module into
  `.git/hooks/pre-push` BY HAND, so it proved the module and never the wiring.
- Fix: base pre-push row `branchset-push` (`run = python -m lab_commons.dev.branchset_push`, `always_run`).
  The planted control now installs the family runner, so a missing row reds. The `branchset-push.sh`
  wrapper is retired (hpc/retired.py).
- Prune: `lab_commons.dev.branchprune`. The serve tick on `[tool.lab_commons.integrator] host` deletes
  undeclared origin branches that are merged into origin/<integration|trunk>, idle >= `grace_hours`, and not
  an open PR head. It does this only with `[tool.lab_commons.branchset] prune_merged = true`; otherwise they
  are listed `deletable` in `forge integration` / `forge queue`. Each deletion is pinned to the judged sha,
  logged as `lab_commons.forge.prune`, and alarmed as `pruned`. Unmerged stale branches raise `stale-branch`
  and are never deleted.
- `Policy.host` is the same field lane/serve-one-queue adds (one owner, one place). Expect a textual merge
  conflict in lanepolicy.py, which resolves to the union.
- Mirror: lab-commons push-mirrors to GitHub with `sync_on_commit` on and an 8h interval. Both had the
  same 14 heads, so a mirror push propagates deletions within one interval.
