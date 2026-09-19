---
name: the-leaf-ships-its-consumers-data-and-60-of-78-mechanisms-are-one-repos-paths
description: lab-commons is the family's leaf and its dev layer had absorbed per-consumer data and per-consumer tree paths as shipped source, against its own README tier-1 rule and its own statement-and-mechanism page. Measured by ast over src/lab_commons - 38 executable data values naming a sibling, 153 path constants this checkout cannot resolve (60 of them in the rules registry, 58 resolving only in motronics-studio), and 181 prose mentions across 119 modules. motronics-studio does not import lab_commons.dev at all, so the largest block is data about a repo that never reads it. Designs the parametrized seam, names per module what stays and what moves, and records the eviction order.
metadata:
  type: project
created: 2026-09-19
accessed: 2026-09-19
---

# The leaf ships its consumers' data, and 60 of 78 mechanisms are one repo's paths

## What was asked, and what is measured rather than argued

lab-commons is the family's LEAF. Its own README says tier 1 "contains no concept from any single
project's domain", and `.claude/rules/statement-and-mechanism.md` says a row "never grades another
repo: an adopter supplies its own mechanisms through `Adoption`". This entry measures how far the
`lab_commons.dev` layer has drifted from both, designs the seam that closes it, and records what
was implemented now versus what a consumer must do first.

Every number below was produced by executing a scan over `src/lab_commons/**/*.py` at
`origin/main` (168 commits past v0.2.1), classified with `ast` so a docstring is told apart from an
executable constant. INFERRED claims are marked.

## The census, by KIND

Three kinds, because they are not equally wrong.

**(a) Executable DATA about a consumer** -- a live string value keyed by, or naming, a sibling
repo. 36 occurrences over 4 files:

| file | count | shape |
|---|---|---|
| `dev/_doorcensus_rows.py` | 18 | `DoorRow(repo='wdg-lab', ...)`, one per repo per door |
| `dev/famtests/_placement_readings.py` | 12 | `ROSTERS`/`CEILINGS`/`MINIMUMS` keyed by repo name |
| `dev/_famconfig_ruff_rows.py` | 3 | repo names in a row |
| `dev/_synccensus_rows.py` | 3 | `ScopeRow(repo='motronics-studio', ...)` |

Plus two executable DOMAIN nouns that are not repo names and are the sharper miss:
`_synccensus_rows.py:94-95` carries `selected=('pareto', 'dev')` -- `pareto` is a motronics extra,
a domain noun in live data, not in prose.

**(b) A consumer TREE PATH used as a mechanism** -- a path literal that resolves in a sibling
checkout and not here. 41 path literals by shape; the decisive reading is resolving each registry
mechanism against the four checkouts on this box:

```
78  mechanism path literals in _rule_rows.py
18  resolve in lab-commons
58  resolve ONLY in motronics-studio
 2  resolve in all three consumers but NOT here (.claude/hooks/deny-commands.js, deny-rules.json)
```

**60 of 78 (77%) of the shipped registry's existence proofs are a tree this repo does not have.**
Two of them name a motronics-only layer outright:
`tests/unit/hamilton/registry/test_solver_capabilities.py` (IMPLEMENT-EVERYTHING,
UNSUPPORTED-RAISES). Two more are motronics `scripts/` paths
(`scripts/gate/prepush_gate.py`, `scripts/hooks/with-retry.sh`).

Outside the registry, 39 further consumer-tree path literals: `_provenance_rows.py` 27,
`_doorcensus_rows.py` 7, `famtests/rostercensus.py` 3 (`scripts/repo/worktree_debris.py`),
`_synccensus_rows.py` 2. One hardcodes a repo name INTO the path:
`scripts/wdg-lab-update.sh` (`_doorcensus_rows.py:137`, `_provenance_rows.py:116`).

**(c) Prose / provenance naming a sibling** -- docstrings, comments, and `why=` justification
text. 183 occurrences over 80 files (134 docstring, 49 comment), plus 45 vendor/domain nouns in
docstrings and 28 inside `why=` strings in `_unit_tokens.py` (FEMM, JMAG, Simulink, NGSPICE, SDM,
stator, motor).

Raw totals for the repo-name scan alone: **399 hits on 341 lines in 85 of 117 modules.**

