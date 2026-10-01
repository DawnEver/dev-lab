# Alignment — the one framework every branch develops against

- This page is the INTEGRATOR's standing plan: what every branch must do the same way so that N branches merge into one tree without a fix-up pass.
- It is downstream of [branch layers](branch-layers.md), which describes what a merge PROVES; this page describes what has to be true BEFORE the merge so the proof is cheap.
- **Every rule below is derived from a MEASURED failure** in a multi-branch integration, not from a preference. The dated measurements live in each consumer's own local alignment ledger, never here — a count in this page would be the drift it argues against. The rules are about merges, not about any one repo's subject.
- **The test of this page is arithmetic**: an integration that follows it conflicts on CODE and never on BOOKKEEPING.

## The one diagnosis everything else follows from

- A single global integer is structurally hostile to parallel lanes: two lanes each legitimately adding one merge cleanly and produce a number that is wrong by one with neither side at fault.
- Budgeting for a fix-up commit on the pins accepts that cost rather than removing it.
- Measured, that cost is most of an integration: of the files in conflict, the ones needing real judgement are a small minority; the rest are pins, counts, floors and line-anchored waivers.
- The remedy is not discipline and not better merge tooling. **A number that every branch must touch has to stop being a number that any branch writes.**

## Stage 1 — partition every shared singleton (the largest single win)

- The rule: **a declaration that more than one branch edits is partitioned by OWNER, and the composed whole is derived by a function that REFUSES a collision.**
- The owner axis is whatever the data actually separates along — a vendor, a physics, a test directory, a module tree.
- Each partition module NAMES its owner in a constant, and the composer verifies the name against the content, so a partition that drifts from its name fails at IMPORT rather than at review.
- The composer RAISES on a key held by two partitions and on a key outside its partition's declared owner — both import-time failures rather than a silent last-wins dictionary merge.
- The payoff: two branches editing two different owners' rows merge with zero conflict, and a monolithic table becomes a short composer over its partitions.
- **A partition does NOT remove the need to re-measure a total; it removes the need for two branches to write the same total.**
- **What Stage 1 does NOT do**: bookkeeping conflicts do not vanish. Registries may still have to be resolved by hand — but the work becomes PORTING ROWS INTO PARTITIONS rather than reconciling two rewrites of one file, which is the cost the stage actually claims to move.

## Stage 2 — a count is DERIVED, never written

- The rule: **where a pin is a population size, the constant is the length of the table and the table is the thing under review.** A hand-written integer beside a list is two sources for one fact.
- Where the count exists to RATCHET, the ratchet compares the measured length against a HIGH-WATER value recorded once per release, not against a per-commit pin — so a lane that adds a row and a lane that removes one do not collide at all.
- Where the number is a genuine MEASUREMENT of the tree rather than of a table — a collection floor, a line count — it is computed by the test and compared against a floor that is only ever LOWERED, so two branches measuring different trees can never disagree.
- **Line counts are the clearest case**: an oversize-debt table should map a path to a high water mark, and the test re-measures and FAILS only on growth past it, so a merge that legitimately shrinks a file needs no edit and a merge that grows one names the growth.

## Stage 3 — line-anchored waivers must stop being line-anchored

- The rule: **no waiver is keyed by a line number.** Every merge moves lines, so a line-keyed waiver set reads simultaneously as stale (waivers with no user) and fresh (violations with no waiver) while the debt itself is unchanged.
- Key a waiver by file plus test-function name, or by a marker in the source, both of which survive a merge that moves the block.
- The same applies to any scan that reports a path and a line: report it, but do not PIN it.
- **A key scheme is only as good as the parse under it.** Fix the SCANNER before re-keying: a guard that counts quotes before the match will count prose mentions inside docstrings as real and miss a real mark nested inside a parametrize entry.

## Stage 4 — one decomposition standard, so two branches split a file the same way

- Two lanes can independently split the same module into a file of the SAME NAME with DIFFERENT contents and different public/private spellings, which is a conflict that no amount of file-disjointness prevents.
- The rule: **before splitting a file over the size band, the split is DECLARED first** — one line in a shared registry naming the file, the seam, and the new module names, pushed before the work starts.
- The registry is the cheapest possible artifact and its only job is to make a duplicate effort visible on the day it starts rather than at the merge.
- The seam standard, so two people who both read it land in the same place:
- Split on the group that shares one SUBJECT, one vocabulary, or one dependency the rest of the file does not need — **never on a line count**.
- The new module's docstring names the seam and why it IS a seam; "split for the ratchet" is not a seam.
- Public names stay public and private stay private; a split does not change a name's visibility, because that is what forces every caller to be touched twice.
- Anything both halves need goes in a THIRD leaf BELOW both, never re-imported sideways.
- **The suppression count is CONSERVED across a split and stated in the commit** — the per-file totals recorded against the one row that stood before, which is the check worth having, because a split is the easiest way to launder a suppression into a file nobody has a number for.

