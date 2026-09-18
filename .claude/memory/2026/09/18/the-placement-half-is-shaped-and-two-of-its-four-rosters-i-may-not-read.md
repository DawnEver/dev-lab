---
name: the-placement-half-is-shaped-and-two-of-its-four-rosters-i-may-not-read
description: Halves 2 and 3 of the family config tranche landed (dev.floors, famtests.datedmemory). Half 4, a placement module, is measured as far as this session could legitimately see it - the two lab rosters are the same mechanism with per-repo calibration prose, but the two motronics rosters were out of bounds, so the half is written down rather than landed.
created: 2026-09-18
accessed: 2026-09-18
---

# The placement half is shaped, and two of its four rosters I may not read

Continues `2026/09/17/plan-one-source-of-truth-for-the-family-config-layer.md`, stage R4, and the
hand-off `2026/09/18/handoff-the-family-config-layer-at-the-quota-wall.md`.

## What landed

| half | commit | what |
|---|---|---|
| 1 (prior session) | `76c64f7` | `famtests.rostercensus` |
| 3 | `4e07cfb` | `dev.floors` |
| 2 | `5bd3c70` | `famtests.datedmemory` |

Neither is pushed; `main` is at `5bd3c70`. `uv.lock` is untracked and was left alone.

## Why half 3 went first

`datedmemory` needs a floor arm, and `floors` is what makes "every scan gets a floor" cheap to
state. Landing the helper first and ADOPTING IT IN THE SAME TRANCHE is what proves it: a module
published and not consumed is the waiver-nothing-uses shape arriving at the moment of publication.

## The floor refusal was forked EIGHT times and only the low side was ever written

Four standalone bodies -- `cjk.assert_floor`, `docwidth.assert_width_floor`,
`famtests/_configrender_readings.assert_floor`, `tests/_arch_corpus.assert_floor` -- raising FOUR
different exception types, and **two of the four are both named `VacuousScan` over different base
classes inside this one repo** (`cjk`'s is a `RuntimeError`, `_arch_corpus`'s an `AssertionError`).
Three more are inlined at the top of a larger arm (`rulespages`, `rostercensus`, `installdoor`).
wdg-lab publishes `bind_floor` and calls it from SEVEN guards; optimi-lab inlines the same assert in
EIGHT with its own prose.

**Every one of the eight guards the LOW side only.** A floor of 180 measured against 208 files still
reads 180 when the tree holds 2000, and by then it refuses a total collapse and passes a walk that
lost nine tenths of its corpus. That is a waiver nothing uses in number form, and
`assert_floor_still_binds` is the side that was missing. The remedy in its refusal is to RE-MEASURE
THE FLOOR, never to widen the headroom.

A COUNT MISLED ME TWICE WHILE WRITING ITS OWN TEST, which is the joke worth keeping. I wrote
`assert len(guessed) < len(honest)` as the counter-control for the exclusion sets; it failed at
`6 < 6`, because excluding the file BY NAME and excluding its DIRECTORY hide the same file and the
totals agree. The repair was to stop comparing counts and name the row. The other one: I claimed
nine and six call sites from reading the grep output rather than counting files, and both were
wrong (seven and eight). Corrected on the record in `5bd3c70` rather than edited quietly.

## `silent` had to be its own population

`datedlog` publishes `date_parts`/`dated_log`, which CONSTRUCT. The waiting rows need to READ. That
much is only a direction. The three measured reasons these do not bolt onto `datedlog`:

* **The layouts are not the same layout.** `dated_log` writes `<base>/<yy>/<mm>/<dd>/<kind>/<name>` --
  a TWO-DIGIT year from `strftime('%y')`, a mandatory `kind`, a repo-chosen `base`. A memory entry is
  `<tree>/<YYYY>/<MM>/<DD>/<name>`. The layout the readers are about is one its neighbour CANNOT
  PRODUCE.
* **The refusals are opposite in kind.** `dated_log` raises on the first bad name. Nothing in
  `datedmemory` raises on an offender: every reader RETURNS THE SET, because both consumers pin
  offenders as a named set and an exception that fires on the first one cannot be pinned, counted or
  ratcheted downward.
