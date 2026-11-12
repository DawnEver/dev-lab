---
name: a-throwaway-worktree-is-a-disposable-lease
description: The worktrees door makes a detached comparison tree declared DISPOSABLE (--scratch) and removes it (--discard); reclaim takes it once quiet.
metadata:
  type: project
created: 2026-11-10
---

# A throwaway worktree is a disposable lease

Incident (a consumer, 2026-11-10, three times): an agent made a detached base tree to diff tests against.
RECURSIVE-DELETE refused `git worktree remove`, reclaim kept the tree as `not landed`, and a submodule checkout
made `git worktree remove` fail anyway, so each one needed the user.

- Doors: `python -m dev_lab.dev.worktrees --scratch <name> <sha>` and `--discard <name>`. They are flags of the
  existing `worktrees` door because every adopter already renders its allow row; a new module would have needed
  one more row in every repo.
- The declaration is the file `dev-lab-disposable` (`reclaim.DISPOSABLE`) in the tree's OWN git admin directory,
  holding the sha it was made at. It is created with git's registration and removed by its prune, so there is no
  second registry.
- Disposable means only two things: untracked content is scratch, and the tree waits for no landing.
  `reclaim.discard` still refuses an undeclared tree, a main checkout or repository, a lock, a tracked change, a
  HEAD no ref holds, a removal holder (the asker's own process family included) and run outputs inside the tree.
- No `submodule deinit`. Removal is reclaim's move-aside delete plus `git worktree prune`, not
  `git worktree remove`, and git keeps a linked tree's submodule repositories under its admin directory, which
  the prune deletes. The planted test checks that this directory is gone.
- Tests: `tests/test_dev_scratchtree.py`. Controls were checked by mutation: with the declaration, reachability
  and occupancy checks disabled, the undeclared, edited/committed and held cases each fail.