## Stage 5 — the guards that partitioning cannot provide

- These catch defects that are INVISIBLE on any single branch and therefore cannot be a lane's responsibility; each is an architecture test the integrator owns.
- **A compile-stage scan of the whole tree.** Two branches adding the same keyword argument a few lines apart produce a call with a duplicate keyword, and git reports clean. An AST parse does NOT catch this — duplicate keywords are a compile-stage check — so the scan must actually compile; a parse-only scan can report zero bad files while the test runner cannot import the package.
- **A duplicate public-name scan.** Each branch can add its own function under one name with a different signature, leaving live callers on both, because neither could see the other. The scan asserts that no two modules in one package export the same name with different signatures. **Note its blind spot**: it deliberately does NOT report two definitions whose parameter names are IDENTICAL, which is why a half-finished module split can hide from it.
- **A retired-PATH registry beside the retired-spelling one.** A directory emptied under a standing directive can be brought back by a branch cut before the deletion, and carried for as long as **a guard only ratchets where it RUNS** — if the lane's own verdict never reaches green, only the merge applies the rule. A deletion that is a POLICY needs a registry row, exactly as a renamed symbol does, so a branch that re-adds the path reds instead of merging.
- **A dead-row scan on every registry.** A table whose rows outlive their subjects is the "waiver nothing uses" half of a ratchet.
- **A duplicate top-level BINDING scan.** Git, the linter and the compiler all accept a module that binds one module-level name twice; Python keeps the LAST, so the first becomes dead code whose prose still argues for it. The discriminator that makes the rule usable: **a rebinding that READS its own previous value is narrowing a table and is legal; one that does not mention the name is discarding it and is the defect.**
- What such a scan finds is in force wrong, not untidy: a constant compiled to two different values far apart so the reader at the top silently runs the bottom one, a logger bound twice so warnings go to a logger the line above did not name, a pin bound twice where the tree is green only by luck.
- **A silent last-wins can settle a domain question**: two branches' declarations of the same data set in one module, decided by line order, is a real disagreement resolved by whichever was later. That is why this belongs beside the compile scan rather than under tidiness.
- **Each of these guards binds a FLOOR** well under a growing population, and carries its dated measurement in its own file rather than in this page — a count in prose is the drift this page is against.

## Stage 6 — the branch protocol

- **Rebase on the integration branch before declaring a feature done.** A branch that has never seen the current integration tree cannot have tested its own merge, and every conflict class above is cheaper the smaller the divergence.
- **Land in LARGE passes with one fix-up pass**, and the fix-up should be about CODE after stages 1 to 3; if it is about bookkeeping, the framework has regressed.
- **When two branches disagree on a constant, MEASURE the merged body — never choose a side and never add the deltas.** The removals overlap, so the arithmetic is wrong even when both inputs are right: the merged figure is typically neither branch's value and not their difference.
- **A capability that lands must not take its refusal test with it.** When a previously-refused option becomes routable, the test asserting it RAISED is correctly inverted — and the refusal half of the gate disappears with it unless re-planted. When a guard has two sides, inverting one requires re-planting the other, keyed off the DECLARATION rather than off the literal value, so the next capability needs no edit.
- **A branch owns its own pricing.** A per-test timeout with no measurement written near it cannot be priced by the integrator, who has neither the seat nor the context; it can only be recorded as debt.

## What "aligned" is measured by

- The integration's conflict set contains no pin file, no count, and no waiver table. A debt table that conflicts merge after merge, and that on re-measurement holds rows for split files, duplicate keys, values describing no file, or a pin left ABOVE a shrunk file — banked slack wearing a ratchet's name — is the signal this has not landed.
- No two branches have split the same module.
- The merged tree compiles before it is tested — the compile scan is green without an edit.
- Every constant in the architecture suite is either derived from a table in the same file, or a high-water mark that only moves in one direction.
- The fix-up pass after a merge is empty, and the integrator's remaining work is reading code.
