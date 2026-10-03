---
name: thirty-two-signatures-and-one-other-was-a-container
description: After the log-scan defect was found by reading a live host, every signature in the kit was audited — thirty-two of them. One other named a container (a process exit code), and two that look wrong are recorded as sound because the reasoning is not obvious.
created: 2026-10-03
accessed: 2026-10-03
---

# Thirty-two signatures, and one other was a container (2026-10-03)

The log-scan defect (`a-signature-that-named-the-container-not-the-condition.md`) was found by reading
a live host's state, not by a test. The obvious next question is how many OTHER signatures in this kit
are taken from a container. `grep -rn 'signature=' src/lab_commons/supervise/` answers it in one line:
**thirty-two sites, and one other was wrong.**

## The one

`ShellProbe` signed a failure `f'{name}:{ran.code}'` while computing `ran.detail()` **for the message
right beside it**.

`Ran.code` is the coarsest container in the kit: it is `-1` for a **timeout**, a command that **could
not be run at all** and an **`OSError`** alike — three different facts under one value. Two failures
that both exit `1` for different reasons collide just as completely. And the policy writes a condition
off by signature, so each of those pairs made the second failure inherit the first one's silence.

Fix: `f'{name}:{ran.code}:{condition_digest(ran.detail())}'`.

## What the sweep bought besides the fix

`condition_digest` moved to `verdict.py`, beside the `Anomaly.signature` field it is the meaning of,
so the two callers share one definition instead of two. Folded numbers, for the reason recorded there.

**Two sites look wrong and are not, and they are the useful part of the result:**

* `HttpHealth` signs `f'{name}:{status}'`. A 503 becoming a 500 IS reported (the signature moves); a
  changing body under one status is NOT. That is the right call — the reader already knows the
  endpoint is broken, and retelling every body change is exactly the noise that teaches a reader to
  ignore the channel.
* `ShellProbe`'s stall arm signs `f'{name}:stale:{value}'` where the value is **by definition unmoved
  while the anomaly fires** — the count only rises when `previous == value`. Stable by construction.

## The general question, which is what to carry forward

For every signature: **would a reader want to be told again when X changes?** If yes, X belongs in the
signature. If retelling it would be noise, X is a container and belongs in the message. A signature
that fails the first half goes silent on a new failure; one that fails the second half is an alert
storm. Both are the same mistake — putting the wrong thing in the field.
