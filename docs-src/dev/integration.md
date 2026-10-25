# The integration branch

Every change is a SHORT-LIVED branch cut from `integrate/main` and returned by a pull request into
`integrate/main` on the gitea forge, the single source of truth. The FORGE is the only merger of
`integrate/main`; `main` moves only by `integrate promote`. No long-lived feature branch exists
(user ruling 2026-10-19).

## The path of one change

1. Cut `pr/<topic>` from `origin/integrate/main` (`ephemeral = ['pr/*']` lets it be pushed with no row), push it,
   and open a PR into `integrate/main` (`forge pr create`). Sync with `forge sync`, never rebase.
2. The forge produces its `tests/<part>` parts. Each tick (`forge integration`, and every `forge serve`), a PR
   whose every part stands PASS, whose head merges cleanly into `integrate/main`, and whose merge passes the
   merge audit is MERGED BY THE FORGE: a merge commit carrying `Merged-Branch: <head>` and `Forge-Pull: <N>`
   (`dev_lab.dev.forgemerge`), the `pr/*` head deleted with it. Otherwise its one integration comment says
   what is missing -- on a conflict, "merge `integrate/main` into the branch".

   SCARCE PARTS BY REACH (user ruling 2026-10-22, `dev_lab.dev.forgescarce`). A part whose need-set holds a
   resource the repo declares scarce -- ONE table, `[tool.lab_commons.tests] scarce = ["femm", "jmag", ...]`, a
   subset of `resources` -- is required of a PR only when a path of `merge-base..head` reaches one of its test
   files (the carry's footprint rule; the files are read off the `handed` map of the record the head's
   `tests/base` links). An unreached scarce part is WAIVED: never produced for the PR, never read for its
   merge, and named in its integration comment. A reached one is required and is produced for the PR whatever
   `[tool.lab_commons.parts.refs]` says. Any doubt (no record, no merge-base) waives nothing. The full scarce
   parts run on `integrate/main` after the merge; a red one there keeps ONE `integration` issue naming every
   merge since its last green and the sessions (`Lab-Session`/`Claude-Session` trailers) that merge brought.
3. `integrate/main` takes nothing else: with `pr_merges_since` declared, a client push adding a commit to it is
   refused at pre-push (`INTEGRATION-TAKES-ONLY-FORGE-MERGES`). The one exception is the emergency
   BREAK-GLASS (user ruling 2026-10-19), for when the forge itself is down or its auto-merge is broken, so
   the fix cannot arrive through a PR. A direct push is admitted only when EVERY new first-parent commit
   carries a `Break-Glass: <reason>` trailer. No env var or config flag opens it, and an empty reason is
   refused at commit-msg. Every `forge serve` tick then keeps one `integration` issue per break-glass
   commit past `pr_merges_since`, naming the commit and its reason (`dev_lab.dev.breakglass`). Put only
   the emergency fix through it, follow up with a PR for anything else, and close the notice by moving
   `pr_merges_since` past the commit in that PR.

   The same door is the INTEGRATOR'S BACK DOOR (user ruling 2026-10-21): the integrator may merge a PR the
   forge cannot auto-merge. Merge its head into `integrate/main` locally (`git merge --no-ff`, never a rebase),
   write `Break-Glass: <named reason>` in the merge message beside any `Merge-Audit:` lines, and push. The
   notice records WHO (the commit author) and WHY (the reason).

4. `main` moves only by `integrate promote <sha>` on a full PASS, as below.

All maintenance happens on gitea (user ruling 2026-10-19): PRs are opened, judged and merged there, and
auto-merge is gitea-only. GitHub (`DawnEver/*`) is ONLY a push mirror (`branch-set.md`); nothing reads or
writes its pull requests.

```toml
[tool.lab_commons.branchset]
ephemeral = ['pr/*']

[tool.lab_commons.integrator]
pr_merges_since = "<the integrate/main sha the rule starts after>"
```

