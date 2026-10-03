---
name: the-supervisors-children-can-notify-and-must-not
description: A supervisor's child processes inherit NOTIFY_SOCKET and at least one of them sends sd_notify. NotifyAccess=main (systemd's default for Type=notify) REJECTS them, which is the only reason the watchdog still means anything — NotifyAccess=all would let a subprocess satisfy the supervisor's own check-in.
created: 2026-10-03
accessed: 2026-10-03
---

# The supervisor's children can notify, and must not (2026-10-03)

Found the moment the watchdog went live on the host, in the journal:

```
wdg-lab-watchd.service: Got notification message from PID 301375, but reception only permitted for main PID 301211
wdg-lab-watchd.service: Got notification message from PID 301389, but reception only permitted for main PID 301211
wdg-lab-watchd.service: Got notification message from PID 301390, but reception only permitted for main PID 301211
wdg-lab-watchd.service: Got notification message from PID 301544, but reception only permitted for main PID 301211
```

Every one is a **child** of the main PID, and they cluster inside a deploy cycle — the window where the
supervisor forks `git`, `uv`, `systemd-run` and the candidate process.

## Why it happens

`systemd` puts `$NOTIFY_SOCKET` in the service's environment. **Every process the service forks
inherits it**, and `systemd-run --scope` deliberately runs its command inside the CALLER's cgroup — so
a child of the supervisor is, to systemd, part of `wdg-lab-watchd.service`. Anything in that chain
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

## The hardening this points at, and why it is not in this edit

**Strip `NOTIFY_SOCKET` from the environment handed to every child.** The kit owns every fork
(`process/systemd.py`), so one place removes the whole class rather than naming one offender -- and
naming the offender is not something the journal could settle: the message records the pid, and the
pid is gone by the time anybody looks.

It is left as a named next step rather than a rushed one because the exposure is currently CLOSED by
the default, and a change to how the supervisor builds child environments deserves its own deploy with
its own verification, not a tail-end edit.
