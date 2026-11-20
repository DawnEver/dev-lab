---
name: Layout enforcement starts with each real producer seam
description: Three tests-first execution plants for the shared layout mechanism; no production implementation.
metadata:
  type: project
---

Umbrella issue #599 owns this work. This checkpoint starts at integration
`a7e65dc59da3ce42142adc25ab763f0eba728928` and changes tests only.
There is no new engine import at collection time and no invented policy schema.
The three plants exercise existing public seams with an explicit family
declaration but deliberately missing layout policy:

- `tests/test_famtests_alwayson.py`: a real git-backed pytester session must
  report a failed required guard, not a collection error or silent absence.
- `tests/test_dev_commandpart.py`: a command that would exit zero must not
  start or post any successful cell when the repository guard fails.
- `tests/test_dev_verifiedby.py`: consumer success must not conceal failure
  of the data repository's own applicable structural guard.

No semantic execution is claimed. Ruff and format checks passed for all three
owners. The next qualification is the complete three files through the existing
hosted measurement door. No local RAM queue was repeated, no production changed,
and no test, worker, memory or wall threshold changed.

The design has one policy/measurement owner, not one scanner per producer.
The planned pure body supplies typed policy, complete expected/read/unread
sets and layout verdicts. Execution adapters must call that same owner from
the existing required pytest item and the command/data producer seams; CI YAML
alone misses other producer routes. CJK's existing scanner must also be reused
for non-pytest producers, not copied. Ordinary non-family/non-repository inputs
must have an explicit applicability boundary and cannot be advertised as guarded.

Remaining tests-first design inventory, pending agreement on the typed policy:
valid and malformed policy, all current line-count units and limits, directory
MUST width 25, depth watch-only, tests/scripts inclusion, exact legitimate
archive/generated/data subject proofs, unreadable/missing subjects, CJK rejection
before a non-Python command, required-item selection, and successful producer
records with distinguishable guard evidence. New valid fake repositories must
declare policy; old fixtures must migrate atomically, not gain fallback waivers.
No grandfather pin or xfail may turn inherited structural violations green.

This checkpoint is not a completed shared guard or full-family qualification.
The pure body and this execution adapter are separately owned design slices;
their schema/API must agree before production is written.