## Auto-sync: the forge syncs a behind PR head

User ruling 2026-10-21: integration is automatic. Wherever the forge merges PRs, each `forge serve` tick (the integration step,
`dev_lab.dev.forgeautosync`) takes every open PR into integration that it did not merge and whose head does
not contain `origin/<integration>`, and merges integration INTO the head in a worktree under the git directory:
a merge commit (`Merged-Branch: <integration>`, first parent the head), never a rebase or a force, pushed under
the head's own name. A lock left stale or conflicted by the merge is relocked inside the merge commit through
the dependency door. The new head gets its parts by the normal path, then merges like any other PR.

- Once per integration tip per head: each outcome is an `integration/sync` status on the head naming the tip,
  and a serving host's `pending` claim keeps N hosts to one (a claim older than 1 h is presumed dead).
- It never resolves a textual conflict outside `uv.lock`, never touches a head outside `ephemeral` or one
  committed inside `auto_sync_quiet`, and never a head holding another open PR's unmerged head: that PR is
  named as the one it waits behind, and the first tip after it merges syncs this one.
- The merge passes the merge audit before it is committed, and the commit runs the repository's hooks.
- Each refusal is said once, in the head's status and the PR's integration comment. `forge integration`
  (no host) only reports.

```toml
[tool.lab_commons.integrator]
pr_merges_since = "<sha>"   # auto-merge on; auto-sync rides it, no switch of its own
auto_sync_quiet = "10 min"  # the default
```

## Roles

| role | does | never |
|---|---|---|
| human | goals, rulings, forge settings, remote deletions | accepts "done" without tests |
| author | its `pr/*` branch, push, PR, `forge sync`, fixes its own PR's reds | merges another branch |
| producer | produces the parts it claimed | produces unclaimed parts |
| forge | the ONLY merger of `integrate/main` | merges a PR lacking a part |
| integrator | keeps the pipeline flowing: producers alive, every PR judged, stuck PRs routed to their authors, `promote`, break-glass | hand merges, direct pushes to `integrate/main`, runs suites |

Who the integrator is, and where it runs, moves; nothing records it. An integrator is a session like any other: it
reads the forge and writes nothing else.

## What enforces it

| rule | mechanism |
|---|---|
| INTEGRATION-TAKES-ONLY-FORGE-MERGES | pre-push `session-branch`, from `[tool.lab_commons.integrator] pr_merges_since` |
| a `pr/*` head pushes with no row | `[tool.lab_commons.branchset] ephemeral = ['pr/*']`, judged by the forge's branch-set test |
| PRS-TARGET-INTEGRATION | the integration tick retargets a PR opened against the trunk, with a comment |
| no long-lived child | `branchset.sessions` names only the integration branch; anything else is merged and deleted |
| every repo declares the flow | `famtests.branchset.assert_the_pr_flow_is_declared` |

## The integrator's loop

Each tick, and nothing else:

1. `python -m dev_lab.dev.forge queue` -- what is waiting, what is starved, which host is idle.
2. `python -m dev_lab.dev.forge integration` -- every child's standing, the forge's merges, the branch rows.
3. A PR stuck past an hour: its reason is already its one integration comment; route it to its author's session.
4. `integrate promote <sha>` when an integration commit's every part stands PASS at scope `full`.
5. Break-glass notices: read the `integration` issue each break-glass commit opened, and close it with the PR
   that moves `pr_merges_since` past the commit.
