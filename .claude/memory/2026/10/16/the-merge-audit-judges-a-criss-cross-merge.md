---
name: the-merge-audit-judges-a-criss-cross-merge
description: mergeaudit refused any merge with 2+ merge bases before reading trailers, so a downstream integration (lane <- integrate/main after each had merged the other) could not be committed; the refusal is gone and several bases fold per test into one base (agreeing bases give that body, disagreeing give none), so a criss-cross is audited like any merge
created: 2026-10-16
---
# The merge audit judges a criss-cross merge (2026-10-16)

## Cause
`_audit` raised `N merge bases (a criss-cross) -- merge through one integration branch instead` before
reading any trailer. A downstream integration -- the merge the integrator rule ("merge, never rebase")
produces every time after the first -- has two bases, so it was uncommittable.

## Rule now
The audit's question (MERGE-DEVIATIONS-NAMED) is about the parents and the result; the base only refines
it -- it is what tells one side's deliberate deletion/edit from a resolution that dropped or reverted it,
a real distinction the existing tests pin, so it stays. `common_base` folds every merge base per test:
bases agreeing on a test give it that body, disagreeing ones give a sentinel equal to no parent body, so
such a test expects a body only where both parents hold the same one (else CONFLICTED). One base is the
old behaviour exactly.

## Tests
`tests/test_dev_mergeaudit.py`: a real temp repo builds a criss-cross; an unnamed LOST test is refused,
the named one passes, a clean criss-cross audits clean; the single-base end-to-end tests are the control.
