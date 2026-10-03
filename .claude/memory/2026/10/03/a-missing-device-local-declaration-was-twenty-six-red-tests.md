---
name: a-missing-device-local-declaration-was-twenty-six-red-tests
description: Twenty-six census failures across nine test modules were one unset environment variable, LAB_COMMONS_SIBLINGS. The published tree names its consumers neutrally and cannot know where a box keeps them, so the box declares it — and the mapping is derivable from evidence in the tree rather than guessable.
created: 2026-10-03
accessed: 2026-10-03
---

# A missing device-local declaration was twenty-six red tests (2026-10-03)

`pytest tests/` in this tree was **26 failed, 2588 passed**. Every one of the 26 was the same
sentence: *"fewer than 3 repos reached, so nothing below is a family measurement"*, *"no consumer is
checked out beside this repo"*, *"only ['lab-commons'] readable; this arm measured nothing"*.

**Not one of them was a defect.** `doorcensus.sibling_paths`'s own docstring says it: *"This tree is
published, so it names its consumers neutrally and cannot know where a given box keeps them. The box
supplies that, outside the tree."* The variable is `LAB_COMMONS_SIBLINGS`, a `name=path,...` map, and
it was unset.

## The mapping is derivable, and that is not the same as guessing

I had refused to supply it earlier, on the ground that a wrong map yields confidently-wrong readings.
That refusal was right about the *risk* and wrong about the *method*: the tree records enough to
identify each consumer, and the test run confirms it.

| neutral | derived from |
|---|---|
| `consumer-a` | the only checkout with `scripts/gate/`, `scripts/repo/` and `tests/architecture/layering/` |
| `consumer-b` | `_config_census_rows.py` says it is "NOT a direct sibling: the family root groups it under an org directory", and `netverb`'s row names `scripts/pull_all.py`, which exists in exactly one candidate |
| `consumer-c` | the remaining direct sibling |
| not a member | the candidate that never names `lab-commons` anywhere |

With the map set, the **whole suite passes: 2614 passed, 0 failed.** A wrong mapping does not
produce a green run — the censuses re-measure by equality in both directions — so the green is the
confirmation.

**The lesson is about where a fact belongs.** A device-local fact that a published tree genuinely
cannot hold is not a defect in the tree; it is a defect in the *run* when nobody supplies it. What
made it cost 26 red lines for as long as it did is that the failures all read as findings.
