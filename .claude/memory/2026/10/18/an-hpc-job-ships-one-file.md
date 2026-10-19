---
name: an-hpc-job-ships-one-file
description: 2026-10-18 lab_commons.hpc -- a job at a commit runs from ONE artifact file, writes ONE results.jsonl, keeps task output node-local, and fails gather past a declared file budget; image format refused until the Ada node probe
created: 2026-10-18
accessed: 2026-10-18
tags: [hpc, ada, file-quota, artifact, retention, campaign]
metadata:
  type: project
---

# An HPC job ships one file (plan from motronics, 2026-10-17)

Branch `feat/hpc-one-file-per-job`. Before: a campaign job reused the test layout (a checkout plus an unpacked
venv per sha, ~46 k files) and wrote a Slurm log plus a results file per task.

## What landed

- Phase 1, `lab_commons.hpc.artifact`: `~/ci/artifacts/<sha>.tar.gz`, built in login-node `$TMPDIR` scratch
  (`git archive`, a fresh venv, uv cache in the scratch), packing `env/`, `tree/<source_roots + artifact_paths>`,
  `native/` and `activate.sh`. `FORMATS` declares `tarball` (built) and `image` (refused, naming the probe).
  `[job] artifact`, `run build --artifact`, `[tool.lab_commons.hpc] artifact_paths`.
- Phase 2: `built_config` puts `enter_lines` (unpack into `$TMPDIR`, source, cd) ahead of the job's setup; a
  `[job] workdir` under `~/ci/trees/` is refused by name. Run dirs for sha jobs: `~/ci/jobs/<sha>/<name>-<stamp>`.
- Phase 3: the worker appends outcomes-format `Event` lines (`item`, `shard`) to one `results.jsonl` under an
  exclusive lock. `Record` itself was not used: it keeps one writer per file, and a run has one per array task.
  `--output=/dev/null`; output goes to `$TMPDIR`, and `worker --close` keeps a 40-line tail. `gather` reads only
  this file. The earlier per-shard `results/<n>.json` layout is read one way (FORMATS-UPGRADE-ON-READ).
- Phase 4: the artifact's uv cache dies with the scratch; every forge env build ends `uv cache prune --ci`.
- Phase 5 (half): retention's `artifact-not-live` keeps the artifact of any sha a queued or running job works
  under (`occupied_shas`: `ci/trees` or `ci/jobs`), plus the newest. NOT done: forge `runs/*/streams` as one
  file per run.
- Phase 6: `[policy] file_budget = 10`, checked at gather (`files_of`); over it, gather exits 1. A planted
  11-file run reds. Earlier-layout runs are named, not judged.

## Cross-version note

The worker comes from the job env's own pinned lab_commons. Until a repo bumps its pin, its tasks still
write the earlier layout. The `--close` line is `|| true`, so an old worker is harmless, and gather reads
that layout.

## Open

- CLOSED 2026-10-19 (user ruling): the image format is refused for good -- `uv sync --frozen` from the
  committed lock already gives reproducibility, and Ada offers only singularity 3.8.5 as a module. The probe
  below is no longer owed.
- Ada probe not run (the classifier denied the ssh). Still needed: `which apptainer singularity squashfuse`,
  plus `srun -p <partition> -t 2 bash -c 'which apptainer singularity squashfuse; df -h $TMPDIR'`.
- Not proven: one gathered T3 shard reproducing the checkout layout's rows.
- Git submodules are not in a tarball.
