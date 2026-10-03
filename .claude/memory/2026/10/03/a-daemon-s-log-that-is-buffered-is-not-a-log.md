---
name: a-daemon-s-log-that-is-buffered-is-not-a-log
description: emit does not flush by default, which is right for a command that exits and wrong for one that never does. The supervisor's journal output was invisible until the process died, and the flush timestamps read as cycle times for an hour.
metadata:
  type: project
created: 2026-10-03
accessed: 2026-10-03
---

# A daemon's log that is buffered is not a log

`lab_commons.log.emit` has `flush: bool = False`. That default is correct for what it was written
for: a command that exits, where the interpreter flushes everything on the way out.

The supervision daemon does not exit. Its stdout is a pipe to the journal, so Python block-buffers
it — 8 KB. The daemon writes **one short line per cycle, every five minutes**. That buffer is days
from filling.

## How it presented, and why it cost an hour

The journal showed a `supervise:` line at 22:40:00, another at 22:48:48, another at 22:58:35 — every
one of them **in the same second as a "Stopping"**. Those looked exactly like cycle times. Read that
way, the daemon was cycling every ten minutes instead of five, and then it stopped cycling
altogether: no line for seventeen minutes, while `ps` said the process was alive with 0:00 of CPU.

The whole diagnosis that followed was reading a daemon that was working perfectly:

* a `py-spy` dump showed the main thread in `stop.wait(self.interval())` — the *inter-cycle sleep*,
  which is where a healthy daemon spends nearly all its time;
* `/proc` showed no child processes, which read as "not waiting on a subprocess" rather than "between
  cycles";
* CPU time of `00:00:00` read as "it has done nothing" rather than "its work is subprocesses".

The one fact that broke it open: the lines appeared **only** at restarts. A restart was the only
thing that flushed them.

## The damage is worse than a missing log

A supervisor whose output is buffered is **indistinguishable from one that never ran** — which is the
single question its logging exists to answer. It is the same failure as having no alerting at all,
arriving through a different door: the machinery is present, correct, and silent.

## The fix

`flush=True` at both of the daemon's emit sites, with the reason written beside them. The CLI's two
sites do not need it — it exits, and exit flushes.

The general rule this belongs to: **any `emit` from a process that does not exit promptly must
flush.** `flush=False` is the right default for the library; it is the wrong default for every
long-running caller, and a caller that forgets gets a log that appears only when it is too late to
be useful.

The regression test patches the daemon's `emit` and asserts `flush=True` was passed — a property of
the call, not of the output, because the output looks identical either way until the process dies.