6. A PR left open after its head landed is closed by the forge's tick; to do it now:
   `python -m dev_lab.dev.forge pr close-landed <n>` ([branch-set.md](branch-set.md#landed-pull-requests-close)).

An integrator runs no test, merges no branch by hand, and pushes nothing to `integrate/main`.

## The PR reviewer is advisory

`PR-REVIEW-IS-ADVISORY` (`dev_lab.dev.forgereview`). The forge only orchestrates: each open, non-draft PR
into `integrate/main` on gitea is reviewed ONCE per head sha by the command the repo declares; its stdout is
the sharp-review findings JSON (`schema_version` 2, read by `dev_lab.dev.forgereview_findings`; an unknown
version is refused by name). The forge posts one PR comment of the findings and a `tests/review` commit status.

**What is read** (`REVIEW-SCOPE`, `dev_lab.dev.forgereview_scope`). The budget is the reviewer's, so it bounds a
slice, not whether a head is read at all:

- *The branch's own change.* The range starts at the merge base with `integrate/main`, which a merge of
  `integrate/main` moves with it -- so merged-in upstream work is never re-read.
- *Since the last review.* When an earlier head of the same PR was reviewed (its review comment is the record)
  and no merge of `integrate/main` came after it, the range starts there: a push is read for what it added.
- *Minus generated files.* The family's whole-file renders (`famfiles.GENERATED`: `uv.lock`, the rendered
  ignores, hooks and workflows) and the repo's `derived` globs (goldens, rendered blocks). Their generator is
  reviewed, not its output. A head of only generated files is `success`, nothing to review.
- *In slices, one lens each.* The reviewable files are packed, a directory kept whole when it fits, into slices
  of at most `max_diff_bytes`; each runs the command once with `{paths}` and `{lens}` -- `strict` for the
  `strict` globs (hooks, rules, `tests/architecture`, contracts), `light` for the `light` ones (docs, memory,
  Markdown), `standard` for the rest. The outputs merge into one document (a finding once per id); a declared
  `synthesis` command then reads it (`{findings}`) over the whole range for what crosses slices.

**It gates nothing but one state**: `tests/review` is never a part, so `integrate promote` and push admission
never wait on it, and the forge's auto-merge waits only on a head the slices cannot hold -- its reviewable change
over `max_total_bytes`, one file alone over `max_diff_bytes`, or several slices for a command without `{paths}`.
That head is HELD on its own context, `tests/review-hold` = `pending` (never read from a description), until a
session reviews it and releases it: `python -m dev_lab.dev.forge status post <sha> --context tests/review-hold
--state success --description "reviewed by <who>"`. So an unreviewable head never auto-merges unreviewed. A second tick on the same head runs nothing and posts
nothing. A failed command posts `error` and is not retried on that head; a HOST that cannot run the review
(a capability undeclared, the command absent or its module missing) posts `error` `not reviewed: cannot run on host
<host>: <why>` once and leaves the head claimable by a capable host, or by itself once fixed.
When EVERY reviewer reports `exhausted` or `auth`, nothing is commented and `tests/review` is `pending` with
`takeover pending`: not a failure, never blocking; the integrator session lists those heads and reviews them
through the same method (takeover chain: anthropic API, then a ccc session, then a ccds session).

It runs inside the integration step of `forge serve` (`forgeservesteps.prompt`): the review host follows the
integrator, so no machine-file capability selects it. The forge holds no model client, prompt or key -- the
command reads its own (`ai_lab`, the `pr-review` task key). Per repo:

```toml
[tool.lab_commons.review]
# {range}: <base>..<head>; {paths}: the slice's paths, one argument each; {lens}: strict | standard | light
# {capabilities.ai_lab.python}: THIS host's ai-lab interpreter; the module reads the method it packages
command = ["{capabilities.ai_lab.python}", "-m", "ai_lab.review", "--range", "{range}", "--lens", "{lens}",
           "--model", "<id>", "--paths", "{paths}"]
synthesis = []             # optional: ["...", "--findings", "{findings}", "--range", "{range}"]
max_diff_bytes = 200000    # one slice
max_total_bytes = 4000000  # one head
derived = []               # generated-file globs beyond famfiles.GENERATED
strict = ["**/hooks/**", "**/rules/**", "tests/architecture/**", "**/contracts/**"]  # the default
light = ["docs-src/**", "**/.claude/memory/**", "**/*.md"]                          # the default
claim_stale = "1 h"        # the default
```

Every serve host may review (usually one host acts as integrator); a CLAIM keeps it to one. Before running the
command a host checks it can start it -- a missing executable, module or capability posts `error` with its reason, like every failure --
then posts `tests/review` = `pending`, `claimed by <host> at <time>, reviewing`, and replaces it with the final
status. Any other host skips a head whose `tests/review` carries any status, pending included, unless it is a
released claim (`released by ...`) or a claim older than `claim_stale` (default `"1 h"`, above the command's
own 30 min timeout): a host that died mid-review never blocks a head for good.

Undeclared, nothing is reviewed. Exit 2 is the command's named refusal (bad method, version or range): its
stderr reason is the `error` status.

The in-process reviewer's keys (`model`, `max_tokens`, `rules`) and its machine-file capability are retired
and refused by name (`lab_commons.hpc.retired`).

## Session branches: one writer, by git

Every repo declares its long-lived branches in `[tool.lab_commons.branchset] sessions` -- the integration
branch is one of them. One host's one repo may carry SEVERAL sessions at once, each on its own branch in its own
worktree (the main checkout is just one more worktree). So a branch is protected for what it IS, never for
where it is checked out or which box pushes it: both move.

ONE-WRITER-PER-SESSION-BRANCH is git's own two mechanisms, and nothing is built for it (user ruling
2026-10-14: no lease refs -- every push would read and write origin, and every fetch would carry them):