## The two instruments disagree by a little, and BOTH numbers stay on record

The counts above were taken by a line-based grep with an `ast` context pass. The shipped scan
(`lab_commons.dev.foreign`) re-took them and reads **38 data / 153 path / 181 prose** against the
grep's **36 / 41-by-shape / 183**. The scan is the instrument that can REFUSE, so its numbers are
what `_foreign_rows.py` pins; the grep's stay here because a reader who finds them elsewhere
deserves to know which instrument took which.

Three deliberate differences, each a decision rather than a discrepancy:

* the scan calls a string over 120 characters PROSE wherever it sits, because a row's `why=` is a
  paragraph explaining a decision. That moves 21 `_unit_tokens` / `_famconfig_pyproject_rows` /
  `_deny_rows` justification sentences out of DATA, which is where the grep had them;
* the scan defines a PATH as "path-shaped, has a source-or-config extension, and does NOT resolve
  against this checkout" -- which is portable (no sibling checkout needed) and which is why its
  path count is 153 rather than the grep's 41: the grep only counted paths that also named a
  sibling, and most foreign paths do not;
* the scan reads 119 modules against the grep's 117, because it does not require git-tracking.

## The fact that reframes all of it

**motronics-studio does not import `lab_commons.dev` at all.** Measured: its 106 `lab_commons`
references are `em`, `paths`, `file_io`, `log`, `exceptions`, `units` -- tier 1 only. The only
`.dev` consumers are wdg-lab and optimi-lab.

So the 58 motronics mechanism paths and the motronics door/sync/provenance rows are data ABOUT a
repo that never reads it, shipped in the wheel that wdg-lab and optimi-lab install. That is not a
convenience anybody depends on; it is inventory.

## What the seam must be, from first principles

The leaf publishes a STATEMENT and a BODY that takes its data as an argument. The consumer supplies
rows/paths/readings **explicitly, with NO DEFAULT**, so a missing row is a refusal and never a
silent fall-back to a sibling's numbers.

One module here already has the right shape and is the pattern for the rest:
`famtests/placement.py`. Its bars are not constants -- `assert_ceiling_is_bounded(value, *, admits,
refuses, what)` makes the two measured readings the ARGUMENT, and the docstring records why a
shared `OWN_MECHANISM_CEILING` may not exist (two of the four intervals are disjoint). Nothing
there can fall back to another repo's number because there is no number to fall back to.

Per module, what moves out and what stays:

| module | stays (statement / body) | moves out (to the repo that owns it) |
|---|---|---|
| `_rule_rows.py` | ID + statement, the noun test, the "row with no mechanism" refusal | the 60 foreign mechanism paths: an existence proof must name the repo that proves it |
| `rules.py` | `Rule`, `Adoption`, `assert_adopted`, `assert_enforceable`, `tracked_files` | nothing -- this half is already right |
| `_doorcensus_rows.py` | `DoorRow`/`Declined`/`SharedDoor` types, `assert_census` | all 18 consumer rows + 7 consumer paths, to each repo's own arch suite |
| `_synccensus_rows.py` | `ScopeRow`, the scorer | 3 consumer rows, 2 paths, and `('pareto', 'dev')` |
| `_provenance_rows.py` | the provenance kinds and the reader | 27 motronics `scripts/` paths and 23 commentary lines |
| `famtests/_placement_readings.py` | the finding's shape | the per-repo readings, which are EVIDENCE for a published finding, not a bar -- lowest priority, nothing can fall back to them |
| `famtests/_datedmemory_readings.py`, `_storedreadings_readings.py` | reading/verdict seam | per-repo readings, same treatment as placement |
| `_famconfig_*_rows.py` | the base/delta renderer | the 3 repo-keyed ruff rows |
| `_unit_tokens.py` | `UNIT_TOKENS` (generic) | `EXCLUDED_TOKENS`' justification: the tokens are generic, the CALIBRATION is four motor trees. The set is a family-of-EM-labs fact, so it is tier-2 (`lab_commons.em`) rather than tier 1 |
| `famtests/rostercensus.py` | the census body | 3 hardcoded `scripts/repo/worktree_debris.py` literals |

## The mechanism, because a rule with no mechanism may not exist

