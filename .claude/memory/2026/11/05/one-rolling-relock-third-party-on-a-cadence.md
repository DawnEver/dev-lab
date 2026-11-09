---
name: one-rolling-relock-third-party-on-a-cadence
description: The forge keeps ONE rolling pr/relock per repo, moves in-house siblings at once and third-party on a declared cadence, and a relock's parts carry every outcome its moves cannot reach.
metadata:
  type: project
created: 2026-11-05
---

> Redacted 2026-11-09: site markers removed (public repo).

# One rolling relock per repo; third-party on a cadence; a relock runs only what it reaches

Evidence 2026-11-05: since 10-22 the family merged 114 relock PRs (about half of all merges in the small repos:
an optimisation consumer 20/40, ai-lab 23/67, numerics-lab 9/25, the second private consumer 6/13), each a full verification. Cause: consumers
follow their siblings' integration line (kept: user ruling), so every sibling merge staled every consumer's lock
and the tick opened a `pr/relock-<dist>-<sha>`. Three user rulings, all in `dev_lab.dev.relock` and the carry.

## 1. One rolling PR -- `relock.BRANCH = 'pr/relock'`

- Each tick: stale reading at `origin/<integration>` -> `chosen` moves -> nothing due: close the open relock
  PR (integration already holds it); the open PR's head already sits on this tip with exactly these moves
  (`carried`, read off the commit body): nothing; else the door rewrites the lock ON THE CURRENT TIP (a moved
  integration is rebuilt on, never merged into), render in the same commit, `push --force-with-lease` on the head
  read by `ls-remote`, then `issue_edit` the PR body (or `pr_create`). A lost lease is a `RelockFailed`; the next
  tick reads afresh. Title is one constant; the body names tip, scope and moves.
- `forgelanes.open_lanes` now skips exactly `pr/relock` -- the old `startswith('pr/relock-')` would have opened a
  lane PR for the new name (the branchflow test is the planted control). The 2026-11-02 "relock-only branch
  closed as landed" defect stays fixed for the new name: `branchdelete.landed` exempts no file, and
  `test_dev_branchprune_sweep` already plants `pr/relock` with a lock-only diff.

## 2. In-house at once, third-party on a cadence

- IN-HOUSE = a lock package with a `git` source carrying no `rev=`/`tag=` (`relock.in_house`): a source FOLLOWING
  a line is exactly a floated sibling, derived from the lock, never listed. Assumption: a third-party git
  dependency that floats would count as in-house; none exists, and a held one (`?tag=`) is third-party.
- Third-party (index packages, `rust-toolchain.toml`, the uv pin) moves only when `third_party_due`: the newest
  commit on integration's history with trailer `Relock-Scope: full` is at least `[tool.dev_lab.relock]
  third_party_every` old (default `1 day`, a pint duration via `forgenotice.duration`, like `drift.max_behind`).
- WHERE: the repo's pyproject, not the serve config -- the cadence is a fact about the repo, several hosts serve
  one repo, and the tick reads it at the tip it relocks; a host config would let two hosts disagree.
- Before the cadence the door moves only the sibling names: `dep --lock-upgrade ROOT --upgrade-package NAME`
  now means `uv lock --upgrade-package NAME` and leaves the toolchain and uv pin alone
  (`_dep_project.lock_upgrade(packages=...)`). Held third-party moves are listed in the PR body.

## 3. A relock PR runs only the tests its move reaches

How a PR's selection is decided today, extended rather than duplicated:
- PER PART, any producer: `forgecarry.docs_only` -> `equivalent` already resolves a changed `uv.lock` to
  `import:<name>` paths (`lockreach.resolve_lock`, D48-2). A relock moving nothing any test imports carries the
  whole part from its integration parent: no run.
- PER OUTCOME, cluster: `SlurmCluster.carry` read only ancestor runs of the SAME env key -- and a relock's whole
  point is a new env, so it carried NOTHING. Now `forgecarry.env_carries` admits another env exactly when `a..b`
  moves the lock and `resolve_lock` resolved it; `carried` then keeps only the unreached outcomes.
  Residual: an interpreter change landing together with a lock move is not told apart -- lab-commons'
  `submit_run` hands the carry the env key, not the manifest (follow-up there).
- SCARCE parts: `forgescarce._waived` never resolved the lock, so an unresolved `uv.lock` reached every footprint
  and a relock produced every scarce part. It now resolves like the carry.
- Planted controls: pint (no test imports it) moved -> carried / waived; numpy (the test imports it) -> run.
- NOT covered: a BOX run (`forgeproduce`) has no per-outcome carry; a relock reaching one test there still runs
  its whole part. Building one is the next increment if box minutes matter.

## Deployment

- Takes effect when serving hosts run this dev-lab. Close any open `pr/relock-<dist>-<sha>` PRs then (they are
  no longer skipped by name; they merge or are closed like any PR). Consumers need no config: the default
  cadence is daily; declare `[tool.dev_lab.relock] third_party_every` to change it.
- Not changed: `forgeautosync` still relocks a lane's merge with a full upgrade when the merge leaves it stale
  (`door_upgrade(tree)`), which can pull third-party moves into a lane before the cadence.
