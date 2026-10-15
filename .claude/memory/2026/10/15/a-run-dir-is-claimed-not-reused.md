---
name: a-run-dir-is-claimed-not-reused
description: paths.run_output_dir named a run dir by the second and reused an existing one (exist_ok=True), so two processes started in the same second shared one dir; it now claims atomically through the one _claim loop it shares with unique_run_dir
created: 2026-10-15
---
# A run dir is claimed, not reused (2026-10-15)

- Cause: `run_output_dir` built `<root>/logs/<yy>/<mm>/<dd>/<name>/<HH-MM-SS>` and `mkdir(exist_ok=True)`.
  The stamp has one-second resolution, so two processes started in the same second wrote one dir
  (interleaved logs, overwritten checkpoints, a resume reading the wrong run).
- Fix: the first call per parent in a process CLAIMS `<stamp>` with `mkdir(exist_ok=False)`, else
  `<stamp>-2`, `-3`, ...; the claim is memoized per parent (`paths._claimed`), so one invocation stays
  in one dir. The loop is `paths._claim`, now the only claim loop: `unique_run_dir` delegates to it.
- Sweep: no other `src/` helper builds a `<stamp>` dir; the remaining `exist_ok=True` calls create
  parents or fixed dirs, which is correct.
- Tests: `tests/test_paths.py::TestRunOutputDirClaim` -- taken stamp -> `-2` and stable, unclaimed
  -> plain stamp and stable, two real processes behind a file barrier with a frozen stamp get distinct
  dirs and see only their own file, and a planted control (exist_ok=True restored in the children)
  lands both in one dir.
- No public name changed, so nothing is retired. Consumers holding a local copy of the claim loop can
  delete it and delegate once their pin moves.
