# Testing — the partition and the discipline

- The tiers, walls and verdict model are on [the verdict model](verdict-model.md); this page is what the tests are and how they are classified.
- Before committing, run the repo's formatter FIRST: a format hook that rewrites files and exits non-zero turns every commit into an add-and-commit-twice loop when formatting happens at staging time.

## The lightweight / heavy partition

- **Opt-in groups are GONE, and tiers replaced them.** A tier that needs a flag to be run has nothing to opt into, and a group nothing runs rots into a false green — a skip is green.
- Measured in motronics-studio: 24 files sat hidden behind an unset variable; of the three old opt-in groups, two had never been run, and both first runs found real defects — one a plain type error that could only survive because the line had never executed.
- The runner selects by MARKER, not by flag: the lightweight tiers deselect the heavy marker and the heavy tier deselects nothing.
- **The heavy partition is DECLARED as data** — a test is heavy by PATH or by an explicit marker, and a collection hook makes the classification visible to the marker expression. A test that lives in a heavy subtree but drives nothing heavy is carved back out by name, so a lightweight tier does not go blind to the exact module being refactored.
- Live vendor tools run only in the heavy tier.

## xfail, never skip

- A known-failing combination is recorded as an xfail with the MEASURED residual in its reason.
- Strict when it is stable-but-off, so an unexpected pass reds and forces the entry out when it is fixed; non-strict when it is operating-point-dependent.
- A skip is only for a genuinely missing environment or a capability that cannot run, never to hide a correctness failure.
- **The xfail list is the distance-to-done; its terminal state is empty.**
- A repo declares the skips it allows as a NAMED SET rather than a count, and the ratchet is two-sided: an undeclared skip reds, and a declared skip that has gone reds too, so the set can only shrink. `lab_commons.dev.reports` reads the allowance out of the project's own configuration.

## Concurrency

- **One test session at a time, machine-wide**, and the hazard is the SESSION rather than the tier: a serial run is not "small".
- Four lanes once obeyed "never run a full gate" by running 274 tests serially, a slow integration test, and two single files — none of them a gate — and the box hit 54 python processes until the serial gate they were protecting lost a worker and blocked forever waiting on it.
- The lock is held by the runner for EVERY tier and a second run is REFUSED and told who holds the box; `lab_commons.dev.boxlock` is the shared implementation.
- Independent vendor tools MAY run concurrently where a repo has measured that they can; the per-vendor grouping bounds RAM and a vendor's unclassified error class, not a box-wide serialization.
- When lanes fan out, they do the non-pytest work — static reading, standalone probes with the import path set, direct lint runs — until the lock frees; the full discipline is on [fan-out](fanout.md).
