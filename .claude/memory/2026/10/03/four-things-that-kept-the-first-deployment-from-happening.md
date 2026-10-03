---
name: four-things-that-kept-the-first-deployment-from-happening
description: The supervise deploy engine refused every release for four independent reasons, each hidden behind the last. Includes a rehearsal that passed because it had performed, by hand, the exact step the real code path never performs.
metadata:
  type: project
created: 2026-10-03
accessed: 2026-10-03
---

# Four things that kept the first deployment from happening

Pointed at a real host, the deploy engine refused every release. The causes were independent and
strictly serial — each was only visible after the previous one was cleared — which is why reading the
code, and even rehearsing it, found none of them.

## 1. A deadlock: the first deployment needed a prior deployment

```python
known = history(ctx.state)
if not known:
    result.anomalies.append(no_verified_release)
    return result  # <-- release_available is never reached
```

A snapshot is written by a successful deploy. A deploy runs only on `release_available`. So a target
that had never deployed could never deploy — and the host sat in that state for seven consecutive
cycles, warning `no_verified_release` while a pushed release waited.

The warning says *"no release has been verified, so a failure could not be rolled back."* That is a
statement about the **floor**, not a reason to refuse the one action that can build one. The warning
stays; the early return went. A release is now offered when the remote differs from the baseline, and
the baseline is the newest verified snapshot **or, when there is none, what the checkouts are
running** — without that second baseline either the first release stays invisible or every cycle
redeploys the same commits.

## 2. The action was handed the wrong configuration

`ActionContext` documents `config` as *"this component's own section."* The acting path passed the
**whole components table**. So the deploy component read its section out of a table that did not have
one, built an empty plan, and refused with:

> the deploy plan is incomplete, missing: repositories, unit, health, install, run, probe

— naming six settings that were in the file the whole time. The **check** path was unaffected, which
is the diagnostic shape to recognise: the supervisor could see a release perfectly and was
structurally unable to act on one. A failure whose text names things that are present is a failure in
the layer that read them.

The registry now resolves which component declares a chain for an anomaly kind, and the loop hands
**that** component's section to its action.

## 3. The install door was not on the service's PATH

`uv` had been installed to a per-user location. The operator's shell had it; the systemd unit's
environment did not, so `make install-web` died with `make: uv: No such file or directory`. A
deployment prerequisite that only holds for an interactive login is not a prerequisite. Moving the
binary to a system-wide location fixed it for the sandbox case too, where a non-root service user
cannot traverse another user's home at all.

## 4. The candidate never got a virtual environment

`preflight` starts a candidate with `{candidate}/.venv/bin/python` and **never created that venv**. The
install is `uv pip install -e ".[web]"`, which refuses to run without one:

> No virtual environment found; run `uv venv` to create an environment

`venv` is now a plan field — the command that gives a candidate an environment, run in the candidate
directory before `install`, empty for a target whose install makes its own.

## The methodological part, which is the part worth keeping

**The rehearsal passed.** It had run: worktree, `uv venv --python 3.12`, `make install-web`, prepare,
start on a spare port, probe both endpoints, tear down. Every step succeeded, the candidate answered
200 on `/health/` and `/wdg_toml/list/`, and it was still 125 MB against a 600 MB ceiling.

It was also worthless as a proof, because it performed **by hand the one step the real code path never
performs**. The check was passing a precondition the code under test did not establish. No amount of
repeating that rehearsal would have revealed it, and the more faithful it looked, the more convincing
the wrong answer became.

The general form: *a rehearsal that does not drive the code path under test is measuring the
rehearsal.* The honest rehearsal is the one that runs the entry point, not the steps the entry point
is supposed to run.

A corollary the same session produced: the operator's shell is not the service's environment. Two of
these four were invisible from an SSH session and obvious the moment the daemon ran.
