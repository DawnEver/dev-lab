---
name: dependencies-float-and-records-say-what-ran
description: user ruling 2026-10-17 ("lab-commons should not pin versions either") superseded D8/D20 -- the lock regime (lockcheck pre-push, lock age, daily `uv lock --upgrade`, committed uv.lock, --frozen bootstraps, lock-required requests) is retired; served venvs follow floating git tips; every run record carries the resolved name==version list; new rule FORMATS-UPGRADE-ON-READ from the Ada journal stall
created: 2026-10-17
---
# Dependencies float; a record says what ran (2026-10-17)

## Ruling
User, 2026-10-17, repeating 2026-10-15: "lab-commons should not lock versions either! Dependencies should
not be locked unless necessary." This supersedes D8/D20 (<consumer>
`.claude/memory/2026/10/16/DECISION-distributed-compute-final-architecture.md`, merged here as `c97ddf8`).

## What changed (lane/unpin)
- Retired: `lab_commons.dev.lockcheck` (the `lock` pre-push row), `lab_commons.dev.lockupgrade`, the
  `lock_upgrade` request, `[tool.lab_commons.branchset] update`, `[tool.lab_commons.integrator]
  lock_max_age_days`, the lock-upgrade commit trailer, `Delivery.LOCKED`, `forgerequest.unreproducible`.
  All registered in `lab_commons.hpc.retired`; a manifest still declaring either key is refused by name.
- `uv.lock` untracked again and back in the family `.gitignore` base; `assert_no_tracked_lock` restored.
- `dep --bootstrap` never passes `--frozen`; this repo's hpc install is plain `uv sync --all-extras`.
- A request's git sources come from its pyproject (`hpc.builds.git_dependencies`, one parser with
  `floating_git`), not its lock.
- `hpc.builds.floating_tips` is the one fold of floating git tips into an env key: `builds_at`, the
  workstation refresh stamp (`hostrefresh.env_key`) and the deploy venv key use it, so a new lab-commons
  on the served ref re-bootstraps a served venv whose pyproject did not change.
- `envkey.env_record` = key + full resolved list from one manifest reading; local records carry it,
  cluster builds report a `resolved` fact and the run record keeps it.
- Rule `FORMATS-UPGRADE-ON-READ` (`tests/test_arch_formats_upgrade_on_read.py`): a module binding
  `SCHEMA`/`SCHEMA_VERSION = N` binds `_UPGRADES` with keys 1..N-1 and reads it. forgerun is an `_OWED`
  row naming lane/journal-schema; the merge bringing its `_UPGRADES` must delete that row.

## Still open
- origin carries the job's `update/lock` branch: `test_this_repo_carries_only_its_declared_branches`
  reds until someone deletes it (a push; not done by the lane).
- Every other adopter of the rules registry must account for FORMATS-UPGRADE-ON-READ.
- Commit `20a653e` has an empty subject (a heredoc slip); it is reverted and re-landed forward as
  `edbf7bb`, never amended.
