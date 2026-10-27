# Fan-out

Parallel work happens in worktrees, one branch each, each with its own `.venv`. Create the worktree at an
explicit sha under `.claude/worktrees/`, bootstrap its environment, split work by file-disjointness, measure
only what you touched, commit, and push (a subagent hands its SHA back instead). Proving the combination is the
forge's job, not yours.

## Environments: each worktree owns its venv

- Each worktree owns its `.venv`, with an editable install of its own source. Never borrow the primary
  checkout's interpreter for a worktree, and never change the primary's environment from a lane.
- Bootstrap or repair a worktree's environment from the repository root, with any interpreter that has
  `lab-commons[dev]`:

  ```text
  <available python> -m dev_lab.dev.dep --bootstrap <worktree> [--sync] [--extra <name> ...]
  <worktree>/.venv/Scripts/python.exe -m dev_lab.dev.dep --root <worktree> --sync
  ```

  The target is always `<worktree>/.venv`, never an inherited `VIRTUAL_ENV`. Failures exit non-zero.
- A consumer declares its complete selection in `pyproject.toml`; with no `--extra`, sync realises all of it,
  and explicit `--extra` flags narrow it. `--dry-run` checks without mutating.

  ```toml
  [tool.dev_lab.dep]
  extras = ["all", "dev"]
  ```

- A run in worktree A blocks mutation of A's environment only, not bootstrap or sync of B's; CPU contention is
  the box seat's job ([box resources](box-resources.md)).
- A log name is a NAME, not a path: the runner places it under its own dated directory and refuses a separator.

## Setting up a lane

- Branch from the current integration tip, never from `main`.
- **Create the worktree at an explicit commit, inside the repo**:
  `git worktree add --detach .claude/worktrees/<name> <sha>` ([worktrees stay inside](worktrees.md)).
- **Split by file-disjointness.** Shared hotspots (an entry-point module, the central chain, the registries
  every feature touches) go to ONE lane, or are serialised.
- There is no lane ledger: `python -m dev_lab.dev.worktrees` lists the trees, `--prune` reclaims clean,
  landed, unoccupied ones, and `--archive <name>` moves a tree's outputs home before a deliberate removal
  ([worktrees](worktrees.md), [auto mode runs the doors](auto-doors.md)).

## Subagents: give them a sha, not your HEAD

- An agent spawned with automatic worktree isolation gets a tree based on the PRIMARY checkout's HEAD, not on
  your lane, so every commit your lane has not merged is absent from it. It then either reports the premise
  false or, worse, reasons about code nobody runs.
- **Spawn it without automatic isolation and make its first step**
  `git worktree add --detach .claude/worktrees/<name> <sha>`, with the sha, never a branch name.
- Then have it check where it landed before anything else: `git rev-parse HEAD` against the sha, plus a count of
  a symbol the task needs that must be non-zero. A zero count is a STOP.
- A subagent measures what it touched, commits and hands back its SHA; it never pushes (`SUBAGENT-NO-PUSH`).
- Tell it not to kill processes or delete lock files it does not own.

## Measuring under fan-out

- A targeted measure is the tests you wrote or touched, not a subset of the suite. Many lanes measuring at once
  share the box's one CPU seat; a measure waits briefly, attaches to an identical run in flight, or cites a
  cached key, and otherwise refuses naming the holder.
- The process table answers "is it alive", never "where is it": dump the stack of the real worker pid.
- A number you cannot reproduce is an anecdote: count what else is running before quoting a duration.

## Landing

- Each lane: implement, measure, commit on its branch, push (or hand the SHA back), report SHAs, the
  measurement and every file touched.
- Keep the branch current with `forge sync`; open a PR into integration when it should be taken.
- The forge merges a PR whose parts stand PASS ([the integration branch](integration.md)).
- Once merged, delete the worktree, its output directory and the branch, tree clean first
  ([one branch per session](branch-set.md)).
