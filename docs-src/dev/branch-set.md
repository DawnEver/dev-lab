# One branch per session

Rule `ONE-BRANCH-PER-SESSION` (statement in `lab_commons.dev.rules`). Each working session maintains exactly ONE long-lived branch and merges its work into it; every other branch is merged and then deleted, never left behind.

## Why

User directive, 2026-10-04: lab-commons alone carried six merged branches on origin and three local branches with unpushed commits, each in its own worktree. A branch nobody declared is a branch nobody owns, and nothing said which of them still held work.

## The declaration

The branches a repo may carry long-term are DATA, in one place -- `pyproject.toml`:

```toml
[tool.lab_commons.branchset]
trunk = 'main'                 # required; a guessed trunk finds nothing and reads every checkout clean
sessions = ['integrate/main']  # one per declared session or lane owner; [] when there are none
```

Read by `lab_commons.dev.branchset.declared_branchset(root)`; a missing or malformed table raises `BranchSetNotDeclared`.

## The census and the candidates

All reads are local refs, so fetch with `--prune` first: the remote is the authority.

| function | answers |
|---|---|
| `census(root, branchset)` | `undeclared_origin` (debt), `local_debt` (undeclared, nothing origin lacks), `unpushed` (undeclared, holds commits no origin ref has) |
| `merge_candidates(root, branchset)` | every undeclared branch, local and on origin, `deletable` when its tip is an ancestor of the trunk's authority or of a session branch; anything else is merged first |
| `python -m lab_commons.dev.branchset [--root R]` | prints the candidates as `delete` / `merge` rows; deletes nothing |

## The assertions consumers run

`lab_commons.dev.famtests.branchset`:

- `assert_origin_branches_declared(root=, branchset=)` -- red on an undeclared origin branch that is NOT contained in HEAD, `origin/<trunk>` or a session branch. A MERGED one is not a red (ruling 2026-10-04: remote deletion is never automatic, and a red here once made an agent delete on origin so its push could verify); it is RETURNED and warned as "merged, deletion owed to a human" with `git push origin --delete <b>`. The local check treats a merged local branch the same way, pointing at `branchset --apply`. `merged_owed(root=, branchset=)` lists both.
- `assert_local_branches_declared(root=, branchset=)` -- red on an undeclared local branch origin already holds; RETURNS (and warns about) the ones holding unpushed work, which are never a red because they are the only copy.
- `assert_the_planted_branchset_is_policed(tmp_path, trunk=)` -- the planted control on a real bare origin: clean first, then a stray branch on both sides, unpushed work, and the deletable list.

This generalises the per-consumer `ORIGIN_BRANCHES` / `LOCAL_ONLY_BRANCHES` pins of `famtests.visibility`: a consumer declares its sessions in the manifest and delegates here.
