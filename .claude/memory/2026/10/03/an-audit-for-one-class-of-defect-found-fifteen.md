---
name: an-audit-for-one-class-of-defect-found-fifteen
description: The supervise package was audited for a single class — a failure reported as success, or as nothing at all — and yielded fifteen instances across twenty-five modules, every one of them reachable. Five were found by using it; ten by looking for the shape.
metadata:
  type: project
created: 2026-10-03
accessed: 2026-10-03
---

# An audit for one class of defect found fifteen

The `supervise` package was built and then pointed at a real host, and in one day **five** defects
surfaced — each only after the previous one was cleared, and each of the same shape:

> a failure that reads as a legitimate empty answer.

A deadlock (a target that had never deployed could never deploy), a config handed to the wrong
party, an unflushed daemon log, a fetch that failed and reported "no release", and a circuit breaker
counting failures recorded in a dictionary it never read. Five instances of one idea, found the hard
way, one production cycle at a time.

So the package was audited **for that idea rather than for bugs**. Two passes over all twenty-five
modules, one asking "where does a failure become a success or a silence", one asking "what grows
without bound". They found **fifteen more**, every one reachable.

## The shape, stated once

It is worth naming because it is not any of the individual bugs:

* a function returns `None`, `[]`, `False` or `0` for two different facts — "I could not find out"
  and "the answer is genuinely nothing" — and the caller reads both as the second;
* a bare `except` returns a default;
* a boolean is returned to a caller that discards it;
* an early `return` skips work the operator needed to know was skipped.

Four of the fifteen were **documented as intended and implemented as the opposite**. The remedy
fallback named an action no component declares, and its own docstring said it existed so an
unhandled anomaly would be "recorded rather than silently dropped". `Outcome.tried`'s docstring
explained that recording the wrong release "would make the circuit breaker count the wrong thing and
never reach its threshold" — and the rollback path never read it. `ProgressTracker`'s test docstring
said "no reading is not no progress" and its assertions recorded `ops_done = 0.0` with no anomaly.
`SCHEMA_VERSION`'s docstring said the version check exists "so a future change to the shape is
something a run can DETECT" — and detection discarded the document without a word.

**A sentence that states the right intent and code that does the opposite is worse than neither**:
the sentence is what a reader checks, and having checked it they stop.

## Two of them had a guard, and the guard was the defect

`test_the_backend_starts_without_the_3d_stack` blocked `OCP` and passed while `scipy` went through
it — a guard that names one absent package tests one absent package. The `UNCONFIGURED` refusal
tested a config that disables all eight components, an arrangement nobody writes, and had **no test
at all**; the arrangement that happens is a config with no sections, and it reported `HEALTHY` over
a supervisor watching nothing.

The lesson is not "write more tests". It is that **an arm whose condition is a shape nobody
produces is dead code with a green light over it**, and the way to find one is to ask what the arm
would need in order to fire, then ask whether anything ever looks like that.

## What the second pass found that the first would not have

Not more of the same: an HTTP body read to EOF with a socket timeout that does not bound it (a
response size is an allocation, and the supervisor's job on a 1.6 GB host is to survive the service
misbehaving); a cycle journal that grows one record per five minutes forever with no ring, read
whole by the digest — the one thing in the package whose size is a function of uptime, in a package
whose state module docstring names its predecessor's growing log ring as a defect it exists to fix.

## The count, and the honest part

`state.py`'s containers are all bounded — anomalies, remedies, failures, releases, component slices
— and the second pass says so explicitly rather than padding the list. The thread pool's
`shutdown(wait=False)` is not a leak in normal operation either; it becomes one only if a check
hangs forever, which is what the unbounded read enabled, and the two are now bounded together.

Fifteen. Five found by running it, ten by looking for the shape. **The ratio is the finding**: the
shape is cheap to search for and expensive to be surprised by.
