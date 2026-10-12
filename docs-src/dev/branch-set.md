# One branch per session

Each working session keeps exactly ONE long-lived branch, declared in `pyproject.toml`, and merges its work into
it (`ONE-BRANCH-PER-SESSION`). Every other branch is merged and then deleted (`MERGE-OR-DELETE`): there is no
third state, and a parked tag or renamed branch is the same debt. Run `python -m lab_commons.dev.branchset` to see
what to merge and what to delete, and `--apply` to delete the merged local ones.

## The declaration

```toml
[tool.lab_commons.branchset]
trunk = 'main'                 # required
sessions = ['integrate/main']  # one per session or lane owner; [] when there are none
```

Read by `lab_commons.dev.branchset.declared_branchset(root)`; a missing or malformed table raises
`BranchSetNotDeclared`. Adding a long-lived branch is a reviewed edit of `sessions`.

## The census and the candidates

Every read is of local refs, so `git fetch --prune` first: the remote is the authority.

| call | answers |
|---|---|
| `census(root, branchset)` | `undeclared_origin` (debt), `local_debt`, `unpushed` (undeclared, holding commits no origin ref has) |
| `merge_candidates(root, branchset)` | every undeclared branch and parked tag, `deletable` when its tip is in the trunk's authority or a session branch; anything else is merged first |
| `python -m lab_commons.dev.branchset [--root R]` | prints the candidates as `delete` / `merge` rows; deletes nothing |
| `python -m lab_commons.dev.branchset --apply` | deletes merged LOCAL branches and tags, re-checking ancestry at the moment of deletion; lists origin's for a human |

- **Merged means merged into the REMOTE authority.** A local `main` that is ahead and unpushed answers "merged"
  about work whose only published copy is the branch you are about to delete.
- The question is whether the CHANGE is there, so the instrument is `git cherry` against the remote, which sees
  through cherry-picks and rebases; the ancestor test does not.
- Deleting a branch on origin is a human's action: the door prints `git push origin --delete <b>`.

## The assertions consumers run

`lab_commons.dev.famtests.branchset`:

- `assert_origin_branches_declared(root=, branchset=)`: red on an undeclared origin branch not contained in HEAD,
  `origin/<trunk>` or a session branch. A merged one is returned and warned as "deletion owed to a human".
- `assert_local_branches_declared(root=, branchset=)`: red on an undeclared local branch origin already holds;
  one holding unpushed work is returned and warned, never red, because it is the only copy.
- `assert_the_planted_branchset_is_policed(tmp_path, trunk=)`: the planted control on a real bare origin.

## The push-time check

A pre-push hook judges every pushed `refs/heads/**` ref (`lab_commons.dev.branchset_push`, reading git's ref lines
from stdin through the family hook runner):

| push | verdict |
|---|---|
| a branch the set names | allowed |
| a branch the set does not name | refused, naming the branch and both remedies |
| a deletion | allowed: deleting a stray branch is the remedy |
| a tag, or a machine ref | allowed |
| a checkout with no declared branch set | refused: a guard that cannot judge must not read as one that acquitted |

There is no bypass flag; the way to push a new long-lived branch is to add it to `sessions`.
