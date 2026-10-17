---
name: a-run-is-one-part-of-one-sha
description: two parts of one sha on one cluster account shared ~/ci/runs/<sha>/state.json and the job name run-<sha12>; the femm part of 59ad34a6657d read base's state as its own, never submitted, settled base's record and alarmed "ended without a record" every tick. State is now runs/<sha>/<part>/state.json and the job name run-<sha12>-<part>
created: 2026-10-17
---
# A run is one part of one sha (2026-10-17)

- Incident (Ada, ezxmw9, motronics-studio 59ad34a6657d): base ran there (job 7714447, record
  `run-<sha>-base-20261017-053549.json.gz`). The femm part was then claimed on the same account.
  `SlurmCluster.submitted` read `~/ci/runs/<sha>/state.json` -- BASE's -- found its rounds, so `advance`
  skipped `submit` (the log has no `[femm] ... submitted jobs` line and sacct no femm job). `gather` settled
  the base state, re-wrote the base record, globbed `run-<sha>-femm-*` and found nothing:
  "the run of 59ad34a6657d ended without a record ... its lines above say why", every tick.
- Not a femm/runner defect: no femm job ever ran.
- Fix: `hpc.run._state_dir(sha, part)` -> `~/ci/runs/<sha>/<part>/state.json`; `load_state`, `gather_run`,
  `progress.where`, `watch.settle(part=)`, `records.run_shas(..., part)` take the part; the Slurm job name is
  `run.job_name(sha, part)` = `run-<sha12>-<part>` (orphans no longer cross parts); `forgeschedule.parse_usage`
  keys usage by `name[4:16]`; retention's `runs()` reads every part and treats a sha as unrecorded while
  any part is.
- Deploy note: a run in flight at deploy keeps its state at the old `runs/<sha>/state.json`, which the new code
  does not read; deploy between runs, or move each such file to `runs/<sha>/<its platform>/state.json`.
