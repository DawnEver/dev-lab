---
created: 2026-10-15
---
# The sync census pins TEXT, not line numbers

**Incident.** Base on integrate/main 53e67da redded 4 tests in
`tests/test_the_syncs_leave_a_verdict_runnable.py`; d4f14ee was green. The suspected cause (a sibling
repo's doors moving) was WRONG: the test reads only this repo's working tree (`_PATHS` names one repo).
The cause was c6ea5c0 deleting the 6-line `[tool.lab_commons.forge.issue_hygiene]` table from this
repo's own `pyproject.toml`, which shifted the hand-pinned `ScopeRow.line` (257 -> 251) and the
`SITES` key line (330 -> 324). Text unchanged; only positions moved.

**Fix at the source.** The row had been hand-repointed 7 times and the site 5 times, every time for
a position nothing had changed the meaning of. `ScopeRow` lost `line`: its evidence must stand on
EXACTLY ONE line of the file (gone or doubled -> `EvidenceGoneError`). `pruning_sites` returns
`(repo, path, command text)` and `SITES` is keyed by that text. The line-moved plant became a
parametrized gone/ambiguous plant.

**Hermeticity.** Already hermetic: no sibling checkout is read. No seam needed.
**Breaking.** Any consumer constructing `ScopeRow(..., line=...)` or keying sites by line must drop it.
