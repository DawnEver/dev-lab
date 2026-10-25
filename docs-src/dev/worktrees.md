# Worktrees stay inside

Every checkout of a repository (a linked worktree, a moved one, a clone made for it) lives at
`<toplevel>/.claude/worktrees/<name>` (`WORKTREES-STAY-INSIDE`). Create one with
`git worktree add --detach .claude/worktrees/<name> <sha>` from the repo root. A tree outside its repository is
outside every scan, ignore rule and search the repository runs, and outside where the next agent looks.

## One fact, three mechanisms

The location is spelled once: `dev_lab.dev.worktreeplace.WORKTREES_REL`.

| mechanism | where | what it refuses |
|---|---|---|
| PREVENT | deny row `WORKTREES-STAY-INSIDE` in `dev_lab.dev._deny_rows`, rendered into every repo's `.claude/hooks/deny-rules.json` | `git [-C <dir>] worktree add` / `worktree move` / `git clone` whose target is not `.../.claude/worktrees/<name>`; any `..`; a clone with no explicit target |
| DETECT | `dev_lab.dev.famtests.worktreeplace.assert_every_worktree_stays_inside(root=...)` | any `git worktree list --porcelain` entry (main checkout excepted) not inside `<main>/.claude/worktrees/`; the red names the `git worktree move` that fixes it |
| IGNORE | the family `.gitignore` base's Claude section: `**/.claude/**` with only the shared directories re-included | a worktree showing up as untracked content of its own repository |

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
declared session) and no TRACKED file is changed. What git does not track -- scratch one-offs, untracked files,
ignored `.venv`, caches, builds -- is not the work (the work is committed; a finding belongs in memory) and goes
with the tree (user ruling 2026-10-25). The one exception is run output: every `archive-outputs` directory is
moved home and the copy verified first, and only on a verified archive does `git worktree remove --force` run;
an archive that cannot be verified keeps the tree and prints why. An orphan directory under the worktree home
goes the same way. What blocks reclaim: a tracked change (staged or not), commits not landed (`git cherry`), a
live process, a `git worktree lock`. `dev_lab.dev.reclaim.reclaimable` is the
one decision; `python -m dev_lab.dev.worktrees --prune` and `python -m dev_lab.dev.branchset --apply` act on it,
and the session debris hook runs the former, so a finished tree no longer pins its branch forever. The exact
criteria are in [auto mode runs the doors](auto-doors.md).

## Archiving a tree before removing it

`python -m dev_lab.dev.worktrees --archive <name>` (`dev_lab.dev.worktree_archive`) is the step before
a deliberate removal. It removes nothing; it reports `safe to remove` or why not.

- Saves no ignored file outside the outputs: what git does not track is not the work.
- Refuses a tree with an occupant (`dev_lab.dev.liverun.occupants`: a process working in it, executing from
  it, or reading it -- another session's tree is live) and a tree on another volume (a move there is a copy).
- Saves `HEAD.txt`, `dirty.patch` (`git diff HEAD --binary`) and the untracked non-ignored files under
  `<archive-to>/<yyyymmdd>/<name>/`.
- MOVES (renames) every file under each `archive-outputs` directory to the same relative path in the main
  checkout: identical bytes are skipped, differing bytes land as `<file>.<name>`, a directory holding
  `pyvenv.cfg` never travels.

```toml
[tool.lab_commons.worktrees]            # the main checkout's pyproject.toml; both keys optional
archive-outputs = ["<dir>"]             # default: worktree_archive.OUTPUTS
archive-to = "<dir>"                    # default: worktree_archive.ARCHIVE_TO
```

It is a flag of the `worktrees` door, whose allow row every adopting repo already renders, so a consumer gets it
by upgrading lab-commons alone.