* **Only one of them scans**, so only one needs a floor.

optimi-lab folded "no `created:` field" into `date_disagreements` as a reason string; wdg-lab split
it out. The SPLIT ships -- not because one lab was right, but because a pin over a mixture cannot
say which half moved. An undated entry is named ONCE, by the shape reader, or one fix reds two arms.

**And the empty set is ACCEPTED here, unlike `rostercensus`'s waiver.** There an empty waiver meant
the arm had outlived its subject and had to be deleted. Here a tree where every entry dates itself
is the state the ratchet exists to REACH, so refusing the empty declaration would make the fixed
state unreachable. The vacuity is closed by the entry floor instead. Copying a refusal across two
adjacent subjects is how a ratchet acquires a side it should not have.

## HALF 4 -- MEASURED AS FAR AS IT COULD HONESTLY BE, AND NOT LANDED

The session was scoped to read `wdg-lab` and `optimi-lab` and forbidden to touch
`motronics-studio` or its worktrees. **Two of placement's four rosters live there.** So:

    wdg-lab   tests/architecture/_placement.py   961 lines, 31 rows, PLACEMENT_FLOOR 25
    optimi    tests/architecture/_placement.py   785 lines, 23 rows, PLACEMENT_FLOOR 18
    motronics  six partitions, 77 rows            OUT OF BOUNDS THIS SESSION

What the two readable ones say, and it is a strong signal: the MECHANISM halves are the same module
under two names. Same constant names in the same order (`STAYS`/`MOVES`/`SPLITS`, `Placement`,
`SCANNED`, `RUNNABLE_SUFFIXES`, `_NOT_PLACED`, `FAMILY_PACKAGE`, `REPO_NOUNS`, `_NOUN`,
`PLACEMENT_FLOOR`), same functions in the same order (`placed_files`, `nouns_in`, `nouns_in_code`,
`_code_and_delegation`, `Density`, `measure_density`, `stays_rows`). Diffed over the function half
only, 243 of 284 lines differ -- **and nearly every one is a docstring or a `#:` comment carrying
that repo's own calibration reading.** The code underneath is effectively identical.

The repo-shaped facts are already visible and would be the no-default arguments: `REPO_NOUNS`, the
`PLACEMENT` roster itself, `PLACEMENT_FLOOR`, `SCANNED`, `BELOW_THE_BAR`, and wdg-lab's `SHELL_ROWS`
which optimi-lab has no equivalent of.

**THE INTERESTING PART IS THE TWO BARS, and it is the thing a rushed version would flatten.**
`OWN_MECHANISM_CEILING = 50` and `MIN_REPO_DENSITY_PCT = 3.0` are IDENTICAL in both labs -- but each
repo BOUNDED them independently against its own distribution, and the intervals differ: wdg-lab's
ceiling must exceed 49 and fall below 55, optimi-lab's exceed 43 and fall below 67; density above
1.41% / at-or-below 4.79% in wdg-lab, above 0.65% / at-or-below 3.06% in optimi-lab. So the VALUE is
a family constant and the INTERVAL is the repo's evidence for it. A family half that shipped only
the value would delete the evidence; one that shipped only the interval would lose the agreement.
Both have to travel, and the arm is "this repo's measured interval CONTAINS the family value".

### Why it was not landed anyway

Not room -- budget was available. **Evidence access.** Half the subject was unreadable, and the
largest roster is the one I could not see. A family half designed from two of four consumers is the
guessed-answer failure this entire tranche is about, one level up: it would not raise, it would just
be one pair of repos' answer handed to a third and then reported as measured. `LAB_CZ_BASE_REF`,
the stray newline on `@{push}`, and the sub-package import token were all that shape.

**Whoever takes it: read motronics' six `_placement_*` partitions in the LANE worktree FIRST, say
which tree you read** -- the plan records an unresolved 77-vs-71 dispute caused by reading the main
checkout instead of the lane -- then diff the mechanism halves across all four with docstrings
blanked, as above. The two-lab diff is already done and is quoted here so it does not need retaking.