- **Locally**, a branch is checked out in at most one worktree, so two sessions of one host and repo never
  share a branch.
- **Remotely**, a plain push is compare-and-swap: origin refuses a non-fast-forward, so a writer on a stale
  tip loses and must merge first. SESSION-HISTORY-ONLY-GROWS refuses the force that would bypass it.

The rest are refused at pre-push by the base row `session-branch` (`dev_lab.dev.sessionbranch`), from
local reads only -- no network call beyond the push itself -- with no escape hatch:

| rule | refuses |
|---|---|
| PUBLISH-IS-THE-LOCAL-REF | a push to `refs/heads/X` whose local ref, `HEAD` resolved, is not `refs/heads/X`: `HEAD:X` from another branch, `Y:X`, a bare sha, a detached HEAD |
| SESSION-HISTORY-ONLY-GROWS | a push whose old remote tip (as git hands it to the hook) is not an ancestor of the new one: a forced non-fast-forward, and a deletion |
| INTEGRATION-TAKES-ONLY-FORGE-MERGES | a new first-parent commit on the integration branch past `pr_merges_since` that the forge did not merge: replaces INTEGRATION-IS-MERGES-ONLY for that branch |

Before `pr_merges_since` stands, INTEGRATION-IS-MERGES-ONLY holds instead: a new first-parent commit on the
integration branch after `merges_only_since` that is not a two-parent merge with a `Merged-Branch:` trailer
whose merge audit passes.

The CPU/box seat stays a RESOURCE lock; it decides no ownership.

## Child branches sync from integration

`DOWNSTREAM-SYNCS-INTEGRATION`: a child merges only integration. Another child's work reaches it once, through
integration.

```
python -m dev_lab.dev.forge sync                       # merge integration (and watched refs) if clean
python -m dev_lab.dev.forge sync --watch origin/<ref>  # opt in to one more upstream; --unwatch, --list
```

- It trial-merges each upstream with `git merge-tree --write-tree`, reports how far behind and which files
  conflict, and merges (never rebases) only when every merge is clean: integration first, then each watched ref.
- On a conflict it merges nothing and names the files; resolve with a plain `git merge`.
- It never pushes. The owner measures what they touched and pushes.
- A child more than `[tool.lab_commons.integrator] behind_max` commits behind integration is the forge's to say:
  `forge serve` runs the behind/conflict report every tick and raises an `integration` alarm, naming this command,
  for each child past the bound or conflicting. No push is refused for it (toolchain plan P3).
