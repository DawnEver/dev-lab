---
name: the-ceiling-is-two-numbers-and-the-fourth-roster-is-the-one-that-says-so
description: Half 4 of the family config tranche landed as lab_commons.dev.famtests.placement, measured across all FOUR rosters rather than the two the previous session could read. The reading that changes the design - three rosters bound their own-mechanism ceiling at 50 and motronics' scripts roster bounds it at 40, over intervals that EXCLUDE each other's value - so neither bar ships as a constant and what ships is the arm that holds a bar inside its own evidence.
created: 2026-09-18
accessed: 2026-09-18
---

# The ceiling is two numbers, and the fourth roster is the one that says so

Closes `2026/09/17/plan-one-source-of-truth-for-the-family-config-layer.md` stage R4, and answers
`2026/09/18/the-placement-half-is-shaped-and-two-of-its-four-rosters-i-may-not-read.md`.

## The tranche

| half | commit | what |
|---|---|---|
| 1 | `76c64f7` | `famtests.rostercensus` |
| 3 | `4e07cfb` | `dev.floors` |
| 2 | `5bd3c70` | `famtests.datedmemory` |
| 4 | this one | `famtests.density` + `famtests.placement` + `_placement_readings` |

## What the previous session could not see, and what it changed

That session read two of the four rosters, found them to be the same module under two names, and
STOPPED rather than design from half its subject. It was right to. The two it could not read were
motronics-studio's, at `3befb376b` in the `feat/optimi-lab` worktree -- the tree that roster's own
prose quotes -- and the larger of the two is 77 rows.

**THE TWO LABS AGREED ON A NUMBER THAT IS NOT A FAMILY NUMBER.** Both bound
`OWN_MECHANISM_CEILING = 50` independently, and the write-up read that agreement as evidence the
value was family and only the interval was the repo's. motronics' `tests/` roster agrees (50, over
47 < c < 56). motronics' `scripts/` roster bounds the SAME bar at **40**, over 35 < c < 42 --
and the intervals are not merely different, TWO PAIRS OF THEM ARE DISJOINT:

    roster              value   must EXCEED   must fall BELOW
    wdg-lab               50       49            55
    optimi-lab            50       43            67
    motronics tests       50       47            56
    motronics scripts     40       35            42

`(35, 42)` excludes 50. `(49, 55)` excludes 40. A family half shipping `CEILING = 50` would have
been wrong for one of its four consumers ON THAT CONSUMER'S OWN MEASUREMENT, and wrong in the
admitting direction, which is the silent one: a ceiling set too high lets rows through instead of
refusing them. Two of four would have produced exactly the guessed answer this tranche is about.

The density minimum is the opposite reading and is worth as much: all four bound `3.0`, their
intervals INTERSECT in `(2.54, 3.06]`, and 3.0 sits inside it. Four independent measurements of one
number is real evidence the bar is a family property.

**Neither ships as a constant.** Publishing 3.0 would delete the evidence and replace it with a
copy -- the fifth repo would inherit a number nothing measured against its files, which is precisely
what the ceiling row shows going wrong. What ships is `assert_ceiling_is_bounded` and
`assert_minimum_is_bounded`, which take the repo's value WITH the two measured readings that bracket
it. All four rosters wrote that bracket as a pair of rows in a COMMENT, where nothing could check it
-- and a comment is exactly where a bar quietly widens to absorb the row that reds.

## The boundary, reported before the module

Family, 4 of 4 and verbatim: the AST+token prose blanker, the delegation reading that makes a binder
legible, `own`/`hits` and its percentage, the walk, and the completeness comparison in both
directions. The labs' bodies differ from motronics' only by carrying ONE delegation home where
motronics carries a SET, and ONE hit signal where motronics carries TWO. Both generalisations went
into the signatures rather than into a branch.

NOT family, each with the count that decided it:

* **The partition composer** (merge per-subdirectory manifests, raise on a collision and on a row
  outside its partition). 2 of 4, and both are motronics. One repo's answer written twice is not a
  family fact.
