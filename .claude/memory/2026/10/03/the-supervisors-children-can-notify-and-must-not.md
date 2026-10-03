---
name: the-supervisors-children-can-notify-and-must-not
description: A supervisor's child processes inherit NOTIFY_SOCKET and at least one of them sends sd_notify. NotifyAccess=main (systemd's default for Type=notify) REJECTS them, which is the only reason the watchdog still means anything — NotifyAccess=all would let a subprocess satisfy the supervisor's own check-in.
created: 2026-10-03
accessed: 2026-10-03
---

# The supervisor's children can notify, and must not (2026-10-03)

Found the moment the watchdog went live on the host, in the journal:

```
<the unit>: Got notification message from PID 301375, but reception only permitted for main PID 301211
<the unit>: Got notification message from PID 301389, but reception only permitted for main PID 301211
<the unit>: Got notification message from PID 301390, but reception only permitted for main PID 301211
<the unit>: Got notification message from PID 301544, but reception only permitted for main PID 301211
```

**THE UNIT NAME IS ELIDED ON PURPOSE, AND THE REASON IS THIS FILE'S OWN SUBJECT.** The journal
line begins with the deployed service's name, and that name is the ADOPTING project's -- it does not
belong in a tree that ships to all of them. Writing it in full is what I did first, and the
private-marker guard rejected the file within the minute; the elision is the guard's remedy and not a
tidying. **Second time in one session** that a memory entry of mine carried a consumer's name into a
published tree, both caught by the same guard, which is the argument for having one rather than for
being careful.

Every one is a **child** of the main PID, and they cluster inside a deploy cycle — the window where the
supervisor forks `git`, `uv`, `systemd-run` and the candidate process.

## Why it happens

`systemd` puts `$NOTIFY_SOCKET` in the service's environment. **Every process the service forks
inherits it**, and `systemd-run --scope` deliberately runs its command inside the CALLER's cgroup — so
a child of the supervisor is, to systemd, part of the supervisor's own unit. Anything in that chain
that speaks the notify protocol is therefore talking AS THE SUPERVISOR.

## Why it is SAFE today, and why that is fragile

`NotifyAccess=main` is systemd's default for `Type=notify`, and it rejects a message from any pid but
the main one. That is the only reason the messages are noise instead of a defect.

**`NotifyAccess=all` WOULD BREAK THE WATCHDOG, AND IT IS THE SETTING SOMEBODY WOULD REACH FOR.**
"Allow notifications from anywhere in the service" reads as the permissive, safe choice. On a unit
that forks -- and every component of this supervisor forks, by design, through `run_capped` and
`start_capped` -- it means **a subprocess can send `WATCHDOG=1` or `READY=1` on the supervisor's
behalf**. The check-in that exists to prove the DAEMON is still working would be satisfiable by a
command it spawned, which is not a watchdog at all.

So: `NotifyAccess=main` is load-bearing and must not be widened. That is the finding.

## The hardening, and where it went

**Strip `NOTIFY_SOCKET` from the environment handed to every child.** The kit owns every fork
(`process/systemd.py`), so one place removes the whole class rather than naming one offender -- and
naming the offender is not something the journal could settle: the message records the pid, and the
pid is gone by the time anybody looks.

**DONE, in its own commit and its own deploy** (`subprocess_runner` now filters the variable out of
the environment it hands to `subprocess.run`). It was held back from the edit that found the problem
because the exposure was closed by the default at the time, and because changing how the supervisor
builds child environments is not a tail-end edit.

Two things about where it landed:

- **The kit's own `systemd-run --scope` calls go through the same runner**, so a candidate build
  loses the variable too. That is correct -- a candidate is not the supervisor -- and it is the
  reason the fix belongs in the runner rather than in a caller.
- **The supervisor's OWN check-in is unaffected, and that is a property of the design rather than a
  coincidence.** `notify.ready()` and `notify.watchdog()` read `os.environ` in the supervisor's own
  process; only children go through `subprocess_runner`. A fix that had stripped the variable
  process-wide would have disarmed the watchdog it exists to protect.
