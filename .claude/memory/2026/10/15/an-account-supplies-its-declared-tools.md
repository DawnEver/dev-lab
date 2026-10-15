---
name: an-account-supplies-its-declared-tools
description: a Slurm account's supply ignored [capabilities.*], so femm-marked work was unclaimable on cluster hosts; box and account now build tools through one probe.declared path, and femm has a real FEMM 5 headless presence probe
created: 2026-10-15
---
# An account supplies its declared tools (2026-10-15)

- Cause: `compute.probe.account()` built a Slurm account's supply from cpu, mem_gb, submits, files and
  linux only; `[capabilities.*]` in the account's machine file was never read, while `box()` merged them.
  A cluster host declaring `[capabilities.femm]` could never claim a femm-marked part.
- Fix (one path): `probe.declared(seats, held=, probes=)` turns declared seats into `(counts, present)`;
  `box()`, `account()` and `tools()` all go through it. `account()` takes a REQUIRED `seats=` so no caller
  can silently forget it; `forgeslurm` passes `box.declared_seats()`, the one reader of the machine file's
  seats (also used by `Capacity.read`).
- `TOOL_PROBES['femm'] = femm_found`: the FEMM 5 headless binary (`femm_headless` on linux,
  `femm_headlessw.exe` on windows) in `FEMM_DIR` or `FEMM_DIR/bin`, else the default install
  (`~/.local/opt/femm-qt/bin`, `C:/femm-qt/bin`). FEMM 4.2 has no probe (retiring). A declared femm the
  probe misses is ABSENT, so admission refuses femm parts naming it -- the existing declared-tool rule.
- Tests: `tests/test_compute_probe.py` (account tools with fakes + planted controls, femm probe per OS,
  default install via HOME).
