# The integrator

The integrator is the session that holds the integration branch's LEASE: it merges child branches into the
integration branch and moves the trunk. It runs no tests: it reads `tests/<part>` parts from the forge. Its
loop is `forge integration` (report on every child), `integrate merge <branch>` for what is ready, a plain
`git push origin <integration>`, and `integrate promote <sha>` then `git push origin <trunk>` when an
integration commit is fully green. Everyone else syncs their branch with `forge sync` and opens pull
requests into integration. Who the integrator is, and where it runs, moves; the lease says which.

## The branch flow

| branch | who writes it | the one verb that moves it |
|---|---|---|
| trunk (`main`) | the integration lease holder | `integrate promote <sha>`, then a push |
| integration (`integrate/main`) | the integration lease holder | `integrate merge <branch>`, then a push |
| any other declared session branch | its lease holder | that session's commits and merges, then a push |
| a child (lane, feat branch, PR head) | its owner | the owner's commits, and `forge sync` from integration |

Declared once in the consumer's `pyproject.toml`; every key is optional and an unknown key is refused:

```toml
[tool.lab_commons.integrator]
integration = "integrate/main"      # the branch children merge into
trunk = "main"                      # moved only by `integrate promote`
test_roots = ["tests"]              # what the merge audit reads
merges_only_since = "<sha>"         # INTEGRATION-IS-MERGES-ONLY holds after this commit
```

Which origin branches are CHILDREN is not a list here but the schedule's one rule,
`[tool.lab_commons.schedule] classes_by_ref` ([scheduling](forge.md#scheduling)): a branch the rule classes
is a child, served and queued; one it does not is neither.

## Session branches: one writer, by lease

Every repo declares its session branches in `[tool.lab_commons.branchset] sessions` -- the integration branch
is one of them. One host's one repo may carry SEVERAL sessions at once, each on its own branch in its own
worktree (the main checkout is just one more worktree). So a branch is protected for what it IS, never for
where it is checked out or which box pushes it: both move. Four invariants, all refused at pre-push by the
base row `session-branch` (`lab_commons.dev.sessionbranch`), no escape hatch:

| rule | refuses |
|---|---|
| ONE-WRITER-PER-SESSION-BRANCH | a push to a session branch (or the trunk) by anyone but the live holder of its lease (the trunk's is the integration branch's) |
| PUBLISH-IS-THE-LOCAL-REF | a push to `refs/heads/X` whose local ref, `HEAD` resolved, is not `refs/heads/X`: `HEAD:X` from another branch, `Y:X`, a bare sha, a detached HEAD |
| SESSION-HISTORY-ONLY-GROWS | a non-fast-forward (forced or not) and a deletion of a session branch or the trunk |
| INTEGRATION-IS-MERGES-ONLY | a new first-parent commit on the integration branch (after `merges_only_since`) that is not a two-parent merge with a `Merged-Branch:` trailer whose merge audit passes |

### The lease

- **Identity is the session**: `$LAB_COMMONS_SESSION` (a declared name -- a human, or a long-lived role),
  else `$CLAUDE_CODE_SESSION_ID`. Resolved per invocation; never a host, directory, repo or login. No
  identity, no push to a session branch.
- **It lives on origin**, as `refs/leases/<branch>`: a commit with the empty tree whose message carries
  `Holder:`, `Where:` (the card name of the box it last renewed on -- an observation, not a binding) and
  `Expires:`. Origin is the one store every session on every box already reads and writes, and the same
  remote the guarded branch lives on; no forge API or token is involved.
- **Compare-and-swap is git's fast-forward rule**: each lease commit has the previous one as parent and is
  pushed plainly, so of two sessions writing from the same old lease, origin refuses the second. The lease's
  history only grows and is its own audit trail.
- **Taken, renewed, expired, taken over**: `python -m lab_commons.dev.sessionlease take <branch>` succeeds
  when there is no lease, it has expired, or you hold it; every push by the holder renews it
  (`[tool.lab_commons.branchset] lease_hours`, default 12); `release <branch>` hands it on at once; `show`
  lists every session branch's holder. A lapsed lease means its holder is gone: anyone may take it over.
- The CPU/box seat stays a RESOURCE lock; it decides no ownership.

## Integrating without a working tree

```
python -m lab_commons.dev.integrate merge <branch> [--audit "<KIND> <test> -- <reason>"]...
python -m lab_commons.dev.integrate promote <sha>
```

- `merge` runs `git merge-tree --write-tree` of the local integration branch and `<branch>`, refuses a
  conflict naming the files, passes the message (`Merged-Branch: <branch>` plus the `--audit` lines) through
  the repo's own `commit-msg` hook stage and `mergeaudit.judge` -- the same functions the hooks run -- then
  `commit-tree` and `update-ref` with the old tip as compare-and-swap.
- `promote` fast-forwards the LOCAL trunk ref to `<sha>`, an origin integration commit whose every derived
  part stands PASS at scope full; it refuses naming the missing parts.
- Neither checks out nor pushes; both refuse a target branch that is checked out in some worktree. The
  lease holder publishes with `git push origin <branch>`.

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
  files; its upstream set; the head's `tests/<part>` states and the open `area:*` issues citing it;
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

`TRUNK-MOVES-BY-FAST-FORWARD`: `integrate promote <sha>` moves the trunk to an integration commit when every
required `tests/<part>` part stands PASS at scope `full`. It refuses naming the missing parts, and refuses a
trunk that is not an ancestor of `<sha>` rather than merging. No merge commit ever lands on the trunk; the
push admission row checks the same standing when the holder pushes it.

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

The integrator may poll (fetch, `forge integration`, act, reschedule) or be woken by the observer. A wake
carries no state: it only means "derive again now". Polling is the floor that makes a lost wake harmless.

**The observer is `forge serve`.** On the host where the live integration lease holder last renewed (its
`Where:`, matched against the serving card name or forge login), each serve tick derives this same queue (`integrator.observe`) and raises an `integration` alarm per row that asks
the integrator to act: a lane READY to merge, the integration tip PROMOTE-able, a lane or tip BLOCKED on a red
to route. Each alarm is keyed by `<state> <branch>@<tip12>`, so the alarm de-dup state is the only memory: a
new row or a moved tip is a new key and is delivered at once; an unchanged row repeats once per the receiver's
`[alerts] repeat_hours`. It goes out through every alarm channel -- the stderr JSONL line a consumer routes
(cc-config's notify), the host card, and `[alerts]`. Every other host derives nothing.

## Failure modes

| failure | what happens |
|---|---|
| the child moved after its part was posted | the new tip has no part and reads `waiting` until a producer posts one |
| stale refs (no fetch) | every row prints its tip, so the staleness is visible; the module never fetches |
| forge unreachable | the command exits non-zero with the remedy; nothing is merged on a guess |
| two integrators on one repo | one lease: the other session's push is refused by ONE-WRITER-PER-SESSION-BRANCH |
| the integrator's session ended | its lease lapses after `lease_hours`; the next session takes it over |
| a child blocked on `failure` | listed with its tip; it is the owner's to fix, through its `area:*` issue |
