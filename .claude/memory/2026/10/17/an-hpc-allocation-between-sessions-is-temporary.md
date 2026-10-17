---
name: an-hpc-allocation-between-sessions-is-temporary
description: user ruling 2026-10-17 -- a session's share of the HPC pool is never a machine-file fact. Default derived from Slurm (measured GrpTRES pool, max-min over the tags squeue shows active, untagged a stream of its own and alarmed); override is ONE expiring forge record hpc-allocation.json written by `python -m lab_commons.hpc allocate`. The per-session machine table is retired and refused by name.
created: 2026-10-17
---
# An HPC allocation between sessions is temporary (2026-10-17)

- RULING (user, to the integrator): an allocation between sessions is TEMPORARY and must never be persisted
  in machine files. It replaces the per-session cap table added the same day (3d70b06); that table is
  registered retired (`hpc/retired.py`, `grants._RETIRED_KEYS['session']`) and a leftover is refused by name.
- DEFAULT, derived (`hpc/allocation.py`): pool = every account's `GrpTRES` ceiling summed (Ada: cpu=96,
  mem=360G per account). Active streams = tags holding pending or running tasks in `squeue -r` on any account,
  plus `untagged`. Max-min fairness per dimension, work-conserving: other streams demand what they hold now,
  the asking session demands without bound -- an idle session gets 0 and lends its share; two busy sessions
  meet at halves. No registry, no heartbeat: Slurm is the source of truth.
- The derived share never binds tighter than the pool's own headroom (every stream's holding already counts
  against the quota); it matters for the throttle and a spread, and an override can bind tighter.
- OVERRIDE: one record `hpc-allocation.json` on the forge records home (`forge records get|put|rm <name>`;
  `forgerecords.read_named/replace_named/remove_named`). `allocate --until <iso, zoned> name=cpus/mem_gb ...`,
  `--show`, `--clear`. Unexpired: decides every session, an unnamed one gets 0 (waits). Expired or absent:
  derived. A forge that cannot be read on the cluster leaves the share derived (`forgeslurm.with_allocation`).
- `session_room` is still the one seam the paging planner reads; a `Session` with `cpus`/`mem_gb` None is
  derived there. Throttle only: a session past its share plans room 0, throttle 1; nothing is cancelled.
- hpc imports only stdlib + tier one (`tests/test_hpc_gate.py`), so the hpc CLI reaches the record through
  `python -m lab_commons.dev.forge records ...` via the launch door, never by importing `lab_commons.dev`.
- Untagged job tasks are counted on the cluster host's standing (`facts['untagged']`) and `forge serve`
  raises the `untagged` alarm.
