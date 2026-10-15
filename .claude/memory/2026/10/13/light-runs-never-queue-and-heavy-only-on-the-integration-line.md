---
name: light-runs-never-queue-and-heavy-only-on-the-integration-line
description: user ruling 2026-10-13 -- the CPU seat binds only saturating runs (light = targeted, capped width, admitted by declared memory); .full parts filtered per ref; producers below normal priority
created: 2026-10-13
---
# Light runs never queue; heavy only on the integration line (user ruling 2026-10-13)

Source: the downstream repo's `.claude/memory/2026/10/13/HANDOFF-modeling-and-objective-gaps-for-the-transient-campaign.md` section 6, Q1-Q4.

## Q1 -- the seat binds only SATURATING runs

- `CpuSeat(saturating=False)` takes NEITHER seat. It is admitted in its own pool `LIGHT_POOL` by its
  declared `memory` demand (refused at construction without one). Its ceilings are OS readings of THIS box
  at admission: memory = total, seats = cores // `LIGHT_WIDTH` (4). MEASURED why: on the conservative
  default an unmeasured box requires 50% of total FREE whatever was declared -- a 64 MB demand was refused
  on this 32 GB box with 4.6 GB free, so the declaration would have been decorative.
- `hold_run_seats(..., memory_bytes=)`: `None` = saturating (takes the box seat, unchanged); an int = light.
  `famtests.boxseat.HOLD_RUN_SEATS_PARAMETERS` now pins five names (adopters' `>=` copies still pass).
- `verify`: a TARGETED selection is light -- `LIGHT_MEMORY_BYTES` (4 x 512 MiB) and `LIGHT_ENV`
  (`PYTEST_XDIST_AUTO_NUM_WORKERS=4`, inert without xdist). Full runs are the producer's and take no seat.
- Planted: `test_a_light_run_completes_while_a_planted_heavy_holder_holds_the_seat` (same block: a second
  heavy run is refused). `test_a_held_box_exits_3_from_a_real_process` now plants every LIGHT seat in a
  private record root, because a targeted verify no longer waits on the box seat.
- Rule row ONE-BOX-ONE-LOCK restated in the same 9 lines (the `_rule_rows.py` size pin is 422).

## Q2 -- `.full` parts only where the part's ref filter admits

- `[tool.lab_commons.parts.refs.<part>] <scope> = [fnmatch...]`, read by `platformparts.part_refs` from the
  SERVING checkout (a branch cannot widen its own filter); `forgeschedule.candidates` drops an excluded
  candidate and SAYS it (`[serve] <ref> is not served tests/<part> at full: ...`). Absent = unchanged.
- TRACE of host G claiming a feature sha: integrate mode serves the integration head, PRs into it, opted-in
  `schedule.branches`, and request issues. the downstream repo declares no `schedule.branches`; a request has no sha;
  the open PR #2454 `feat/winding -> integrate/main` is a PR candidate with a feature sha. So: the PR path.

## Q3 -- producers below normal priority

- `forgeproduce.below_normal(spawn, argv, **kw)`: Windows `BELOW_NORMAL_PRIORITY_CLASS` at creation (inherited
  by the pytest workers); POSIX renice to 10 right after spawn (no `preexec_fn` beside serve's threads).
  Measured by `tests/test_dev_forgeproduce_priority.py` reading the class back via `GetPriorityClass`.

## Not mine, seen red

- `tests/test_two_repos_cannot_both_hold_the_cpu_seat.py::test_a_holder_under_its_own_pool_name_still_excludes_a_second_checkout`:
  its second checkout runs verify AS THE PRODUCER (`producing(...)`), which takes no box seat
  (`boxwait`), so it runs. Red on base `origin/integrate/main` by that reading, independent of this change.
