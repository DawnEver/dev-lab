# Worktrees stay inside

Every checkout of a repository (a linked worktree, a moved one, a clone made for it) lives at
`<toplevel>/.claude/worktrees/<name>` (`WORKTREES-STAY-INSIDE`). Create one with
`git worktree add --detach .claude/worktrees/<name> <sha>` from the repo root. A tree outside its repository is
outside every scan, ignore rule and search the repository runs, and outside where the next agent looks.

## One fact, three mechanisms

The location is spelled once: `lab_commons.dev.worktreeplace.WORKTREES_REL`.

| mechanism | where | what it refuses |
|---|---|---|
| PREVENT | deny row `WORKTREES-STAY-INSIDE` in `lab_commons.dev._deny_rows`, rendered into every repo's `.claude/hooks/deny-rules.json` | `git [-C <dir>] worktree add` / `worktree move` / `git clone` whose target is not `.../.claude/worktrees/<name>`; any `..`; a clone with no explicit target |
| DETECT | `lab_commons.dev.famtests.worktreeplace.assert_every_worktree_stays_inside(root=...)` | any `git worktree list --porcelain` entry (main checkout excepted) not inside `<main>/.claude/worktrees/`; the red names the `git worktree move` that fixes it |
| IGNORE | the family `.gitignore` base's Claude section: `**/.claude/**` with only the shared directories re-included | a worktree showing up as untracked content of its own repository |

- A deny pattern reads text: it cannot tell whether a `.claude` in the target belongs to this repository. The
  detector reads git's own list, so the two halves are not duplicates.

## Adopting it in a repo

1. Upgrade `lab-commons` and re-render `.claude/hooks/deny-rules.json` (`lab_commons.dev.hook_adoption.render`).
2. Add one test:

   ```python
   from pathlib import Path
   from lab_commons.dev.famtests.worktreeplace import assert_every_worktree_stays_inside


   def test_every_worktree_stays_inside() -> None:
       assert_every_worktree_stays_inside(root=Path(__file__).resolve().parents[N])
   ```

3. Re-render `.gitignore` from the family base ([project files](project-files.md)).
4. Move any misplaced tree with the command the red names.
