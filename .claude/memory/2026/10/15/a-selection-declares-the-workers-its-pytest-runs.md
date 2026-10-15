---
name: a-selection-declares-the-workers-its-pytest-runs
description: verifybox.selection_demand declared a fixed SELECTION_CPU cores whatever width the verify ran (serial without xdist still claimed 4); it now takes selection_workers, the one number the -n it appends is built from, one core when serial
created: 2026-10-15
---
# A selection declares the workers its pytest runs (2026-10-15)

User ruling 2026-10-15: every run declares only the CPU cores it actually uses.

- Before: `selection_demand(capacity)` claimed `min(SELECTION_CPU, box)` cores, and `boxed` handed xdist an
  `PYTEST_XDIST_AUTO_NUM_WORKERS` cap that only bit when a consumer's addopts said `-n auto`. A repo without
  xdist (this one) ran ONE interpreter under a 4-core claim; a caller's `-n0` or `-n 8` was never read.
- Now: `selection_workers(argv, capacity, xdist=xdist_installed())` returns the workers and the `-n` to
  append. Caller's width wins as given (`auto`/`logical` = the cap; `-p no:xdist` = serial); none given
  with xdist -> `SELECTION_CPU` capped at the box, appended as `-n <cap>`; no xdist -> serial.
  `selection_demand(workers)` claims `max(1, workers)` cores. `boxed` returns `(argv, record)`; the env
  cap is gone, the explicit `-n` is the single source.
- Tests (`tests/test_dev_verify.py`): `test_a_selection_declares_the_workers_its_pytest_runs` (7 cases,
  planted controls: no xdist, `-n0`, `-p no:xdist` claim 1, never the cap); red 8/8 before, green after.