* **The non-Python reading.** Three answers in four rosters: wdg-lab reads a shell file WHOLE,
  motronics strips whole-line comments and calls that its code-only reading, optimi-lab has none.
* **The `pytest.param` construction.** 4 of 4, and four lines over a mapping the repo owns. This
  package publishes assertion BODIES, never a parametrize helper.
* **The bars, the nouns, the trees, the floor, the debt rows.** Data, 4 of 4 different.

## Three defects the four-way read found that a two-way read could not

* **`Density.justified` closes over whichever module it was imported from**, and motronics already
  paid for it: its tests roster had to write `is_justified` out by hand because the inherited
  property closed over the `scripts/` roster's 40 while the tests module DECLARED 50, so tests-tree
  rows were judged by a bar bounded on a different tree. Two rows read between the two ceilings and
  caught it. The published `Density` has no `justified`; `justified(density, *, ceiling, minimum_pct)`
  takes them.
* **optimi-lab declares `.sh` runnable, holds zero of them, and has no shell arm.** The day one
  arrives its `stays_rows` hands it to `ast.parse` and the guard ERRORS rather than fails -- an
  error carries no measurement at all. wdg-lab closed this with the named set `SHELL_ROWS` and
  motronics with `is_python`; optimi-lab is the 1 of 4 with a live latent hole.
* **No roster checks its DEBT mapping against its own manifest.** Every one records below-the-bar
  rows as a named set and strict-xfails them, so a row that starts passing must be deleted. None
  checks the other direction: a debt row whose FILE is gone describes nothing, still reads as a live
  shortfall, and its strict xfail can NEVER fire, because the parametrize that would have run it no
  longer has the row. `assert_no_stale_debt` is the half nobody wrote.

## The empty declaration, and which side it is on

`datedmemory`'s, not `rostercensus`'s. An empty debt mapping means every `STAYS` and `SPLITS` row
clears both bars -- the state the ratchet exists to REACH -- so refusing it would make the fixed
state unreachable. The vacuity is closed by the walk's floor instead, which runs whether the debt is
empty or not. An empty `delegation_homes` is legal for the same reason: a repo that has adopted
nothing from the family yet has a TRUE answer to that question.

## The control had to be split before it could be driven

`assert_the_meter_still_convicts` was written as one function that plants three shapes and judges
them, the way `rostercensus.assert_the_grader_still_convicts` is. Its counter-control could not be
written: the only way to break it from a test is to pass a `delegation_home` the plant does not use,
and the function uses the same argument for both, so it always agrees with itself. **An assertion
nobody has seen fire is a declaration.** So `meter_readings` plants and measures, and
`assert_readings_convict` judges readings it is HANDED -- and the test drives four wrong readings
through it, one defect at a time.

## It is TWO modules, and the module-size band is what asked the question

Written as one, `placement.py` measured 688 raw lines against this repo's 400-line band -- and the
band asked the right question. The seam it forced is the one the measurement already named: the
DENSITY METER is the half that is identical in all four rosters, and the ROSTER ARMS are where the
repo-shaped facts arrive. So `famtests.density` holds the meter (385 lines) and `famtests.placement`
holds the walk, the completeness ratchet and the two bar arms (289). The four rosters' readings went
to `_placement_readings.py` as DATA, which is strictly better than the prose they were: the tests
CONSULT them, so `test_the_family_ceiling_is_two_values` reds if a re-measurement ever dissolves the
disagreement it describes, instead of quietly outliving it.

## Inventory, not mine

`src/lab_commons/dev/famtests/datedmemory.py` is 431 lines against the 400-line band with no
`DEBT` row, so `test_arch_module_size_alarm` is RED at `810c2ef` and was red before this commit --
it landed with half 2 in `5bd3c70`. Not pinned here: pinning a module the day after it lands is the
loosened band arriving through the waiver list, and the fix is the same seam this half just took.

## Floors

`dev.floors` is consumed rather than re-inlined: `assert_every_file_is_placed` binds BOTH sides of
the floor before it compares a single path, because "nothing unplaced" over an EMPTY walk reports
exactly what a fully classified tree reports.
