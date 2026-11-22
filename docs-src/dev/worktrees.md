# Worktrees stay inside

Every checkout of a repository (a linked worktree, a moved one, a clone made for it) lives at
`<toplevel>/.claude/worktrees/<name>` (`WORKTREES-STAY-INSIDE`). Create one with
`git worktree add --detach .claude/worktrees/<name> <sha>` from the repo root. A tree outside its repository is
outside every scan, ignore rule and search the repository runs, and outside where the next agent looks.

## One fact, three mechanisms

The location is spelled once: `dev_lab.dev.worktreeplace.WORKTREES_REL`.

| mechanism | where | what it refuses |
|---|---|---|
| PREVENT | deny row `WORKTREES-STAY-INSIDE` in `dev_lab.dev._deny_rows`, rendered into every repo's `.claude/hooks/deny-rules.json` | `git [-C <dir>] worktree add` / `worktree move` / `git clone` whose target is not `.../.claude/worktrees/<name>`; any `..`; a clone with no explicit target. Admitted (`admits: family-sibling-clone`, judged on the filesystem by `deny-commands.js`): ONE clone of a family repo into the siblings root |
| DETECT | `dev_lab.dev.famtests.worktreeplace.assert_every_worktree_stays_inside(root=...)` | any `git worktree list --porcelain` entry (main checkout excepted) not inside `<main>/.claude/worktrees/`; the red names the `git worktree move` that fixes it |
| IGNORE | the family `.gitignore` base's Claude section: `**/.claude/**` with only the shared directories re-included | a worktree showing up as untracked content of its own repository |

- The NAME is its own rule, `WORKTREE-NAMES-ITS-TASK` (user ruling 2026-11-22): `<name>` says what the tree does under
  its task, never a hash (`dev_lab.dev.worktreename`). The deny row of that ID refuses `worktree add|move` to a
  hash-like name; `assert_every_worktree_names_its_task(root=...)` detects one made any other way.
- A deny pattern reads text: it cannot tell whether a `.claude` in the target belongs to this repository. The
  detector reads git's own list, so the two halves are not duplicates.

## Adopting it in a repo

1. Upgrade `lab-commons` and re-render `.claude/hooks/deny-rules.json` (`dev_lab.dev.hook_adoption.render`).
2. Add one test:

   ```python
   from pathlib import Path
   from dev_lab.dev.famtests.worktreeplace import assert_every_worktree_stays_inside


   def test_every_worktree_stays_inside() -> None:
       assert_every_worktree_stays_inside(root=Path(__file__).resolve().parents[N])
   ```

3. Re-render `.gitignore` from the family base ([project files](project-files.md)).
4. Move any misplaced tree with the command the red names.

## Reclaiming a finished tree

A worktree is a lease on a branch for one task. It ends when the branch's content is landed (on the trunk or a
declared session) and it holds nothing unlanded: no TRACKED change and no untracked, not-ignored file (D31, user
2026-11-17: a worktree's work is MERGED or the tree CLEANED, never parked aside). What git IGNORES -- `.venv`,
caches, builds -- is regenerable and goes with the tree. A tree holding unlanded work is kept and listed with its
doors: commit it on its branch and land it through a PR, or the user discards it with
`python -m dev_lab.dev.branchset --discard <branch> --approved "<the user words>"`. Run output is moved first (user ruling 2026-11-12:
reclaiming useless trees is a required part of the workflow): a reclaimable tree's `archive-outputs` are moved
into the MAIN checkout's `output/` and verified, and only then does it go; a move that cannot be verified keeps it
and prints why. Each run ends with a summary line counting every kept tree by reason. An orphan directory under the worktree
home is judged the same way. What blocks reclaim: a tracked change (staged or not), an untracked not-ignored file, commits not landed (`git cherry`), a
live process, a `git worktree lock`. `dev_lab.dev.reclaim.reclaimable` is the
one decision; `python -m dev_lab.dev.worktrees --prune` and `python -m dev_lab.dev.branchset --apply` act on it,
and the session debris hook runs the former; a session start, and every merge (`githooks/base.toml`
`post-merge`, `reclaimrun --background`), detach a background run of the latter, so a finished tree no
longer pins its branch forever. `--prune` removes at most `--limit N` trees per run (default
`reclaimrun.BATCH`, `0` for no bound) and ends with a `next` line naming the run that takes the deferred rest:
each removal deletes a tree's `.venv` (~12.8k files, ~12 s measured 2026-11-17), so an unbounded prune over ~90
trees outran an agent's 50-minute shell. The exact
criteria are in [auto mode runs the doors](auto-doors.md).


## A throwaway comparison tree

A tree made only to compare against (a base sha to diff tests on) is never landed, so reclaim would keep it as
`not landed` forever. Declare it disposable when you make it, and remove it yourself when done:

```text
<venv python> -m dev_lab.dev.worktrees --scratch <name> <sha>   # detached at <home>/<name>, declared disposable
<venv python> -m dev_lab.dev.worktrees --discard <name>         # removes it now, submodule checkouts included
```

The declaration is a file in the tree's own git admin directory (`dev_lab.dev.reclaim.DISPOSABLE`, holding the
sha it was made at), so it goes with git's registration. Disposable means its untracked and ignored content is
scratch and it waits for no landing; `--prune` and `branchset --apply` also take it once quiet. `--discard`
still refuses an undeclared tree, a main checkout, a lock, a tracked change, a HEAD no ref holds, a live process
(the asker's own included) and run outputs inside it.

## Removing one named tree

`python -m dev_lab.dev.worktrees --remove <name>` (`dev_lab.dev.worktrees.remove`) is the one door for a named
tree on a branch or detached -- never the raw git removal, which `RECURSIVE-DELETE` refuses. It refuses a tree
holding unlanded work (a tracked change or an untracked, not-ignored file, named with its doors), a detached
commit no ref contains, a holding process, a live session and the main checkout; otherwise it moves the tree's
run outputs home, verified (`dev_lab.dev.worktree_outputs.home_outputs`), then removes it. A branch the tree held
stays for `branchset --apply`. D31 retired the flag that saved a tree's work aside; it is refused by name.

- MOVES (renames) every file under each `archive-outputs` directory to the same relative path in the main
  checkout: identical bytes are skipped, differing bytes land as `<file>.<name>`, a directory holding
  `pyvenv.cfg` never travels; a tree on another volume is refused (a move there is a copy).

```toml
[tool.dev_lab.worktrees]            # the main checkout's pyproject.toml; optional
archive-outputs = ["<dir>"]             # default: worktree_outputs.OUTPUTS
```
