---
name: a-slurm-part-is-admitted-at-the-size-it-submits
description: a cluster part was admitted at a 13 GB run peak and submitted at 352 GB a task, throttled %1 from the 360 GB ceiling, and pended an hour on AssocGrpMemLimit behind 232 GB held by the account's other jobs; the claim demand now reads the plan's task_gb, the throttle reads the headroom, a first round with no headroom is not submitted, and a job held by an account limit with nothing running is given back
created: 2026-10-16
---
# A Slurm part is admitted at the size it submits (2026-10-16)

## Measured
- One account's base-part array: `ArrayTaskThrottle=1`, `ReqTRES=cpu=1,mem=360658M`, 52 tasks, PENDING `AssocGrpMemLimit` for over an hour, 0 running.
- That account: GrpTRES `mem=360G`, 29 running 8 GB one-core tasks of non-forge campaigns = 232 GB held. Card supply `mem_gb=128`, `cpu=66`.
- So the supply WAS right: `probe.account` takes `Quota.remaining()` = ceiling less every RUNNING job of the caller's on the account, whatever submitted it. CPU headroom (`plan.headroom`) also counts pending jobs; memory counts running only.
- The learned table on that host: `runs['slurm|'].peak_mem_gb = 13.04` (an older run), while `peaks_mb` held 240438.4 MB for every file of one downstream test directory (one multi-file item's peak is taught to every file in it).

## Cause
- (3) claim: `cluster_demand` asked `Run.peak_mem_gb` (13 GB, no safety); the plan asks `Measured.mem_gb` over the pending items = 240438.4 MB x 1.5 = 360658 MB a task. Two formulas, two sizes: admitted at 13, submitted at 352.
- (2) `%1`: `make_plan` set `throttle = min(shards, quota_slots(CEILING), ...)` = floor(360 / 352.2) = 1. Headroom was only used for the makespan estimate.

## Fix
- `learned.task_gb` is the ONE per-task formula; `Measured.worker_gb` and `cluster_demand`'s `mem_gb` both read it.
- `make_plan`: `throttle = min(shards, max(1, headroom slots), max_jobs)`; the plan records `room` (headroom slots now).
- `hpc.run._submit_round`: a FIRST round with `room == 0` raises `NotSubmitted` (release path) and `learned.record_ask` raises the need-set's peak so this host stops admitting the part at the old size. Retry rounds keep a floor of 1.
- `hpc.progress.held_by_a_limit` + `SlurmCluster.gather`: pending past `policy.stall_minutes` on an `Assoc*/QOS*` limit with nothing running -> learn the ask, cancel the jobs, raise `NotSubmitted` -> released for a host with headroom.

## Open
- The 235 GB per-file peaks come from one item's peak being taught to every file it held; with them the base part asks 352 GB a task, which no account's headroom holds while campaigns run. Whether that peak is real is a downstream measurement question, not this fix.
