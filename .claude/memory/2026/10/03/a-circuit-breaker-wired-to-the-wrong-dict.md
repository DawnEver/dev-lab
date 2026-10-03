---
name: a-circuit-breaker-wired-to-the-wrong-dict
description: A component's check was handed state['components'][component] and its action a shared state['components']['actions']. So the deploy component read its history out of one dict and wrote the snapshot into another — and the escalation that was supposed to fire after repeated failures could never fire at all.
metadata:
  type: project
created: 2026-10-03
accessed: 2026-10-03
---

# A circuit breaker wired to the wrong dict

The loop handed a component's **check** `state['components'][component.name]` and its **action**
`state['components']['actions']` — a slice shared by every acting component, on the reasoning that
"several components may share an action". The deploy component's check and its action therefore
looked at two different dictionaries, and both halves failed quietly.

## The visible half

`Deploy.check` reads its deployment history from its slice; `_deploy` records the verified snapshot
into the other one. So `check` never saw a verified release, and `no_verified_release` —
*"a failure could not be rolled back"* — warned on every cycle against a target that had deployed
successfully twenty minutes earlier. On the host it was measured doing exactly that: the snapshot
was in the state file, correct, and the check reporting that no release had ever been verified.

## The half that mattered

`failure_streak(ctx.state, wanted)` counts how many times a release has failed, and `check` reads it
to decide whether to escalate. The failures were being recorded by the action, into the other dict.

**A release could fail every cycle for as long as it liked and the count stayed zero.** The
escalation the operator explicitly asked for — *"do not blacklist it, but tell me when it has now
failed five times"* — could not fire, because the number it fires on was being written somewhere it
never read. Retrying forever with no escalation is not the feature that was specified; it is the
feature with its alarm removed.

It was invisible for the same reason the rest of this lane's defects were: the supervisor reported
`DEGRADED` with the right anomaly names, and an anomaly that is *listed* looks handled.

## The fix, and the rule it belongs to

One component, one slice. The loop already resolves which component declares a chain for an anomaly
kind, because the config had to be scoped the same way; the slice now comes from the same lookup. A
chain declared by a configuration override has no owning component and keeps the shared slice, which
is what having no owner means.

The rule: **state that two halves of one component have to agree about belongs in one place.** The
slice split was justified by a case that does not exist — no two components share an action in this
tree — and the cost was paid by the one component that acts.

## Why the test that would have caught it did not exist

Every test drove either a check or an action. Nothing asserted that they were looking at the same
state, because the defect is a *relationship between two call sites* rather than a behaviour of
either. The regression test now writes a marker in the check and asserts the action can see it,
which is the property rather than the mechanism.
