# The integrator

The integrator is the session whose branch is the integration branch: it merges child branches into it
and moves the trunk. It runs no tests: it reads `tests/<part>` parts from the forge. Its
loop is `forge integration` (report on every child), `integrate merge <branch>` for what is ready, a plain
`git push origin <integration>`, and `integrate promote <sha>` then `git push origin <trunk>` when an
integration commit is fully green. Everyone else syncs their branch with `forge sync` and opens pull
requests into integration. Who the integrator is, and where it runs, moves; nothing records it.

## The one flow (user ruling 2026-10-19)

Every change is a SHORT-LIVED branch cut from `integrate/main` and returned by a pull request into
`integrate/main` on the gitea forge, the single source of truth. No long-lived feature branch exists.

1. Cut `pr/<topic>` from `origin/integrate/main` (`ephemeral = ['pr/*']` lets it be pushed with no row), push it,
   and open a PR into `integrate/main` (`forge pr create`). Sync with `forge sync`, never rebase.
2. The forge produces its `tests/<part>` parts. Each tick (`forge integration`, and every `forge serve`), a PR
   whose every part stands PASS, whose head merges cleanly into `integrate/main`, and whose merge passes the
   merge audit is MERGED BY THE FORGE: a merge commit carrying `Merged-Branch: <head>` and `Forge-Pull: <N>`
   (`lab_commons.dev.forgemerge`), the `pr/*` head deleted with it. Otherwise its one integration comment says
   what is missing -- on a conflict, "merge `integrate/main` into the branch".
3. `integrate/main` takes nothing else: with `pr_merges_since` declared, a client push adding a commit to it is
   refused at pre-push (`INTEGRATION-TAKES-ONLY-FORGE-MERGES`). There is no break-glass.
4. `main` moves only by `integrate promote <sha>` on a full PASS, as below.

GitHub (`DawnEver/*`) is a read-only public mirror, and cloud sessions reach only it. Their PRs are carried
across by the same tick (`lab_commons.dev.forgemirror`), from the mirror declared once as `mirror`: the head is
pushed to gitea `pr/gh-<N>` (dropping any commit that only registers its own branch in `sessions`), a gitea PR
is opened or updated with the title and body and a link back, the GitHub PR gets one comment linking it, and
once the gitea PR merges or closes the GitHub PR is closed with a pointer. GitHub credentials are read like
the forge's (`git credential fill` for `github.com`) and never printed.

```toml
[tool.lab_commons.branchset]
ephemeral = ['pr/*']

[tool.lab_commons.integrator]
pr_merges_since = "<the integrate/main sha the rule starts after>"
mirror = "https://github.com/DawnEver/<repo>"    # only where a GitHub mirror exists
```

## The PR reviewer is advisory

`PR-REVIEW-IS-ADVISORY` (`lab_commons.dev.forgereview`, user ruling 2026-10-19). Each open, non-draft PR into
`integrate/main` on gitea is reviewed by Claude ONCE per head sha: the prompt is the repo's own rule files
(`AGENTS.md`, `.claude/rules/*.md`, read at `origin/integrate/main`, never the PR's copy) plus the PR's diff, and
the answer is one PR comment of findings as `path:line` and a `tests/review` commit status. **It gates
nothing**: `tests/review` is never a part, so the forge's auto-merge, `integrate promote` and push admission
never wait on it, whatever it says. A second tick on the same head asks nothing and posts nothing; a new head
is reviewed afresh. A diff over the cap is never sent (`tests/review` says so); a failed model call posts
`error` and is not retried on that head.

It runs as a `forge serve` step only on a host whose machine file declares the capability, so only that host
holds the key:

```toml
[capabilities.pr_review]      # the machine file (lab_commons.config) of the ONE reviewing host
```

The key is ONE dedicated Anthropic API key used for nothing else: the `pr-review` TASK key of the one
model-key scheme -- host `api.anthropic.com`, username `api-key-pr-review` in the git credential store, read by
`lab_commons.credentials.api_key`, stored by `python -m ai_lab.auth login anthropic --task pr-review`. Never the
host's default `api-key` and no other AI key is ever read; with it absent the step refuses by that name and
raises an `auth` alarm. Never printed or logged. Per repo, optionally:

```toml
[tool.lab_commons.review]
model = "claude-opus-5-5"                       # the default: the latest Claude
max_diff_bytes = 200000                         # a larger diff is not sent
max_tokens = 8192
rules = ["AGENTS.md", ".claude/rules/*.md"]     # fnmatch over tracked paths; `*` crosses `/`
```

## The branch flow

| branch | who writes it | the one verb that moves it |
|---|---|---|
| trunk (`main`) | the integrator | `integrate promote <sha>`, then a push |
| integration (`integrate/main`) | the integrator | `integrate merge <branch>`, then a push |
| any other declared session branch | its session | that session's commits and merges, then a push |
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

## Session branches: one writer, by git

Every repo declares its session branches in `[tool.lab_commons.branchset] sessions` -- the integration branch
is one of them. One host's one repo may carry SEVERAL sessions at once, each on its own branch in its own
worktree (the main checkout is just one more worktree). So a branch is protected for what it IS, never for
where it is checked out or which box pushes it: both move.

ONE-WRITER-PER-SESSION-BRANCH is git's own two mechanisms, and nothing is built for it (user ruling
2026-10-14: no lease refs -- every push would read and write origin, and every fetch would carry them):

