# Alignment

The framework every branch develops against, so that merging N branches conflicts on CODE and never on
bookkeeping. Before you add a shared count, a waiver or a registry row, check it against the stages below: a
number every branch must touch has to stop being a number any branch writes. The integrator's measure of success
is a merge whose conflict set holds no pin, no count and no waiver table.

## The diagnosis

- A single global integer is hostile to parallel branches: two branches each legitimately adding one merge
  cleanly and produce a number wrong by one, with neither at fault.
- Most files in conflict during a large integration are pins, counts, floors and line-anchored waivers; only a
  minority need real judgement. The remedy is structural, not discipline or better merge tooling.

## Stage 1: partition every shared singleton

- **A declaration more than one branch edits is partitioned by OWNER**, and the whole is composed by a function
  that REFUSES a collision.
- The owner axis is whatever the data separates along: a vendor, a physics, a test directory, a module tree.
- Each partition names its owner in a constant; the composer verifies the name against the content and raises on
  a key held twice or outside its owner, at import time, never as a silent last-wins merge.
- A registry conflict then becomes porting rows into partitions rather than reconciling two rewrites of one file.
- A partition does not remove the need to re-measure a total; it removes the need for two branches to write it.

## Stage 2: a count is derived, never written

- **Where a pin is a population size, the constant is the length of the table**; a hand-written integer beside a
  list is two sources for one fact.
- A ratchet compares the measured length against a high-water value, not a per-commit pin, so a branch adding a
  row and a branch removing one do not collide.
- A genuine measurement of the tree (a collection floor, a line count) is computed by the test and compared with
  a floor that is only ever lowered.
- A size-debt table maps a path to a high-water mark and fails only on growth past it.

## Stage 3: no waiver is keyed by a line number

- Every merge moves lines, so a line-keyed waiver reads as stale and fresh at once while the debt is unchanged.
- Key a waiver by file plus test-function name, or by a marker in the source.
- Fix the SCANNER before re-keying: a guard that counts quotes before the match will count prose inside
  docstrings and miss a mark nested in a parametrize entry.

## Stage 4: one decomposition standard

- Two branches can split one module into files of the SAME NAME with DIFFERENT contents. So **a split is declared
  first**: one line in a shared registry naming the file, the seam and the new module names, pushed before the
  work starts.
- Split on the group sharing one subject, one vocabulary or one dependency the rest does not need, never on a
  line count. The new module's docstring names the seam.
- Public names stay public and private stay private. Anything both halves need goes into a third leaf below both.
- **The suppression count is conserved across a split** and stated in the commit.

## Stage 5: the guards only the merged tree can run

These catch defects invisible on any single branch; each is an architecture test with a floor.

- **A compile-stage scan of the whole tree.** Two branches adding the same keyword argument a few lines apart
  produce a duplicate keyword that git calls clean; only compiling catches it, not parsing.
- **A duplicate public-name scan**: no two modules in one package export one name with different signatures.
  Its blind spot: two definitions with identical parameter names.
- **A retired-PATH registry** beside the retired-spelling one, so a branch cut before a deletion cannot bring the
  path back ([retirement](retirement.md)).
- **A dead-row scan on every registry**: a row that outlives its subject is a waiver nothing uses.
- **A duplicate top-level binding scan.** Python keeps the last binding, so the first is dead code. A rebinding
  that READS its own previous value is narrowing a table and is legal; one that does not is the defect.

## Stage 6: the branch protocol

- **Run `forge sync` before declaring a feature done**, so the branch has seen the current integration tree;
  every conflict class above is cheaper the smaller the divergence.
- **When two branches disagree on a constant, measure the merged body**; never choose a side and never add the
  deltas.
- **A capability that lands must not take its refusal test with it.** When a refused option becomes routable,
  re-plant the refusal half keyed off the declaration, not the literal value.
- **A branch prices its own timeouts**: a per-test timeout with no measurement near it cannot be priced by the
  integrator.

## What "aligned" is measured by

- The integration's conflict set contains no pin file, no count and no waiver table.
- No two branches have split the same module.
- The merged tree compiles before it is tested.
- Every constant in the architecture suite is derived from a table in the same file, or is a one-way high-water
  mark.
