---
name: a-serve-tick-is-bounded-and-the-hour-was-the-carry
description: Ada serve ticks ran 35-70 min with the host card published only at the end, so forge queue showed live hosts STALE. Measured cause - forgecarry judged each test file's import closure separately (quadratic, 33 min of pure CPU before one sbatch). Fixed with one backward taint pass, plus a card before each advanced run and a tick bounded by its period.
created: 2026-10-17
---
# A serve tick is bounded; the hour was the carry (2026-10-17)

- Symptom (Ada, ezxmw9@hpclogin01 and ezxmb14@hpclogin02, motronics-studio): `flock -n ... forge serve`
  alive, one tick running more than 1 h, `forge queue` showing the host STALE, and every later cron start skipped.
- Measured. Log lines have no timestamps, so the times come from forge status `created_at`, file mtimes and `/proc`:
  - gather, route and post were NOT the bulk. On 38258ea7583b, 'publishing' was posted at 11:40:31Z and the
    failure status at 11:40:35Z, so routing 5 issue updates plus the post took 4 s.
  - hpclogin01, tick starting 12:50Z: c9a2e314012d was published at 12:50:52Z. The tick then advanced the
    new claim ef797e4fab42. Its prep collect finished at 13:04Z (`prep.log`). After that the serve process
    ran at 100% user CPU with no I/O, no syscalls and no children until `submitted jobs 7716582` at
    13:37:19Z. That is 33 min in `SlurmCluster.carry` -> `forgecarry.carry_from` -> `carried` ->
    `Footprints.of(test).reaches_any` per test file.
  - Local replay (c0928c03937c -> ef797e4fab42; 5119 test files, 8.3k modules, 47 changed paths): `of()`
    projected 73 min. The profile showed 268M `list.pop`, 1M `sorted`, and `top` rebuilt over 13.8k
    tracked paths on every parse. Each test re-walked the shared closure.
  - hpclogin02 at the same time was in the same step: a submit's in-tick prep collect (~2-3 min per run),
    then the carry.
- Fix 1 (`fix(carry)`): `Footprints.reaches(test, changed)` taints the modules whose closure reaches the
  change and walks importers backwards once per changed set. It equals `of(test).reaches_any(changed)`
  (tested on cycles, declared and undeclared reads, seeds, globs and non-test files). The same pair now
  takes 33 s, all of it the linear per-module parse.
- Fix 2 (`fix(serve)`): `_advance` publishes the host card before each run and, once the tick period
  (`tick_minutes`) is spent, leaves the runs it has not reached in flight for the next tick. It always
  advances at least one run. A tick is now bounded by its period plus one step.
- Not fixed, by design: the deferral always starts from the head of `live()` order. If the head run's
  step alone exceeded the period on every tick, the runs behind it would wait. Every slow step seen so
  far happens once per run (submit, publish), so this has not occurred.
- Also seen: the femm 59ad34a6657d loop (`a-run-is-one-part-of-one-sha.md`) re-settles base's 36 MB state
  every tick on the deployed 17471634e. That is fixed upstream and needs a deploy.
