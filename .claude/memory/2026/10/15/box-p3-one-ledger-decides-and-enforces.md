---
name: box-p3-one-ledger-decides-and-enforces
description: P3 of the box refactor -- leases/lending/preemption deleted, a box host's forge supply is its box ledger, and a local producer runs in the box at exactly the demand it was admitted at
created: 2026-10-15
---
# Box P3: one ledger decides and enforces (2026-10-15)

User ruling 2026-10-14 "A 删除": reservations, leases, lending and preemption are deleted; priority is
ordering only. P3 lands that and moves the box host's forge path onto `lab_commons.box`.

## Decisions where the brief left a choice

| question | decision | why |
|---|---|---|
| where a box host's supply comes from | `compute.probe.box(scope, capacity=Capacity.read(), holdings=box.holdings())` | ONE source: every claim (a producer, an interactive verify) is on the ledger, so nothing is "given back" or "seated" |
| what a box part is admitted at vs. what it holds | ONE number, `compute.learned.box_demand`: measured cores and peak x `BOX_HEADROOM`, capped at the box; unmeasured = the whole box | the admitted demand is the box claim the kernel enforces; ask/hold could disagree, a claim cannot |
| how that number reaches the producer | `Work.demand`, set at claim (`forgetake._take`), read by `forgeproduce.boxed` | recomputing it in the producer would be a second derivation (and needed `origin_url` in the producer) |
| how a producer runs in the box | the CLI spelling `lab_commons.box.command(...)` -> `python -m lab_commons.box run ... -- argv`, spawned like before | serve still streams, renews, supersedes and stops (stoprun) the launcher's tree; the Job Object dies with it |
| a box with no room / a box kill | `REFUSED` (69) releases RETRYABLE; `KILLED` (137) releases naming the kill and learns the peak as a floor | an outage-like refusal is never red; a kill grows the next demand |
| `PRODUCE_WALL_S` | deleted: the box enforces `BOX_WALL_S` | one wall, enforced by the kernel side |
| `[reserve] delegates`, card `delegates`/`reservations`/`preempted`, `workstation --delegates` | deleted; `[reserve]` keeps only `cpu_margin`/`mem_margin` (the box capacity) | they existed only to authorise leases |
| who vouches for a job's origin host | the card's FORGE-RECORDED author (`forgehosts.card_of` takes `comment.author`; `card_owners`) | the security property the ledger reader held, kept in one place without the lease ledger |
| `Job.origin/origin_host/session` | deleted from `compute.model.Job` (they stay on `Candidate`, which priority reads) | only lease matchers read them on the job |
| standalone `forge tick` supply on a box | the whole `Capacity` (no holdings) | deterministic, and a tick alone runs nothing |
| retired spellings | registered in `hpc/retired.py`; `forge reserve|release` and `workstation --delegates` refuse by name | NO compatibility: the old door names its replacement and does nothing |

## The verify door and the supervisor (second commit)

| question | decision | why |
|---|---|---|
| what a selection declares | `dev.verifybox.selection_demand`: <= 4 cores (= xdist workers), 8 GB, 3600 s, killed past each | the old LIGHT run declared 2 GiB for ADMISSION only; an enforced limit needs a number a real selection fits |
| what is boxed | the pytest step only; ruff runs unboxed; the ENVIRONMENT seat (`envseat`) is still held across all three steps | the env seat guards a different resource (dependency mutation) and is not superseded |
| a producer's own verify | not boxed again (`PRODUCING_VAR`) | serve already ran it in the box at its admitted demand: no nested double claim |
| `--lock-wait-s` | kept as the spelling; it is the box queue ceiling (and the env seat wait) | P5 callers type it; the rename is not worth a flag day |
| `inflight` / `familyheads` cache dir | `resources.Broker().resource_dir()` | they only needed "a box-wide directory outside every repo", which the broker still owns |
| `supervise` `run_capped` | `SystemdProcessManager.run_capped` runs `box.command(...)` at `CAPPED_CPU = 1`, `ceiling_gb(memory_max)`, wall = timeout, queue 120 s | one manager per machine; the box's scope replaces the hand-built `systemd-run --scope` |
| rule `ONE-BOX-ONE-LOCK` | ID kept, statement and guards rewritten to the box ledger | consumers cite the ID; the meaning (one rendezvous per machine) holds |

RISK, unverified here (Windows box): the box's Linux backend uses `systemd-run --user --scope`. A supervisor
running as a SYSTEM service with no user manager gets every `run_capped` REFUSED (reported, never run
unbounded). Check on the host before deploying; the fix would be a system-scope path in `box/_linux.py`.

## Deferred

- P4: the cluster `held_run` double count (a cluster run in flight is still `running` at `cluster_demand`).
- P5: downstream callers (its gate runner and anything importing the deleted `dev` modules).