Prose cannot hold this: the drift happened while both rules pages were being read on every turn.
So the finding ships as `lab_commons.dev.foreign` -- a scan that classifies every string constant
under `src/lab_commons/` into the three kinds above, and an arm
`assert_no_foreign_data(findings, *, evicted, synthetic, read, floor)` -- no argument has a
default, because a missing row must be a refusal and never a silent fall-back, which is the failure
this module is about, one layer in.

The waiver is TWO named sets, not one. `EVICTED` is the eviction ORDER: rows that must go, each
with the reason the deletion is not in this pass. `SYNTHETIC` is the path-shaped strings that name
no tree at all -- `tests/a/test_fast.py` in a refusal message, `planted/recipe.py` in a worked
example. Merging them would put rows in the eviction list that are never going anywhere, and a
waiver list nobody believes is a waiver list nobody reads.

Two-sided, as a ratchet must be:

* an UNWAIVED foreign datum reds -- nothing new arrives;
* a WAIVED name that the scan no longer finds ALSO reds -- the waiver may not outlive its row, so
  each eviction is mechanical: delete the row, delete its waiver name, the suite agrees.

The waiver is a NAMED SET of `module::kind` handles, never an integer, for the reason
`statement-and-mechanism.md` already gives about count pins. The scan carries a floor, so reading
nothing is inconclusive rather than green.

## What is implemented now, and what is deferred and why

IMPLEMENTED (non-breaking; no consumer reds):

* `dev/foreign.py` -- the scan, the three kinds, the two-sided arm, the named waiver set at today's
  measurement. Every module above is named in it, so the eviction order is data.

DEFERRED, in this order, each blocked on a consumer edit this pass may not make:

1. **`_rule_rows.py` mechanisms.** The 60 foreign paths cannot simply be deleted: `Rule` refuses a
   row with no mechanism, so deleting them deletes the rows. The correct next step is to give a
   mechanism its PROVING REPO (`('motronics-studio', 'tests/...')`), which changes the row shape
   that `RULES` exposes -- and wdg-lab/optimi-lab both build `Adoption` against it. So: land the
   pair-shaped mechanism here, then both consumers' `test_*_adopts_the_shared_registry.py` move
   WITH it in the same push train. No `_compat` alias; the break is deliberate and chosen.
2. **`_doorcensus_rows` / `_synccensus_rows` / `_provenance_rows` consumer rows.** Read only by
   lab-commons' own tests (wdg-lab's single mention of `_doorcensus_rows.DOORS` is in a COMMENT,
   measured). Deleting the consumer rows here therefore reds only this repo's floors, which must be
   RE-MEASURED by executing the scan -- not lowered -- once each consumer holds its own census.
3. **`_unit_tokens.EXCLUDED_TOKENS` to tier 2.** It is re-exported from `lab_commons.dev.__init__`,
   so the move is a public-surface break for `dev.units` consumers.
4. **The prose.** 183 sibling mentions in docstrings are the LEAST wrong kind and the most work;
   they are evidence of where a finding came from. Rewrite to name the SHAPE, not the repo, as
   `rem/integration.md` already requires ("an example is a spelling waiting to be retired").

## The frozen installs, and the smallest correct fix

MEASURED: trunk is 168 commits past v0.2.1 (2026-09-13); all three consumers pin `lab-commons` by
BARE BRANCH with no `rev`; the three venvs hold 0.1.1, 0.1.1 and 0.1.0.

INFERRED, and the inference is strong: those two facts are not what froze the installs, and fixing
the tag would not thaw them. A bare-branch `git+` requirement re-resolves to the branch TIP on
every install -- 0.2.1+dev, not 0.1.1 -- so a venv sitting three minor versions back has not been
re-installed, not been mis-resolved. `_doorcensus_rows.py` already measures the doors that decide
this per repo and records `RESOLVES`/`INERT` per command; the frozen versions are the door not
being WALKED.

Smallest correct fix, in order: (1) tag trunk, so a version is a name and not a moving target --
the `dev` layer being entirely untagged means no consumer can say what it has; (2) pin each
consumer to that tag with an explicit `rev`, which turns a silent tip-follow into a declared
upgrade; (3) keep `_doorcensus_rows` measuring the doors, since the pin only helps if the door runs.

Not acted on in this pass: tagging and publishing belong to the parent session.
