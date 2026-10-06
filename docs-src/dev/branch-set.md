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

## The push-time interception

Everything above runs AFTER the push, which is too late for the thing the rule is about. Measured 2026-10-05/06: a session pushed seven `work/*` lane branches to origin while the census naming exactly that hazard was green -- because it had not run yet. The rule now has an enforcement point where the decision is still open, as a pre-push hook:

```yaml
      - id: branchset-push
        name: every pushed branch is declared
        entry: lab-with-venv
        args: ['lab_commons.dev.githooks', 'branchset-push']
        stages: [pre-push]
        always_run: true
        pass_filenames: false
```

`lab_commons.dev.branchset_push` reads the refspec from **stdin** (git's own pre-push protocol: `<local ref> <local sha> <remote ref> <remote sha>`) and falls back to `PRE_COMMIT_REMOTE_BRANCH`, which is what pre-commit exports because it consumes that stdin. Measured on a real bare origin: a raw hook is handed every ref on stdin; a pre-commit hook is handed one, in the environment. Every `refs/heads/**` ref is judged; tags and machine refs such as `refs/ci/**` pass.

| push | verdict |
|---|---|
| a branch the declared set names | allowed |
| a branch the set does not name | **refused**, naming the branch and both remedies |
| a deletion (`local sha` all zeros) | allowed -- deleting a stray branch IS the remedy, and a guard may not refuse its own |
| a tag, or a machine ref | allowed |
| a checkout whose manifest declares no branch set | **refused** -- a guard that cannot judge must not read as a guard that acquitted |

There is no bypass: no flag, no environment variable, and no `--force` spelling relaxes it. The one documented way to push a new long-lived branch is to add it to `sessions` in `pyproject.toml` -- a reviewed edit in the repo that argues for the branch, which is the point.

Two limits, stated rather than left to be discovered. Pre-commit runs **no hook at all** for a push that only deletes a branch (measured twice), so a deletion passes there by not being asked; a raw hook IS asked, and recognises a deletion by the all-zero local object name. And pre-commit reports one ref per push, so a multi-ref `git push <branch> <tag>` is judged on its branch.
