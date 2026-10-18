---
name: local-executor-runs-ready-units-at-once-bounded-by-the-ledger
description: LocalExecutor.run starts every ready unit on its own thread; the box ledger (demand, seats, FIFO queue) is the only concurrency bound; one hash runs once; an interrupt releases every claim
created: 2026-10-18
---
# LocalExecutor concurrency, 2026-10-18 (integrator option A, D16 "local = one more host")

- `lab_commons.compute.execute.LocalExecutor.run`: a unit whose upstream is all decided is decided in the
  caller's thread (SKIPPED / CACHED / hash), then placed on a daemon thread. Each thread enters
  `hold(unit.demand, ..., queue_s)`; the ledger admits, queues FIFO among contenders, or refuses.
  NO pool size, NO semaphore: seats (`Demand(..., seats={'jmag': 1})` against `[capabilities.jmag] seats`)
  are the bound. Outcomes are returned in graph order. Journal format unchanged.
- `LocalExecutor(queue_s=...)` is how long a unit may wait for room; the default 0.0 refuses a
  contended unit at once (then it is REFUSED or OFFERED by `--where`). A caller wanting units to queue
  behind each other must pass a queue_s.
- One hash in flight runs once: a ready unit whose hash is running waits and is then CACHED.
- Interrupt / any BaseException out of an entry: scheduling stops, every ledger `Claim` held by this run is
  `release`d, the exception re-raises. A running entry is NOT killed (threads cannot be); its journal entry
  stays and the next run resumes it. A thread admitted after the cancel refuses before calling its entry.
- `Unit.demand` already existed and stays REQUIRED: `Demand` has no defaults by rule (box/demand.py), so the
  brief's "default one interpreter" was not added -- the caller declares `Demand(1, mem_gb, wall_s, {})`.
- Tests (tests/test_compute_execute.py): overlap vs dependant-waits, seats=1 serialises vs seats=2 overlaps,
  subtree failure with a running sibling, same hash runs once, interrupt releases the sibling's claim.
