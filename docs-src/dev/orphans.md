# Killed runs and orphans

Stopping a wrapper does not stop the run: the test session and its workers survive, keep their memory and may
keep the box's CPU seat. Stop a run with `python -m dev_lab.dev.stoprun --pid <root pid>` (its whole tree,
children first), then list the processes again. Never age out or delete a lock whose holder is alive; end the
holder instead.

## What survives a stop

- A tool-level stop, a closed shell or a timeout on a pipeline ends the CONTROLLER and leaves every worker
  alive. The workers stop advancing but do not exit, and they keep their memory.
- That memory narrows every later run, because worker width is sized from available memory.
- A child reparented away from the root you swept is no longer under it: re-list after every sweep.

## The lock judges liveness, not age

- A lock file records the holder's pid, what it is doing and since when. A dead pid is not a holder, so a
  crashed run leaves at worst a stale file, never a blocked box.
- An orphaned controller that is alive and idle holds the lock legitimately and forever; every run then
  refuses naming it. The remedy is to end the orphan, never to steal the lock.

## What can reap

| tool | what it does |
|---|---|
| a tool-level stop, or closing the shell | ends the wrapper only |
| `python -m dev_lab.dev.stoprun --pid PID [--dry-run]` | stops one identified run and its subtree; refuses a pid that matches no run signature |
| a repo's reaper script | reaps orphans box-wide, and refuses while any live controller exists |

- A reaper decides at the box level: a test process is an orphan only when no live controller is anywhere on
  the box. It refuses even over provable orphans while one is, because reaping a live run's workers voids
  someone's verdict.
- Run a reaper read-only first, then as a dry run, then for real.

## When the process census fails (Windows)

- A reaper needs every process WITH its command line. If the OS management repository cannot answer, there is
  no automatic reaping and every orphan needs a human.
- Diagnose by COUNT: a healthy repository holds roughly 1200 classes. A consistently EMPTY one passes the
  consistency check, so salvage and reset report success and change nothing.
- The fix is to recompile every definition file by hand, elevated, with the directory change and the pipeline
  on ONE line, so the compile cannot run in the wrong directory.

## The procedure after a kill

1. Count the interpreter processes on the box.
2. Run the reaper read-only. If it refuses, a live run exists: wait, or ask whose it is.
3. If it cannot enumerate the process table, fix the management repository first.
4. Stop orphans by root pid; re-list until none remain.
5. Bound every wait: an unbounded loop outlives the thing it waits for.
