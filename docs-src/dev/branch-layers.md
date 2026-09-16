# Branch layers — the three, and what each one proves

- This page is about BRANCHES; the tiers, walls and verdict model are on [the verdict model](verdict-model.md), and lane mechanics are on [fan-out](fanout.md).
- What must be true BEFORE a merge so this page's work is cheap is on [alignment](alignment.md), which supersedes this page's advice about ratchet pins.
- **A branch layer is defined by what a green verdict on it PROVES**, and the three prove three different things — which is why one cannot substitute for another.
- A lane (`feat/...`, `fix/...`) proves: this change is green IN ISOLATION, on a tree nobody else is writing.
- An integration branch proves: these lanes are green TOGETHER, on one tree, at one moment.
- `main` proves: this is the state every box can fast-forward to, and the state a new lane branches from.
- **No mechanism in the tree knows the integration branch's prefix** — verified 2026-08-26 by grepping the hooks, the gate and the lane scripts for it and finding nothing — so an integration branch is a convention held by the coordinator, not a guard.

## The layers are siblings, not a hierarchy

- Measured 2026-08-26 with merge-base against `main`: four lanes all branched from the same commit one behind `main`, and the integration branch branched from `main` itself. None branched from another.
- So they are SIBLINGS of the integration branch and not children of it — nothing merges "up" a tree, and the coordinator pulls work sideways into its own worktree.
- Divergence is therefore expected and deliberately unbounded: a dev agent works its branch and PUSHES each green commit, which is the readiness signal itself, and the other agents keep working while the coordinator absorbs it.
- The consequence to plan for is that **the coordinator's tree is the only one where the combination has ever existed**, so its verdict is the only evidence about the combination.

## Integrate, then RE-GATE — two green branches are not a verdict about their merge

- A merge that was never gated is an untested tree with two green ancestors.
- Measured 2026-08-26, collected test counts: the lane collected 16726, the integrator collected 16712, and the merged tree collected 16752.
- **No arithmetic on the first two numbers predicts the third** — not the sum, not the max, not either operand — because collection depends on the merged tree's parametrize inputs, so the merged count is a MEASUREMENT and never a derivation.
- The same is true of the verdict: a red that appears only in the merged tree is the merge's own defect, and it is invisible from either side.
- Measured: one branch removed a symbol and updated all 12 callers; another added a test importing it. Green alone, an import error together.

## At high divergence the pre-push gate is effectively whole-tree

- The gate tier is REACH-selected from the push increment, which is cheap when the increment is a few files and is not cheap when it is a few hundred commits.
- Measured 2026-08-26 on an integration branch: 754 paths selected, 16765 tests, 787.86 s of parallel execution.
- So the reach optimisation buys nothing on an integrator's push, and the cost to budget for is the whole lightweight suite — plan the integration pass around one long run, not around many short ones.
- The remedy for the wait is the one the verdict model names: split or parallelise the work, never raise the ceiling.

## `main` and its fast-forward preconditions

- **`main`'s bar is a heavy PASS, and it is the only destination with that bar** (user rulings 2026-08-27 and 2026-09-07): every other branch answers for its own increment, so this hop is where the whole tree must be green.
- That PASS must name THIS tree: a verdict carries its tree and its environment, so a run whose tree moved underneath it — a commit landing mid-run, or a later fix-up — is a verdict about a tree nobody is pushing.
- `main` advances by a fast-forward-only merge from the integration branch, which requires that `main` be an ancestor of it — so the integration branch must have been rebuilt on the current `main` before the merge is attempted.
- **Never write "merged" from memory**: `git merge-base --is-ancestor` is conclusive when true, else `git cherry` — and state which one answered.
- **A cherry-pick changes the sha, so the ancestor test answers NO about content that IS present** — `git cherry`'s minus lines say absorbed, and that is the test to trust after an integration.
- Measure a branch against the REMOTE authority and dispose of it in the SAME pass: nothing outstanding means DELETE. A branch parked pending a look is debt wearing a backup's name.
- After a real merge, delete the worktree, its output directory, and the origin branch, with the tree clean first.

## The shared ratchet pins are where merges actually collide

- Modules rarely collide, because lanes are split by file-disjointness; the pins collide, because every lane touches them by construction.
- The colliding singletons are the collection floor, the per-file ceilings, the oversize debt table, the heavy-partition declaration, and any line ratchet over the always-loaded documents.
- **A single global integer is structurally hostile to parallel lanes**: two lanes each legitimately adding one merge cleanly and produce a number wrong by one with neither side at fault, which is exactly the 16726 / 16712 / 16752 shape above.
- Measured 2026-08-26: one suppression pin moved three times in one session, and none of the three moves was a defect in the lane that moved it.
- Read a pin conflict as **arithmetic to redo on the merged tree** rather than as a disagreement to resolve in favour of one side — measure the merged body, never choose a side and never add the two branches' deltas, because their removals overlap.
- Do not budget for a pin fix-up pass: [alignment](alignment.md) exists to make it EMPTY, and its success criterion is exactly that. Measured over a 2026-09-03 seven-branch integration, the fix-up was most of the pass — of roughly 55 files in conflict across three merges, about a dozen needed real judgement and the rest were pins, counts, floors and line-anchored waivers.
