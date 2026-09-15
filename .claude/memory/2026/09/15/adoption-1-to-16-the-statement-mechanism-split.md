---
name: adoption-1-to-16-the-statement-mechanism-split
description: lab-commons authors the 28 shared rules and adopted 1 of them; splitting each row into a STATEMENT (portable) and a MECHANISM (per-tree, resolved through git ls-files) is what let it build its own mechanisms and reach 16 enforced with 12 named absences, and it is why the absent set is a mapping with reasons rather than a count.
metadata:
  type: project
created: 2026-09-15
accessed: 2026-09-15
---

# The repo that authored the rules was its own worst adopter

`src/lab_commons/dev/rules.py` and `_rule_rows.py` hold 28 development rules that several repos
read. For most of their life this repo enforced exactly ONE of them against its own tree. That is
not an oversight anybody could have seen from the registry: the registry looked complete, because
every row already named the files that enforce it.

They named files in ANOTHER repo. Every mechanism path a row carried -- `tests/architecture/...`,
`scripts/gate/runner.py`, `.claude/hooks/deny-commands.js` -- is a path in motronics-studio. The
module's own docstring promised that "a second adopter inherits the statements and must supply the
mechanism for its own tree" and then offered no way to supply one. Measured 2026-09-15: driven
against its own tree, lab-commons refused its OWN registry with 70 failures.

## The split that fixed it

A rule is two different things wearing one name:

- the **STATEMENT** -- what is true everywhere, and the only part that travels;
- the **MECHANISM** -- the file in THIS tree that refuses a violation, which cannot travel at all.

`Adoption` carries the second half per repo. `assert_adopted` resolves each named mechanism through
`git ls-files`, so a mechanism counts only if the fleet can actually fetch it: a guard that exists
in one working copy is a guarantee nobody else can reproduce, and the check says so rather than
trusting `Path.is_file()`.

With that, the 27 gaps became BUILDABLE rather than describable, and the raise was real work --
`tests/test_arch_*.py`, one guard per statement, each with its own floor and its own planted
control. 16 enforced, 12 declared absent, the ceiling lowered in the same edit.

## What the absent set is FOR, and why it is a mapping

`_ABSENT_REASONS` maps a rule id to a sentence. A bare set would have been cheaper and would have
lost the only thing worth keeping: the absences are not the same KIND of absence, and the repair for
each kind is different.

- **No subject.** `BAR-IS-A-CONSTANT`, `IMPLEMENT-EVERYTHING`, `UNSUPPORTED-RAISES`,
  `RETIRED-NAMES-REGISTERED` -- a library with no solvers has no combination matrix, no acceptance
  bar and nothing to declare unsupported. Nothing to build; building something would be the
  declaration-that-lies.
- **Unbuilt machinery.** A gate runner, a network wrapper, a production entry point. Adoptable, and
  a decision rather than a defect.
- **Unreachable.** `SHARED-CHECKOUT` is a fact about `origin`, not about any file here, so no file
  in this tree can enforce it. The honest record is the absence.
- **VIOLATED.** `TOLERANCE-CARRIES-A-UNIT` was the one to read twice. This repo wrote seven bare
  `pytest.approx` calls with no `abs=` floor, so a guard would have RED on the authoring repo.

That last one carried the sharpest lesson of the raise, and it was a refusal rather than an edit:
the cheap close was to write the guard with those seven pinned as a waived set, which would have
turned the rule green while leaving every violation in place. **A loosened band arriving through the
pin is still a loosened band.** The honest close, done 2026-09-15, was seven real edits -- a floor
per site chosen from the quantity it measures, with the reason in a comment. One of them compared
the vacuum permeability, 1.2566e-6 H/m, against the framework's default `abs=1e-12`: a floor worth
1e-6 of the value, which would have accepted a constant wrong in its seventh digit. The rule's own
inversion, live in the tree that authors it.

## The shape to keep

A statement is portable; a mechanism is not. Anything that reads like a rule but names a path is
half of each, and the half that names the path belongs to exactly one tree. When a registry looks
adopted because its rows are populated, check WHOSE tree the rows point at.
