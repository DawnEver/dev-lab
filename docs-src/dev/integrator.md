# The integrator

The integrator is the one session that merges child branches into the integration branch and moves the trunk.
It runs no tests: it reads `tests/<platform>` parts from the forge. Its loop is `forge integration` (merge
what is ready, report on every child), push, and `forge promote` when integration is fully green. Everyone
else syncs their branch with `forge sync` and opens pull requests into integration.

## The branch flow

| branch | who writes it | the one verb that moves it |
|---|---|---|
| trunk (`main`) | nobody by hand | `forge promote`: fast-forward to a fully green integration tip |
| integration (`integrate/main`) | the integrator | merges of child branches, then a push |
| a child (lane, feat branch, PR head) | its owner | the owner's commits, and `forge sync` from integration |

Declared once in the consumer's `pyproject.toml`; every key is optional and an unknown key is refused:

```toml
[tool.lab_commons.integrator]
lane_prefixes = ["feat/", "fix/"]   # which origin branches are children
integration = "integrate/main"      # the branch children merge into
trunk = "main"                      # moved only by `forge promote`
test_roots = ["tests"]              # what the merge audit reads
```

## Integration lives in the main checkout

The integration branch and the trunk have one home: the main checkout, whose single editor is the
integrator. Lanes live in linked worktrees on lane branches. A commit or merge commit on either declared
branch from a linked worktree is refused by the `integration-home` commit-msg hook
(`lab_commons.dev.integrationhome`); commit-msg runs for merge commits, pre-commit does not. At session
start, `python -m lab_commons.dev.integrationhome report` says how far the main checkout's branch is
behind its origin and names `sh scripts/hooks/with-retry.sh pull --ff-only` to fix it.

To adopt it: the row comes from `base.toml`, which every repo's hook table merges over, so the hook
needs no change. A repo also prints the `report` line from its SessionStart hook (or worktree-debris
report). Before the first commit, move any integration worktree
back into the main checkout.

## Child branches sync from integration

`DOWNSTREAM-SYNCS-INTEGRATION`: a child merges only integration. Another child's work reaches it once, through
integration.

```
python -m lab_commons.dev.forge sync                       # merge integration (and watched refs) if clean
python -m lab_commons.dev.forge sync --watch origin/<ref>  # opt in to one more upstream; --unwatch, --list
```

- It trial-merges each upstream with `git merge-tree --write-tree`, reports how far behind and which files
  conflict, and merges (never rebases) only when every merge is clean: integration first, then each watched ref.
- On a conflict it merges nothing and names the files; resolve with a plain `git merge`.
- It never pushes. The owner measures what they touched and pushes.
- The watched set is the checkout's git config `branch.<child>.labUpstream`, never a committed file.

## Pull requests target integration

`PRS-TARGET-INTEGRATION`: every pull request targets integration; one opened against the trunk is retargeted
with a comment saying why. Each child carries one PR at most.

## The integration tick

```
python -m lab_commons.dev.forge integration
```

- Fetches origin and each PR head (`pull/N/head`, including PRs on a GitHub mirror remote).
- Per child, says: merged into integration at `<sha>`, or deferred and why; behind N, clean or the conflicting
  files; its upstream set; the head's `tests/<platform>` states and the open `area:*` issues citing it;
  promoted once the trunk holds the merge.
- **The report is one comment per PR**, found by a hidden marker and edited in place. A child without a PR gets
  an `integration` commit status on its head, posted only when it changed.
- The integrator never writes a child branch.

## The ready predicate

`python -m lab_commons.dev.integrator queue [--json]` derives the merge queue from origin every time; nothing
stores it, so a duplicate or lost wake changes nothing.

- **A child is absorbed** when `git cherry <origin/integration> <tip>` prints no `+` line; absorbed children
  are skipped, including cherry-picked or rebased ones.
- An un-absorbed child is `merge` when its tip's parts stand PASS (any scope), `blocked` on a FAIL part,
  `waiting` otherwise. `lane_ready(statuses, head=)` is the one spelling of that rule.
- Integration is `promote` when its parts stand PASS at scope `full`, `blocked` on a FAIL, `parts-needed`
  otherwise.
- Order: oldest tip commit first, ties by branch name.
- The predicate, the order and the queue are the family's and are not configurable.

## Promoting the trunk

```
python -m lab_commons.dev.forge promote
```

`TRUNK-MOVES-BY-FAST-FORWARD`: a fast-forward push of the trunk to the integration tip when every required
`tests/<platform>` part stands PASS at scope `full`. It refuses naming the missing parts, and refuses a trunk
that is not an ancestor of integration rather than merging. No merge commit ever lands on the trunk.

## The merge audit

`MERGE-DEVIATIONS-NAMED`: a merge may not lose or rewrite a test in silence.

- `lab_commons.dev.mergeaudit` computes, per test, what a clean three-way merge would hold. A deviation is
  `LOST`, `ALTERED` or `CONFLICTED`, and each is named in the merge commit message:
  `Merge-Audit: <KIND> <test> -- <reason>`. A clean merge needs no line; a line naming no real deviation is
  refused.
- It runs as the family base's `merge-audit` commit-msg hook, on both `git merge` and the commit that
  concludes a conflicted one, and refuses with the unnamed list and the remedy.
- Integrate by merge only: a rebase leaves no merge commit to audit.
- Not seen: a fixture or helper changed under an unchanged test body.

## Resolving a conflict

- Take the newer STRUCTURE, then re-express your own content inside it. When upstream extracted or split a
  file, your edits go to the new home.
- A shared count or pin that conflicts is arithmetic to redo on the merged tree, never a side to pick
  ([alignment](alignment.md)).
- Price a batch before touching a tree: `git merge-tree --write-tree --name-only <integration> origin/<branch>`
  lists a merge's conflicts without a checkout.

## Waking the integrator

The integrator may poll (fetch, `forge integration`, act, reschedule) or be woken by an observer when a child's
parts turn green. A wake carries no state: it only means "derive again now". Polling is the floor that makes a
lost wake harmless.

## Failure modes

| failure | what happens |
|---|---|
| the child moved after its part was posted | the new tip has no part and reads `waiting` until a producer posts one |
| stale refs (no fetch) | every row prints its tip, so the staleness is visible; the module never fetches |
| forge unreachable | the command exits non-zero with the remedy; nothing is merged on a guess |
| two integrators on one repo | the push whitelist and fast-forward-only promote make the loser's push fail |
| a child blocked on `failure` | listed with its tip; it is the owner's to fix, through its `area:*` issue |
