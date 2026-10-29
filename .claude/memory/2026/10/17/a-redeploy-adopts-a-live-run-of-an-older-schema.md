---
name: a-redeploy-adopts-a-live-run-of-an-older-schema
description: redeploying Ada from 1747163 to 12dd0ff left 17 live schema-1 forge-run files; live() refused the first and serve exited 1, stopping every tick on four accounts. live() now upgrades schema 1 -> 2 on read (write-back, old job name kept as an alias squeue also asks for) and a tick skips an unknown-schema file with a RUN alarm
created: 2026-10-17
---
# A redeploy adopts a live run of an older schema (2026-10-17)

- Incident (~14:28Z): host kits redeployed 1747163 -> 12dd0ff/8ea6f6e under 17 live runs (user4 5,
  <user-b> 4, user1 3, user3 5). `forgerun.live` raised `ForeignSchema` on the first schema-1 file and
  `forgeserve` caught it at the top, exit 1: ONE file stopped the WHOLE tick, every run, every tick.
- Schema 1 -> 2 changed no field: 2 added the `submitting` phase (D19, cc749ce), a value schema 1 never
  wrote. What did change under the same file is the Slurm JOB NAME (669f7be): `run-<sha12>` ->
  `run-<sha12>-<part>`. Live schema-1 jobs carry the old name (seen on user3: `run-c4b6bfd37f23`).
- Upgrade (`forgerun._UPGRADES`, `_from_1`): every field carried, `schema` 2, `job_aliases =
  ['run-<sha12>']`; written back through `save` (durable, atomic). `SlurmCluster.orphans` asks squeue for
  `run-<sha12>-<part>,<aliases>`. Orphans is the only reader of the job name: submitted/gather/progress/
  cancel go by the cluster state's job ids. Unknown schemas still refuse; `live(refused=...)` lets serve
  skip that one file with a RUN alarm.
- The state.json move (`~/ci/runs/<sha>/state.json` -> `<sha>/<part>/state.json`) is compatible: checked
  user3 253407f03e38 -- `base/state.json` holds `platform: base` and rounds `[<job>]`, matching the
  journal's job_ids; `streams/` stays at `runs/<sha>/streams` where `records.stream_sources` reads it.
- Fixture: `tests/_hpc_fixtures/forge-run-schema1-2026-10-17.json` (user3's c4b6bfd37f23, account
  renamed to alice).
