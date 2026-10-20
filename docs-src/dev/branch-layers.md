# Branch layers

Three layers, each proving something different: a child branch proves a change in isolation, the integration
branch proves the children together, and `main` is the proven state every box fast-forwards to. Work on your
own `pr/<topic>` branch, take integration into it with `forge sync`, and let the forge move the other two. The
verbs are on [the integration branch](integration.md); the bars are on [the verdict model](verdict-model.md).

## What each layer proves

| layer | proves | moved by |
|---|---|---|
| child (`pr/<topic>`, a session branch, a PR head) | this change, on a tree nobody else writes | its owner's commits and `forge sync` |
| integration (`integrate/main`) | these children together, on one tree | the forge's merges of green PRs |
| trunk (`main`) | the state everyone may branch from and fast-forward to | `integrate promote` only |

- **Branch from integration, never from `main`**, which lags by the integration cycle.
- **Two green branches are not a verdict about their merge.** Collection, imports and parametrize inputs depend
  on the merged tree, so the merged tip gets its own parts. A red that appears only there is the merge's own
  defect.
- **The trunk moves only by fast-forward** to an integration commit whose every required part is a full PASS.
  No merge commit lands on it.

## Is it merged?

- Never write "merged" from memory. `git merge-base --is-ancestor <commit> <target>` is conclusive when true;
  else `git cherry <target> <branch>`, whose `+` lines are what the target lacks. Say which one answered.
- A cherry-pick or rebase changes the sha, so the ancestor test answers no about content that is present;
  `git cherry` sees through it.
- Measure against the remote authority (`origin/<target>`), never a local branch that may be ahead and unpushed.

## When it is merged

- Delete the worktree, its output directory and the branch in the same pass, with the tree clean first
  ([one branch per session](branch-set.md)). A branch parked "for later" is debt, not a backup.

## Where merges actually collide

- Modules rarely collide, because work is split by file-disjointness. Shared counts and pins collide, because
  every branch touches them: the collection floor, per-file ceilings, size-debt tables, heavy-partition
  declarations, line ratchets.
- A conflicting count is arithmetic to redo on the merged tree: measure the merged body, never choose a side
  and never add the two deltas, because their removals overlap. [Alignment](alignment.md) exists to make this
  case empty.
