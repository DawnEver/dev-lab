# Worktrees stay inside

Rule `WORKTREES-STAY-INSIDE` (statement in `lab_commons.dev.rules`). Every checkout of a repository -- a linked worktree, a moved one, a clone made for it -- lives at `<toplevel>/.claude/worktrees/<name>`.

## Why

User ruling, 2026-10-03: eight worktrees had been created as SIBLINGS of their repositories (`PEMC/lab-commons-wt-cf`, `PEMC/lc-placement`, `PEMC/lab-commons-integrator`, `PEMC/ms-placement`, `PEMC/optimi-lab-wt-cf`, `WindingDesign/wdg-lab-wt-pm`, ...). A tree outside its repository is outside every scan, ignore rule and search the repository runs over itself, and outside the place the next agent looks for it.

## One fact, three mechanisms

The location is spelled once: `lab_commons.dev.worktreeplace.WORKTREES_REL`.

| mechanism | where | what it refuses |
|---|---|---|
| PREVENT | deny row `WORKTREES-STAY-INSIDE` in `lab_commons.dev._deny_rows`, rendered into every repo's `.claude/hooks/deny-rules.json` (needs no remedy, so every adopter ships it) | `git [-C <dir>] worktree add` / `worktree move` / `git clone` (and `sh <retry-wrapper> clone`) whose target is not `.../.claude/worktrees/<name>`; any `..` in the target; a clone with no explicit target. Bare, `"double"` and `'single'` quoted, `/` and `\` separators. The opening holds only if EVERY such verb on the line lands inside, because the engine tests an opening against the whole command. |
| DETECT | `lab_commons.dev.famtests.worktreeplace.assert_every_worktree_stays_inside(root=...)` | any entry of `git worktree list --porcelain` (main checkout excepted) not inside `<main>/.claude/worktrees/`. The red names `git -C <main> worktree move <tree> <main>/.claude/worktrees/<leaf>` per tree. |
| IGNORE | `.claude/worktrees/` in the family `.gitignore` base (`_famconfig_rows.GITIGNORE_FAMILY_LINES`) | a worktree showing up as untracked content of its own repository |

## What the text guard cannot see

A deny pattern reads text. It can insist the target ends in `.claude/worktrees/<name>`; it cannot tell whether that `.claude` belongs to the repository in question (`git worktree add /elsewhere/.claude/worktrees/x` passes it). That residue is what the detector exists for -- it reads git's own list, so the two halves are not duplicates.

## Adopting it in a repo

1. Upgrade `lab-commons`, re-render `.claude/hooks/deny-rules.json` (`lab_commons.dev.hook_adoption.render`). The row needs no remedy, so it ships unconditionally.
2. Add one test file:

   ```python
   from pathlib import Path
   from lab_commons.dev.famtests.worktreeplace import assert_every_worktree_stays_inside

   def test_every_worktree_stays_inside() -> None:
       assert_every_worktree_stays_inside(root=Path(__file__).resolve().parents[N])
   ```

3. Re-render `.gitignore` from the family base (see [Project files](./project-files.md)).
4. Move any existing misplaced tree with the command the red names.
