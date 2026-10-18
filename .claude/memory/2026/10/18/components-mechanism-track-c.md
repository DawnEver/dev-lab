---
name: components-mechanism-track-c
description: Track C of the <consumer> PLAN-engines-and-one-outcome-vocabulary landed on lane/track-c -- [tool.lab_commons.components] schema (path derived as components/<name>), drift() over .gitmodules/uv sources/Cargo/gitlinks, a stateless bump loop on one lane name lane/components-bump, served checkouts init submodules; plus the two integrate/main reds (module-size split of forgerun/deploy/rule rows, box Claim cycle)
created: 2026-10-18
---
# Components mechanism (Track C), 2026-10-18

- Plan: <consumer> `.claude/memory/2026/10/17/PLAN-engines-and-one-outcome-vocabulary.md`, II.5 and C1-C6.
  Docs: `docs-src/dev/components.md`. Consumer side is Track E (<consumer> E1).
- C1 `lab_commons.dev.components.components_of`: one table per engine; required `url branch parts`,
  optional `package crates`. DECIDED HERE: the mount path is DERIVED (`components/<name>`) and a
  declared `path` is refused (the plan listed path as a key; one source of truth wins). Names must be
  `<x>-lab` (R7); `lab-commons` refused (R8). `components` added to `hpc.declared.KNOWN_TABLES`.
- C2 `drift(...)` pure, `drift_at(root)` reads the index (`ls-files --stage`), `.gitmodules`, tracked
  `Cargo.toml` outside components/. Only `components/` is policed. CLI `python -m lab_commons.dev.components`.
- C3 `lab_commons.dev.componentbump.tick(rows, product, engines)`. DECIDED HERE:
  - NOTHING PERSISTED: state is origin refs + forge statuses + issue titles, so FORMATS-UPGRADE-ON-READ
    has no format to apply to.
  - ONE lane name for all engines, created with `--force-with-lease=<lane>:` -> serialisation by git.
  - Green = every part the component declares PASS -> READY; the tick does NOT merge, the existing
    integrator queue does (plan II.5 step 4). Absorbed lane -> deleted (LANDED).
  - Red -> one issue `components: bump <name> to <sha12> is red` (dedup by title over open+closed),
    lane deleted (so the integrator's BLOCKED prompt never makes a second issue); the title's existence
    is the hold on that engine sha.
  - Engine green = `platformparts.standing(...).result == 'PASS'` on the engine's own forge;
    `forgework.client_for(root, url=...)` added for that.
  - Not wired into `forge serve`; run by cron/the integrator via the CLI. Wiring is a follow-up.
- C5: forge trees and cluster trees already init submodules; the gap was `hpc.deploy_steps.update`
  (served checkout), now `submodule update --init --recursive` when `.gitmodules` exists.
  NOT done: `dep --bootstrap` of a fresh agent worktree does not init submodules (lock-fresh lane's area).
- Reds fixed first: `forgerun` -> `forgerunstate` (state file, schema upgrades, Cluster protocol),
  `deploy` -> `deploy_account` (credentials, grant), FORMATS-UPGRADE-ON-READ row -> `_rule_rows_b`;
  `box.Claim` moved to `box.demand` (cycle gone, no lazy import).
- Still red on integrate/main, NOT mine (lane/outcomes-a0): undeclared suppressions and reflection in
  `outcomes/cell.py` + `tests/test_outcomes_cell.py`; `tests/test_hpc_run.py:1400` locale encoding.
