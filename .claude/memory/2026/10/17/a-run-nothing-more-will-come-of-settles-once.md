---
name: a-run-nothing-more-will-come-of-settles-once
description: a submitted cluster run whose part has no state and no job (never ran), or whose jobs ended without a record, now SETTLES -- released with its reason, its file dropped, one RUN alarm -- instead of re-alarming "cannot advance" every tick (Ada femm 59ad34a6657d / af1e282ccfbe)
created: 2026-10-17
---
# A run nothing more will come of settles once (2026-10-17)

- Incident: after 669f7be keyed state by part, the pre-fix femm runs of 59ad34a6657d (ezxmw9) and
  af1e282ccfbe (<user-b>) stayed `submitted` with base's job ids; `gather` raised "ended without a record"
  and `forgeserve._advance` alarmed `run ... cannot advance` on every tick, forever.
- Rule (`forgerun._gather` / `_settle`): at `submitted`, no `state.json` for the part AND no job of its
  name in squeue = never ran; `forgeslurm.gather` raising `forgerun.Unrecorded` = ran, no record. Either
  releases with a recorded reason and drops the run file -> one alarm (`... settled`), never one per tick.
  - ran, no record: `released: inconclusive (exit 3) -- no part: ended without a record` (a human reads it).
  - never ran, sha still `tip_of(ref)`: `released: unreachable -- never submitted; claimable again` (OPEN).
  - never ran, ref moved on: `released: superseded -- never submitted, and <ref> moved on` (DONE).
- Also fixed: `SlurmCluster.submitted` swallowed `Unreachable` (a RuntimeError) as `[]` -- an unreachable
  cluster would have read as "never submitted" and settled a live run. It now propagates.
- Planted controls: a running run is kept with no alarm; a run with jobs of its name still queued is kept;
  a host answering with no state is `[]`.
