---
name: A partial collection must not become a workflow manifest
description: Tests-first checkpoint for collection exit integrity; semantic execution is pending.
metadata:
  type: project
---

At public integration `1c5684b4518a0f394dacc81a0f2a7323c3f77491`,
`jobparts.pytest_collector` parses stdout without checking subprocess exit status.
This checkpoint adds nine controls in `tests/test_dev_jobparts.py`: five failed
partial collections must not print a matrix, exit 5 with IDs must not mean an
empty collection, and successful or genuinely empty resource probes retain their
original results. This is linked to the architecture audit umbrella issue #599.

Production is unchanged: `src/dev_lab/dev/jobparts.py` blob remains
`494761442a6629a12cff69d631cd78e9f91b5dd0`. No semantic RED has been obtained.
The canonical full-file request used
`python -m dev_lab.dev.verify --lock-wait '20 min' -- tests/test_dev_jobparts.py`.
It first reported two E501 errors and formatting differences, then remained
queued for its unchanged 1 GB claim. Its exact owned verify subtree was checked
with fresh process identities and stopped using ordinary `stoprun` dry-run and
execution. The wrapper terminated with exit 1; pytest executed zero items.
This was INTERRUPTED, not a semantic test failure. Mechanical formatting then
completed, and Ruff check passed. Hosted full-file execution is the next door;
production must not change before actual semantic RED.

Canonical frozen bootstrap completed before editing, moving environment identity
`b1f371f11d1d5b8c` to `cc01d403bbc2929f`; lab-commons moved to `50a403422`.
An initial request for nonexistent extra `dev` was refused by name. The supported
bootstrap without that extra selected this repository's declared test/ops extras.

Empty matrix output alone has not been shown to produce PASS: `part_of` already
rejects empty covered cells. Whether a sentinel-only corpus can conceal missing
repository tests remains unverified and is not asserted as a defect here.
All existing owner controls remain intact; worker, memory and wall policy did
not change. This is an incomplete tests-first checkpoint, not a completed fix.