- The watched set is the checkout's git config `branch.<child>.labSyncFrom`, never a committed file.

## Pull requests target integration

`PRS-TARGET-INTEGRATION`: every pull request targets integration; one opened against the trunk is retargeted
with a comment saying why. Each child carries one PR at most.

`ONE-SESSION-ONE-PR`: a launcher (`ccc`, `ccds`, `codc`; cc-config `scripts/shared/machine.mjs`) issues one
`LAB_SESSION` per session, inherited by every child. The `lab-session` commit-msg row writes it as a
`Lab-Session:` trailer (`dev_lab.dev.labsession`). A commit without `LAB_SESSION` is never refused, agent or
human (user ruling 2026-10-21): it carries no trailer and the rule does not judge it, so a path no launcher
starts (the VS Code Claude extension, the codex desktop app, `codc` attached to a shared app-server) keeps
committing. Only a session that has an id is judged. `Claude-Session:` is prose nothing reads. The rule is the guidance of a
development agent focused on ONE task: it gathers all of its work on one PR. A PR never blocks the flow (user
ruling 2026-10-25): `forge pr create` always opens the PR, and for a head that shares a session with another open
head it names that head's branch, on stderr and as an `Admission:` line in the PR body (`dev_lab.dev.pradmit`).

`NO-STACKED-PRS`: `forge pr create` tells a head holding a commit of another open PR's head that integration does
not hold (`trialmerge.shares_unmerged`) that it is stacked and lands only after that PR, and opens it anyway.

## The integration tick

```
python -m dev_lab.dev.forge integration
```

- Fetches origin and each PR head (`pull/N/head`).
- Per child, says: merged into integration at `<sha>`, or deferred and why; behind N, clean or the conflicting
  files; its upstream set; the head's `tests/<part>` states and the open `area:*` issues citing it;
  promoted once the trunk holds the merge.
- **The report is one comment per PR**, found by a hidden marker and edited in place. A child without a PR gets
  an `integration` commit status on its head, posted only when it changed.
- The tick never writes a child branch.

## The ready predicate

`python -m dev_lab.dev.integrator queue [--json]` derives the merge queue from origin every time; nothing
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

- `dev_lab.dev.mergeaudit` computes, per test, what a clean three-way merge would hold. A deviation is
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
- `MERGE-RESOLUTION-DECLARED` (`dev_lab.dev.mergeresolution`): a merge whose parents conflict lists each
  conflicted file once, `<path>: <class> -- <why>`. The forge enforces it: a PR is not merged while a merge
  commit its head adds over integration leaves one undeclared (`forgemerge.decide`), whoever made that merge,
  client or web UI. A message cannot be amended, so the remedy is to redo that merge with the declaration. The
  `merge-resolution` commit-msg hook makes the same judgement early, on the merge being committed.
- A shared count or pin that conflicts is arithmetic to redo on the merged tree, never a side to pick
  ([alignment](alignment.md)).
- Price a batch before touching a tree: `git merge-tree --write-tree --name-only <integration> origin/<branch>`
  lists a merge's conflicts without a checkout.

## Waking the integrator

The integrator may poll (fetch, `forge integration`, act, reschedule) or be woken by the observer. A wake
carries no state: it only means "derive again now". Polling is the floor that makes a lost wake harmless.

**The observer is `forge serve`, on EVERY host.** No host owns integration. Each serve tick derives the
queue (`integrator.observe`), and every row that asks a session to act -- a PR READY to merge, the
integration tip PROMOTE-able, a child or tip BLOCKED on a red to route -- is kept as ONE forge issue titled
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
| the forge's auto-merge is broken | nothing reaches `integrate/main` but a break-glass push, whose issue names it |
| a child blocked on `failure` | listed with its tip; it is the owner's to fix, through its `area:*` issue |
