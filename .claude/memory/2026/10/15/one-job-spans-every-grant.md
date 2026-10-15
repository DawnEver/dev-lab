---
name: one-job-spans-every-grant
description: a job-file batch now spreads over every Slurm grant by predicted throughput, one record lists each grant's slice, a dead grant's slice is re-placed; the forge test run does not span yet (named follow-up)
created: 2026-10-15
---
# One job spans every grant (2026-10-15)

- `lab_commons.hpc.span.span`: each grant that can take the batch is planned on the WHOLE of it
  (`plan.plan_on`: headroom, free slots, QOS, home inodes); throughput = padded seconds / that makespan; items
  cut into consecutive slices in proportion (`span.split`), each re-planned on its grant. Kept only when every
  slice holds one `shard_minutes_min` shard and the slowest slice beats the best single grant (`plan.allocate`).
- File-count quota is a resource: the probe reads `df -iP "$HOME"` (`Snapshot.inodes_free`) and `plan_on` refuses a
  plan writing more than `plan.files_needed` (5 + 2 per shard). `df -i` is the filesystem's free inodes, not the
  GPFS per-user quota `dev.diskusage` reads with `mmlsquota` (hpc may not import dev) -- an upper bound.
- `lab_commons.hpc.jobs`: `[job] sha`+`repo_url` derive the tree workdir and env setup; each chosen grant is
  ensured with `run build`'s `build_run` over ssh; a failed build drops that grant and re-spans. The record
  `<job>.submission.json` is `{stamp, placements[], moved[]}`; gather merges slices by item offset; retry
  re-places a silent grant's whole slice over the grants still answering (same rule: no results file, not active).
  A record without `placements` is refused (submit again). No public name changed, so nothing was retired.

## Follow-up: span the forge's `run submit` rounds

Not done here, too big for the scope. `run submit` runs on ONE login node (`cluster.submitter` is the local
shell for every grant), so it can only span grants sharing that home (`run.shares_home`: same cluster, same
user, different Slurm accounts) -- the tree is built once there. What changes: `_submit_round` uses
`span` over the same-home snapshots instead of `allocate`; `state['current']` becomes a list of
`{account, job_id, shards, items, at_ceiling}`; `gather_run`, `progress`, `records.files_made`/state reader and
`dev.forgeslurm.submitted` read every entry; `fold` takes the union of the per-account item lists. A cross-user
span for the forge would need a build in each home driven by that account's own `forge serve`, i.e. one run
claimed by several hosts -- a forge design question, not an hpc one.
