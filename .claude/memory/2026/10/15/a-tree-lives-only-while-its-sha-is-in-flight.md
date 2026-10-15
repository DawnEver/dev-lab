---
name: a-tree-lives-only-while-its-sha-is-in-flight
description: files are an HPC resource; retention now keeps a cluster tree only while its sha is in flight (one in_flight function), an env only for an in-flight run or its repo's newest recorded run, runs every serve tick, and declares uv hardlinking; retention.py split into retention (run the pass) and retentionplan (what goes)
created: 2026-10-15
---
# A tree lives only while its sha is in flight (2026-10-15)

- Ruling: control the NUMBER of files intermediate artefacts make. Measured on the served cluster accounts
  (GPFS file quota 2 M or 4 M): `~/ci/trees` 0.85-2.05 M files (40-81 trees, ~22 k each), `~/ci/envs`
  0.54-1.32 M; the rest under 60 k.
- Cause: a tree was kept as long as its RUN was a carry source. The carry reads `runs/<sha>/state.json`, never
  the tree; gather reads the tree's streams only while the run has no record. So the tree was kept for a
  reference that does not exist. Same for envs: a kept carry source pinned its env.
- Already minimal per tree: trees are `git worktree`s of one bare `~/ci/cache.git` (no object store per tree),
  and the env lives apart in `envs/<key>`. The ~22 k files are the checkout plus submodules. An archive
  without `.git` would save a handful of files; the count of trees is what binds, so that is what changed.
- Rules (`lab_commons.dev.retentionplan`): `in_flight` is the one definition (live run file, Slurm workdir at
  or under the tree, ungathered and not abandoned, or younger than `min_age_hours`). Tree:
  `tree-not-in-flight`. Env/native/cargo: kept for in-flight runs' `builds` plus each repo's newest recorded
  run; an occupied tree with no run state, or an unreadable queue, decides nothing. Keeping the newest TREE
  per branch was rejected: it saves one `worktree add` at ~22 k files.
- Every tick: `every_hours` and the per-checkout state file are retired (registered); prune commands run
  only after a pass deleted something. The budget is the quota itself, the same reading admission uses as
  the `files` supply; over `pressure` after the pass, the existing `storage` alarm fires.
- uv: Linux default is already hardlink; it is now declared (`UV_LINK_MODE=hardlink`) in the build script.
  `measure` counts a hardlinked file each time it is linked, so a deleted env's freed files overstate what
  the quota sees until `uv cache prune` drops the cache side; the next tick's quota read is the truth.
- Workstation: unchanged rule shape -- a `forge-*` producer tree is in flight while its producer runs, is
  removed by `shatree.close_tree`, and a stale one goes by `forge-tree-stale`.
