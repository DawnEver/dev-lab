---
name: the-kit-grew-an-operational-tier
description: lab_commons.supervise lands as a tier-2 subpackage — the general-purpose supervision machine that was trapped inside a Claude Code plugin's distribution channel, rewritten rather than moved, with zero new runtime dependencies and the module floor re-taken.
metadata:
  type: project
created: 2026-10-03
accessed: 2026-10-03
---

# The kit grew an operational tier

A Claude Code plugin named `watch` had been carrying four layers, and only two of them were Claude's.
Its `watchd` daemon and its whole `core/` — alert transport, state, configuration, atomic write,
file locking, remediation — say so in their own docstrings: *"No Claude Code dependency, survives
session restarts."* A general-purpose supervision machine was being distributed through a channel
that made sense for none of it, with three consequences that were each independently disqualifying:

* **It could not be installed where it was needed.** The host it supervised reached it by hand.
* Its atomic write, locking, logging and configuration conventions had **forked from the family's**,
  which already has all four one layer down.
* It admitted in its own notes that its state lived in **three files** whose keys did not even agree
  on a naming scheme.

## The layer model, and where each fact now lives

```
layer 3  project        consumer-a            config.toml, unit names, ports, probe list
layer 2  Claude adapter cc-market/watch       commands / hooks / skills. No logic
layer 1  the machine    lab_commons.supervise transport / state / config / probe protocol /
                                              ProcessManager / release algebra
layer 0  the base       lab_commons (already) log, paths, file_io, units, exceptions, em
```

Layer 0 was **not re-implemented**, and the first thing the plan got wrong was assuming it could be
reused as-is. Two measurements overturned it: `em` is a single module rather than a subpackage (so
the structural precedent is `dev/`, tier 3), and `file_io` holds TOML read/write and **no atomic
write at all** — `save_toml` truncates in place, with no `os.replace` and no lock.

So the two primitives came from where they actually were. Atomic publication reuses the private
`_records.stage` / `publish` pair, which stages a temp file **in the destination's own directory**
because *"publishing is a link and a replace, and neither can cross a filesystem."* Mutual exclusion
uses `resources.Broker`, tier 1, whose algebra is declared-capacity admission rather than an advisory
lock — and whose docstring carries the rule that decided the design: *"staleness is asked of the OS,
never of a clock."* That rule is why the predecessor's pid file was **not** carried over. A pid file
is a second definition of the same thing, which `dev/boxlock.py` refuses in as many words.

## Zero new runtime dependencies, and it was not a preference

`test_arch_dependencies.py` pins `RUNTIME_DEPENDENCIES` as a two-sided exact frozenset, so one
third-party import anywhere under `src/` reds it. TOML reuses `rtoml`; HTTP and the two webhook-shaped
channels use stdlib `http.client`; SMTP uses stdlib `smtplib`; `psutil` and `resend` are **lazily
imported optional extras** and are not in the set. That the figure came out at zero rather than
"small" is what kept a cross-family decision off this lane.

## The floor was re-taken, the headroom was not

Twelve modules landed, and the arm that counts them said so: `MODULE_FLOOR = 95` with `45` of
headroom admits `[95, 140]`, and the tree now holds 149 tracked modules. The floor moved to 119 —
the same ~80% both earlier readings used — and **the headroom stayed at 45**, because widening it is
the move that guard's own docstring calls giving up the arm to keep it.

The reading is recorded as the measurement of the day the package became **visible**, not the day it
was written: `source_modules()` walks tracked files, so while the package was untracked the guard
could not see twelve new modules and stayed green.

## What was deliberately not carried over

The predecessor's eight self-admitted defects were refusals, not bugs to port: three-way split state,
a remedy chain declared in two places, anomaly counting duplicated between daemon and loop, a single
point of known-good, an HTTP probe that never checked the status code, an unlocked ring rewrite, and
a heartbeat that is not a real dead-man switch. Each is a shape this package does not have, and the
one that is worth naming is the last: the host answers it with systemd `Restart=always`, because
a supervisor that must be supervised is a second thing to keep alive.