- **Locally**, a branch is checked out in at most one worktree, so two sessions of one host and repo never
  share a branch.
- **Remotely**, a plain push is compare-and-swap: origin refuses a non-fast-forward, so a writer on a stale
  tip loses and must merge first. SESSION-HISTORY-ONLY-GROWS refuses the force that would bypass it.

The rest are refused at pre-push by the base row `session-branch` (`lab_commons.dev.sessionbranch`), from
local reads only -- no network call beyond the push itself -- with no escape hatch:

| rule | refuses |
|---|---|
| PUBLISH-IS-THE-LOCAL-REF | a push to `refs/heads/X` whose local ref, `HEAD` resolved, is not `refs/heads/X`: `HEAD:X` from another branch, `Y:X`, a bare sha, a detached HEAD |
| SESSION-HISTORY-ONLY-GROWS | a push whose old remote tip (as git hands it to the hook) is not an ancestor of the new one: a forced non-fast-forward, and a deletion |
| INTEGRATION-IS-MERGES-ONLY | a new first-parent commit on the integration branch (after `merges_only_since`) that is not a two-parent merge with a `Merged-Branch:` trailer whose merge audit passes |

The CPU/box seat stays a RESOURCE lock; it decides no ownership.

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
  session publishes with `git push origin <branch>`.

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
- A push of a child more than `[tool.lab_commons.integrator] behind_max` commits behind integration is refused
  at pre-push (`behind-push`, naming this command); `forge serve` runs the behind/conflict report every tick and
  raises an `integration` alarm for each child past the bound or conflicting.
- The watched set is the checkout's git config `branch.<child>.labUpstream`, never a committed file.

## Pull requests target integration

`PRS-TARGET-INTEGRATION`: every pull request targets integration; one opened against the trunk is retargeted
with a comment saying why. Each child carries one PR at most.

## The integration tick

```
python -m lab_commons.dev.forge integration
```

- First carries the GitHub mirror's open PRs to the forge (above), then fetches origin and each PR head (`pull/N/head`).
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
- The base only refines the parents: it tells a side's deliberate deletion or edit from a resolution that
  dropped or reverted it. A criss-cross merge (several merge bases -- every downstream integration after
  the first) is audited like any other: per test, bases that agree give it that base, bases that disagree
  give it none, and a test with no base expects a body only where both parents hold the same one.
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

**The observer is `forge serve`, on EVERY host.** No host owns integration. Each serve tick derives this same
queue (`integrator.observe`), and every row that asks the integrator to act -- a lane READY to merge, the
integration tip PROMOTE-able, a lane or tip BLOCKED on a red to route -- is kept as ONE forge issue titled
`integration: <subject>` (`forgeroute.reconcile`, the found-by-title rule failure routing keeps an `area:*`
issue by). N hosts deriving the same row write one issue; only the host that creates or changes it raises the
alarm (the stderr JSONL line, the host card, `[alerts]`), and a row no longer derived closes its issue. The
`starved` alarm is kept the same way, one `starved: <subject>` issue per part.

## Failure modes

| failure | what happens |
|---|---|
| the child moved after its part was posted | the new tip has no part and reads `waiting` until a producer posts one |
| stale refs (no fetch) | every row prints its tip, so the staleness is visible; the module never fetches |
| forge unreachable | the command exits non-zero with the remedy; nothing is merged on a guess |
| two integrators on one repo | the second's push is a non-fast-forward and refused; it merges first |
| a child blocked on `failure` | listed with its tip; it is the owner's to fix, through its `area:*` issue |
