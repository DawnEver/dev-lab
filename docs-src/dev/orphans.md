# Killed runs, orphans, and the process census

- This page is what happens AFTER a run is stopped: what survives, what can reap it, and the one machine-level prerequisite the reaper depends on.
- The tiers, walls and verdict model are on [the verdict model](verdict-model.md); concurrency is on [fan-out](fanout.md); what the box rations while a run is alive is on [box resources](box-resources.md).

## Stopping a run does not stop the run

- Killing the wrapper — a tool-level stop, closing the shell, a timeout firing on the pipeline — ends the CONTROLLER and leaves the test session and every parallel worker alive.
- Measured 2026-08-27: a stopped sharded heavy run left the controller plus **16 workers** running, memory climbing from 5.2 GB to 17.4 GB, still executing for about ten minutes.
- The workers stop advancing once the controller dies, because nothing dispatches to them — but they do not EXIT, and **they keep their memory**.
- That memory is not cosmetic: worker width for the NEXT run is sized from available memory, so an unreaped fleet quietly narrows every later tier.
- **Kill a process TREE by its ROOT pid.** Stopping a wrapper leaves its children running, which is this whole page in one sentence.

## The lock does not time out, by design

- A lock file records the holder's pid, what it is doing and since when, and the lock judges the holder's LIVENESS, never the file's AGE — a dead pid is not a holder, so a crashed run leaves at worst a stale file and never a blocked box.
- The failure this does NOT cover is a holder that is alive and idle: an orphaned controller reads as alive with zero CPU and holds the lock legitimately, forever.
- Every tier then refuses, naming the holder, which is correct behaviour against an incorrect situation.
- **So the remedy is always to end the orphan, never to steal or age out the lock.**

## What can reap, and what cannot

| tool | what it does |
|---|---|
| a tool-level stop, or closing the shell | ends the wrapper only, never the process tree |
| the system task-kill utility | shares the management infrastructure with the process lister; on a damaged box it answers with a class error |
| the shell's own process cmdlet | works always — a direct API call — but cannot see command lines |
| a reaper script | the supported route; needs a full census, below |

- The reaper decides at the BOX level: a test process is an orphan when NO live controller is anywhere on the box, and is OWNED when one is.
- It **refuses whenever any live controller is present, even over provable orphans**, because not reaping is always safe and reaping a live run's workers is never — that kill reads as a worker death and voids someone's verdict.
- It needs COMMAND LINES to tell a run's workers from any other interpreter, which is why the lightweight process cmdlet is not a substitute and the reaper was NOT widened onto it.
- Run it read-only first, then with an explicit dry run, then for real. A reaper whose default is to kill is the wrong default.

## The prerequisite: a populated management repository

- The reaper's census asks the OS for every process WITH its command line, so a box whose management infrastructure cannot answer that has no automatic reaping at all and needs a human for every orphan fleet.
- One box was in exactly that state from 2026-08-18 to 2026-08-27, which also broke the plain process lister and was the root cause of three reds.
- **Diagnose by COUNT, not by the error** — the error names a symptom that three different remedies all misread as corruption.
- Healthy is roughly 1200 classes; this box read **65**, while the repository verifier reported it CONSISTENT — because it was consistently EMPTY.
- The salvage and reset operations both repair or rebuild CONSISTENCY, which was never the defect, so both reported success and changed nothing.
- The cause was one registry value: the autorecover list had been truncated to **8** entries, and the reset recompiles only what is on that list — so it faithfully and repeatably produced 65 classes.
- The fix is to recompile every definition file by hand, elevated, **with the directory change and the pipeline on ONE line**.
- **The one-line form is load-bearing.** Split across two lines the directory change can land after the pipeline, which compiles five unrelated files elsewhere, prints a wall of successes, and looks exactly like a real run. That happened here once.
- Result: 65 classes to 1198, and the process census went from a class error to 369 processes.
- A few definitions failing is normal — they belong to optional components that are not installed. A definition missing the autorecover pragma is the same defect from the other side: it does not re-enter the list and drops out of the next reset.

## The procedure, when a run has been killed

- Check what survived: count the interpreter processes on the box.
- Run the reaper read-only first; if it REFUSES, a live run is on the box and the right move is to wait or to ask whose it is.
- If it reports that it cannot enumerate the process table, the management repository is the problem and the section above is the fix — **the reaper says so explicitly rather than reaping blind**.
- Never age out or delete a lock whose pid is alive; end the process instead.
- **Bound every wait.** An unbounded loop waiting on a dead thing outlives the thing it waits for.
