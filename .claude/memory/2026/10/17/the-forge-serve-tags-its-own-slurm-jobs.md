---
name: the-forge-serve-tags-its-own-slurm-jobs
description: cron sets no $LC_HPC_SESSION, so every forge array was untagged and every Ada account alarmed "N untagged job task(s)"; the forge serve now submits as session `forge` unless $LC_HPC_SESSION names one, and its pre-fix untagged arrays (job name run-<sha12>[-<part>]) are not counted as untagged
created: 2026-10-17
---
# The forge serve tags its own Slurm jobs (2026-10-17)

- Incident (forge queue 18:12Z): `ALARM untagged` on every Ada account (user1 26, user2 76, user3 18,
  user4 8, <user-b> 1). squeue on user4 showed only `run-89f11a39d6fe|(null)` x7 and
  `run-4ad64054bba3-base|(null)`: the forge's own arrays.
- User ruling: no allocation in machine files, so no host config. `forgeslurm.slurm_cluster` defaults the
  machine's session to `FORGE_SESSION = 'forge'` when `$LC_HPC_SESSION` is unset; an explicit one wins.
  Chosen over `forge:<repo>`: one serve per host is one stream across repos, and a per-repo tag would
  split its derived share by the number of repos served.
- `standing()['untagged']` now reads `squeue -h --me -r -t PENDING,RUNNING -o "%j|%k"` and counts tasks
  with no `lc:session=` comment whose name is not a run's (`hpc.run.is_run_job`: `run-<sha12>` or
  `run-<sha12>-<part>`) -- arrays sbatched before the fix stop alarming; campaign/wdg-design untagged jobs
  still alarm, correctly. Planted controls in `tests/test_dev_forgerun.py`.
- Not changed: `hpc.allocation`'s share derivation still sees those pre-fix arrays as the `untagged`
  stream until they drain (hours); only the alarm count excludes them.
- Follow-up (same day): ONE classifier, `hpc.slurm.stream_of(comment, name)` -- tag, else `forge`
  (`FORGE_SESSION`, now in `hpc.slurm`) for `is_run_job(name)`, else `''` (untagged). The probe's shared
  squeue now asks `%C|%m|%D|%k|%j`; `parse_usage` classifies through it, so the allocation's `active()`
  counts pre-fix forge arrays as `forge` and the alarm (`usage['']`) reads the same snapshot -- the extra
  `%j|%k` squeue is gone. The superseded bullet above about allocation is resolved.
