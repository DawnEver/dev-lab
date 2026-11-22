---
name: tests/base@windows is cut by the wall after two dead workers, and named no test
description: Measured 2026-11-21/22 on ci.yml runs 44962572687, 44958028133, 44961519258 -- where the Windows part stalls, why the 600 s ceiling did not name the wedge, and what is still unknown until a run carries the cells.
metadata:
  type: project
---

Measured from the job logs and the uploaded verify log (windows-2025-vs2026, `-n 2`, box `--cpu 2 --mem-gb 2 --wall 3600`).

| run | sha | last full progress line | first `node down` | second `node down` | wall verdict |
|---|---|---|---|---|---|
| 44962572687 | 72f396c2 | 00:18:33 `[ 99%]` | 00:26:58 gw0 | none before the cut | 00:37:07 |
| 44958028133 | 03fbd4b3 | 23:23:08 `[ 99%]` | 23:31:35 gw0 | 23:41:47 gw2 | 23:42:42 |
| 44961519258 | a40d3926 | 00:04:37 `[ 99%]` | 00:13:40 gw1 | 00:23:52 gw2 | 00:24:18 |

- The suite reaches ~99% in about 41 minutes; 10400 of 10471 results were printed in 44962572687, 138 of them `F`.
- One worker then holds a test to the 600 s ceiling and dies (`node down: Not properly terminated`); its replacement
  dies 612 s later on the first test it is handed. 41 + 10 + 10 minutes passes the 3600 s wall, the box kills pytest
  (exit 4294967295), no summary is printed, and the verdict is INCONCLUSIVE.
- So the ceiling of #896 fires, but NOTHING IS NAMED: the pytest-timeout stack dump of a worker never reaches the log
  (no `Timeout` line in any of the three), xdist names a dead worker's test only in the summary the wall prevents,
  and the 138 reds are likewise only dots.
- The per-test cells were on the runner the whole time (`verify-*.outcomes/`), not uploaded, and held no cell for a
  dead worker's test: xdist files it as one report in phase `???` and the recorder wrote only at teardown.

Not a cause, ruled out by measurement:

- The collected tail (`tests/test_ops_*` from index 9700 of 10483 on, `test_supervise_*`, `test_the_*`,
  `test_uv_follows_its_pin.py`) pass on a Windows 11 workstation through verify: 744 + 50 passed, no wedge.
- The box claim and the pytest argv are byte-identical to the last green Windows run.

The last complete Windows record is `run-a67a1f23...-base@windows-verify-20261120T103655Z` (10140 cells, all ok, 30
minutes). Between it and the first run that reached pytest again the runner image moved 20261103.298.1 ->
20261116.315.1 (Git for Windows 2.56.0.windows.4 -> 2.56.1.windows.1), the lock moved lab-commons by 41 commits, and
about 330 tests were added. Which of those wedges two tests and reds 138 is NOT established: the reds cluster, by
position, on files that drive the locked Node engine or real git (test_dev_supersede, test_dev_agenthooks,
test_dev_agent_guard, test_dev_worktree_remove, test_hpc_deploy_checks), which is a lead, not a finding.

What changed here so the next run answers it: a dead worker's test is a cell the moment the scheduler files it
(reason kind `worker_died`), a verify that did not settle names the failures it had recorded (dead workers
first), and the part job uploads `verify-*.outcomes/` beside the log.
