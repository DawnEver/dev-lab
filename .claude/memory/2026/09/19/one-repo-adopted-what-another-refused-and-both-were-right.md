---
name: one-repo-adopted-what-another-refused-and-both-were-right
description: wdg-lab adopted famtests.datedmemory while motronics refused it as a REGRESSION with two measured incidents on record, which reads as a one-source-of-truth violation and is not one. Measured - the kit's walk is scoped by a required no-default not_walked argument, motronics changed the QUESTION to git ls-files while wdg-lab pinned the ANSWER as a named set, and only motronics is structurally exposed to the over-reach because this box's hooks confine every worktree to that one repo. Both adoptions are defensible and the difference is exposure, not disagreement.
metadata:
  type: project
created: 2026-09-19
accessed: 2026-09-19
---

# One repo adopted what another refused, and both were right

## The apparent contradiction

`lab_commons.dev.famtests.datedmemory` walks the filesystem for `.claude/memory` trees.

* **motronics REFUSED it**, and its own `test_memory_files_live_under_a_dated_directory.py` carries
  two MEASURED incidents as the reason: the walk judged another checkout's files, then an installed
  third-party package's `.gitkeep`. Its docstring adds the general claim -- *"each ad-hoc exclusion
  only moves the boundary to the next place nobody looked"* -- and it asks `git ls-files` instead.
* **wdg-lab ADOPTED it.**

Read as a family question that is a one-source-of-truth violation: one repo is carrying a
regression the other declined with evidence. Measured, it is not.

## What the measurement says

    declared: 5    found by walk: 5    named-set arm: PASS
    NOT_WALKED: {'node_modules', '__pycache__', '.venv', '.git', 'target', 'lib'}

Three facts, and together they dissolve it:

1. **wdg-lab does not rely on the exclusion set being complete. It pins the RESULT as a NAMED SET** --
   `assert_trees_are_the_named_set(..., declared=MEMORY_TREES, ...)`, whose own docstring reads *"a
   sixth tree is a fork, and a name missing here is a tree that stopped being read."* An
   over-reaching walk therefore lands as a LOUD fork failure, never as a wrong judgement. That is
   exactly the half motronics' objection is about, and it is closed by a different mechanism.
2. **Its `NOT_WALKED` already excludes `.venv`** -- the installed-package path of motronics' second
   incident -- and `lib`, its untracked fixture tree.
3. **Only motronics is exposed to the first incident at all.** This box's hooks confine every
   `git worktree add` to `motronics-studio/.claude/worktrees/`, so motronics is the one repo whose
   tree can contain another checkout. wdg-lab cannot hit it.

## The kit is not at fault either, and the reason is the doctrine

`memory_trees(root, *, not_walked)` takes `not_walked` as a REQUIRED KEYWORD WITH NO DEFAULT. The
scope of a walk is a repo-shaped fact, so the kit refuses to guess it -- the same no-default rule
`LAB_CZ_BASE_REF` is the worked example of. motronics' criticism is therefore precise rather than
general: it indicts *relying on the exclusion set alone*, which wdg-lab does not do.

## The shape worth keeping

**Two consumers of one kit module reached opposite adoption decisions, and neither is wrong,
because they are not exposed to the same hazard.** A family that reads adoption as a binary --
adopted or owed -- cannot express that, and a census row that records only the side will make one
of these two look like debt forever.

So the useful question is not *"do all four repos adopt module X?"* but *"is each repo's answer
defensible against ITS OWN exposure?"* -- and the second question has a different shape: it needs
the exposure named, not just the decision.

**NOT ACTED ON.** Nothing here is a defect, so nothing was changed in either repo. The risk this
entry exists to stop is the opposite one: a later reader seeing the divergence, calling it drift,
and "fixing" it by making wdg-lab ask `git ls-files` -- which would delete a working named-set
ratchet to satisfy a symmetry nobody measured.
