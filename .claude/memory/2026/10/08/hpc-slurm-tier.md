---
name: hpc-slurm-tier
description: lab_commons.hpc Slurm planner and the shared width formula, from the Ada HPC session
created: 2026-10-08
---

Branch feat/hpc (bcbfeff; an ancestor of origin/integrate/main per `git merge-base --is-ancestor`, checked 2026-10-12): opt-in stdlib-only lab_commons.hpc (config TOML single source; slurm probe/parse; pure plan by free holes, quota CEILING and per-QOS submit limit; run via local/ssh Runner, stdin sent as bytes because Windows text mode wrote CRLF that sbatch refuses; worker per shard). Shared lab_commons.width.fits keyed by resources.DIMENSIONS; dev.bounded.worker_width routes through it. Fixture anonymized. E2E verified on Ada 2026-10-08. Follow-up: unify multiprocess.py and consumers' cpu_count sizing onto fits.
