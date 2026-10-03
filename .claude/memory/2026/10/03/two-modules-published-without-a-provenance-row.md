---
name: two-modules-published-without-a-provenance-row
description: collectcensus and ruffwaivers were published by the census refactor with no row in PROVENANCE, and the ratchet refused them. The right kind was decided by facts — git rename detection for one, two live delegating importers for the other — not by which wording read better.
created: 2026-10-03
accessed: 2026-10-03
---

# Two modules published without a provenance row (2026-10-03)

`test_every_published_kit_module_declares_its_provenance` was red in the commit that stopped this
repo holding consumers' rows: `collectcensus` and `ruffwaivers` were published and neither got a row.
A published module with no row is exactly what `_provenance_rows.py`'s ratchet exists to refuse —
*"a published module with no row reds, and a row naming no module reds too"*.

## The kind is a factual question, and there are two deciders

The registry offers three kinds. The difference that matters is between the two that are not
`original`, and neither was chosen by which sentence I could write:

* **`collectcensus` SUPERSEDES `tests/_collect_census.py`** — because `git show -M --name-status`
  records `R052 tests/_collect_census.py -> src/lab_commons/dev/collectcensus.py`. The file did not
  sprout a sibling; it *moved*, and the path in the row is the one it left. Its rows half,
  `tests/_collect_census_rows.py`, STAYED and is this repo's own row.
* **`ruffwaivers` is ADOPTED_BY**, not `supersedes` — because both files that used to hold its
  reading still exist and both import from it today (`tests/_config_census.py` kept its placement
  machinery, `tests/test_a_waiver_wider_than_an_ignore_is_declared.py` kept its floors and its bar).
  A `supersedes` row would have named two files that keep every line they have, which is the
  over-claim `adopted_by` was added to make unavailable.

**Run `git show -M --name-status` before writing a provenance row.** The rename detector answers the
`supersedes`-or-not question directly, and the answer is not recoverable from the module's docstring:
prose that names a file names it for both reasons at once.
