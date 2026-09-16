# The shared checkout — where a tool's correctness argument stops transferring

- Distilled 2026-09-05 from two 2026-09-04 incidents. This page is MECHANISM: what specifically breaks when several parties write one checkout, and what the writer can do about it.
- The hard constraints it sits under stay in each repo's always-loaded rules — never mutate what another party learns about by accident; a path-scoped commit is a working-tree snapshot.

**The shape both incidents share.** A tool is correct under a premise it never checks: the commit hook assumes it owns the working tree; the verdict's base resolution assumes the default branch is roughly current. Neither premise holds here. **Both tools report SUCCESS either way**, so the failure is silent and gets attributed to "the shared checkout" as a vague force rather than to a named mechanism.

## A commit hook's stash covers the WHOLE TREE, so it reverts other agents' work

- A hook framework that stashes before running prints its own evidence: it stashes unstaged files, runs the hooks — lint, format, message check, checkout guard, and the window is not short — then restores.
- **The stash takes every unstaged change in the tree**, not the paths being committed. If agent B writes a file inside agent A's hook window, A's restore puts the OLDER snapshot back over B's newer content, and B sees a revert with nothing in its own history explaining it. Measured: one agent's work reverted three times, once mid-measurement, costing a full re-run.
- **A path-scoped commit does not help.** It scopes what is COMMITTED; the stash is tree-wide regardless. Same lesson, other direction, learned separately the same day: path scoping does not limit what the HOOKS CHECK either.
- **This is NOT the shared-INDEX hazard** — a broad staging command sweeping another agent's file into your commit, four separate incidents. Both present as "the checkout ate my work"; different mechanism, different remedy, so name which one before reaching for a fix.
- Remedies, in order:
1. **Commit promptly.** Exposure is proportional to how long work sits unstaged, not to its size.
2. **STAGE what you are not ready to commit** — the hook stashes UNSTAGED changes only. This is the cheap protection and it is entirely under the writer's own control.
3. An out-of-repo byte copy during someone else's commit. A git stash is the wrong instrument: the stash ref is repo-wide across every worktree, so it must be a plain file outside the tree.
4. Skipping verification skips the stash and is **forbidden by default**. Used deliberately once, flagged, and re-verified by hand — lint and format over the committed content, and the commit contained zero of the other agent's lines. Sound reasoning, correct outcome, and it stays an exception that is DECLARED and hand-re-verified, never a habit.
- This is not a bug in the hook framework. Its stash is correct for the single-checkout case it was designed for. **When a tool that assumes exclusivity is run concurrently, its correctness argument does not transfer.**

## A new lane's FIRST push is structurally blocked, and the lane is not the cause

- The base resolution walked from the hook-supplied ref, to the branch's upstream, to the default branch. On a never-pushed lane the first is all zeros and the second is unset, so the base was the default branch — which was **763 commits and two days behind the integration branch**. The verdict then re-judged other people's already-green work: 585 paths against 320 for the lane's own 50 commits, 31 minutes, and INCONCLUSIVE over the wall.
- The retry wrapper then retries the push, re-running the whole thing. **Kill it** — three retries buy 90 minutes of reproducing the same INCONCLUSIVE, and retrying a tier that is over its wall is the retry-instead-of-change-approach antipattern.
- Checked rather than assumed, all five of the obvious remedies DO NOT work:
- **A smaller first increment** — any first push has no baseline, so the fallback applies whatever you push. "Push early" is not survivable advice here: the FIRST push has no early.
- **Seeding the remote branch at an older sha** — that push is also a new branch.
- **A base override on the runner** — there was none; the gate tier takes no paths and no base, which is why the fix had to land INSIDE the resolution rather than at the call site.
- **Citing an already-green heavy run** — the runner only WRITES its verdict files; nothing read them back, and the pre-push path ran the gate unconditionally for a non-default branch.
- **Tracking the integration branch so the upstream ref resolves** — with the default push strategy it stays undefined when the remote branch has a different name, and the strategy that would define it is refused here, because on a shared checkout a bare push would then send the lane onto the integration branch.
- **CLOSED 2026-09-04 BY A FOURTH STEP, and this page nearly shipped saying otherwise.** The note it was distilled from ended "the remedy is a HUMAN's", and it was right on the day it was written. It was already stale the next night: the resolution now inserts the INTEGRATION branch before the default branch, each step falling through unless it names a real ANCESTOR of HEAD — which is what keeps a narrower base honest, since a base HEAD does not descend from would let the run SKIP commits rather than decline to re-judge ones the remote already holds.
- Measured 2026-09-06 on a lane 104 ahead and **0 behind** the integration branch: the base resolves to the integration branch, and the increment is **436 paths** rather than the 585 the old fallback produced. The default branch itself had drifted further meanwhile, from 763 commits behind to **770** — the fallback gets worse on its own, which is why the fix had to be a step in the resolution rather than a one-off rebase.
- **The transferable half is the mistake, not the fix.** A finding recorded as "blocked, a human must act" is the kind MOST likely to be stale when you reach for it, because it is precisely the kind someone goes and fixes. Re-run the measurement before repeating the conclusion; the check here cost one command.
- Note what was never the problem: the tree. The commits are safe on the local lane and nothing is lost by not pushing.

## What else is shared, and each has bitten

- **Dependencies.** A dep pinned into the shared environment turns every stale borrowing lane into new-deps-against-old-code. Never install into the primary checkout from a lane.
- **Working tree — including your own.** Never edit the primary from a lane, and never edit your own lane while ITS verdict runs: collection imports, so the verdict PROBABLY describes the old tree, and "probably" is not a measurement. Queue the edit.
- **The index.** Staging in the primary hands your staged work to whoever commits next; lanes call the linter directly rather than the staging-time fixer.
- **The stash.** The stash ref is repo-wide, not per-worktree; use a scratch commit, or a detached probe worktree.
- **Per-worktree memory directories** while memory paths are repo-root-relative — resolve the top level before any staging command, as a habit.

## The transferable half

- Before trusting a tool on this checkout, ask what its correctness argument ASSUMES — exclusive ownership of the tree, a ref being current, a lock being uncontended.
- Then ask whether that assumption is OBSERVABLE in the output.
- **If the tool reports the same thing either way, the assumption is load-bearing and unmonitored**, and that is where to put the check.
