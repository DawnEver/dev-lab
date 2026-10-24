# One branch per session

Each working session keeps exactly ONE long-lived branch, declared in `pyproject.toml`, and merges its work into
it (`ONE-BRANCH-PER-SESSION`). Every other branch is merged and then deleted (`MERGE-OR-DELETE`): there is no
third state, and a parked tag or renamed branch is the same debt. Run `python -m dev_lab.dev.branchset` to see
what to merge and what to delete, and `--apply` to delete the merged local ones.

## The declaration

```toml
[tool.lab_commons.branchset]
trunk = 'main'                 # required
sessions = ['integrate/main']  # one per session or lane owner; [] when there are none
ephemeral = ['pr/*']           # default []: glob namespaces of short-lived PR heads, pushable with no row
prune_merged = true            # default false: every serving host deletes merged idle origin branches
grace_hours = 24               # default 24: idle time before a branch is pruned (merged) or alarmed (unmerged)
```

Read by `dev_lab.dev.branchset.declared_branchset(root)`; a missing or malformed table, or an unknown key,
raises `BranchSetNotDeclared`. Adding a long-lived branch is a reviewed edit of `sessions`.

A branch in an `ephemeral` namespace is the head of ONE pull request: the push hook and the census accept it
without a row, and the forge deletes it once no open PR has it as head and it has sat idle `grace_hours` (merged
or closed; `branchprune`'s `ephemeral-done` rule, no `prune_merged` needed). A forge merge deletes it at once.
Registering a branch in `sessions` to get it pushed is never the remedy; push it under `pr/` instead.

## The census and the candidates

Every read is of local refs, so `git fetch --prune` first: the remote is the authority.

| call | answers |
|---|---|
| `census(root, branchset)` | `undeclared_origin` (debt), `local_debt`, `unpushed` (undeclared, holding commits no origin ref has) |
| `merge_candidates(root, branchset)` | every undeclared branch and parked tag, `deletable` when its tip is in the trunk's authority or a session branch; anything else is merged first |
| `python -m dev_lab.dev.branchset [--root R]` | prints the candidates as `delete` / `merge` rows; deletes nothing |
| `python -m dev_lab.dev.branchset --apply` | deletes merged LOCAL branches and tags, re-checking ancestry at the moment of deletion; lists origin's for a human |

- **Merged means merged into the REMOTE authority.** A local `main` that is ahead and unpushed answers "merged"
  about work whose only published copy is the branch you are about to delete.
- The question is whether the CHANGE is there, so the instrument is `git cherry` against the remote, which sees
  through cherry-picks and rebases; the ancestor test does not.
- Deleting a branch on origin BY HAND is a human's action (the forge's automatic prune, below, is the same
  human decision made once as data): the door prints `git push origin --delete <b>`.

## The assertion consumers run

`dev_lab.dev.famtests.branchset.assert_the_pr_flow_is_declared(root=)` judges the DECLARATION only: the repo
declares `pr_merges_since`, the `pr/*` ephemeral namespace and its integration branch in `sessions`. No test
reads origin's refs or a host's local branches: such a test judges the environment, not the code under test,
and reds every unrelated PR (ruling 2026-10-24).

## Judged on the forge, never at push

The branch set is the forge's alone (toolchain plan P3; user ruling 2026-10-24): the forge's
`branchset` status is the one judgement, and the pruner below alarms or deletes an undeclared origin branch. No pre-push
row reads the branch set, and none can be declared: the push-time module is retired. Every open PR head into
integration carries a `branchset` status (`dev_lab.dev.forgeheadgate`): `failure` when its branch is not admitted
by the set its own commit declares, naming the ephemeral namespaces and `sessions`. Agent lanes are local: only
the declared branches reach origin.

## Pruning origin

Finished branches still pile up on origin, so the forge prunes them (`dev_lab.dev.branchprune`). The host
EVERY serving host -- no host owns this; a deletion is pinned to the judged sha, so a raced second delete is a no-op --
surveys origin on every `forge serve` tick, after the tick's `git fetch --prune`. No other host reads or
deletes anything. Undeclared branches whose tip has been idle for at least `grace_hours` are judged:

| origin branch | rule | what happens |
|---|---|---|
| declared (`trunk`, `sessions`, the integration branch) | none | never touched |
| idle less than `grace_hours` | none | never touched |
| head of an open pull request | none | never touched |
| tip is an ancestor of `origin/<integration>` or `origin/<trunk>` | `merged-idle` | DELETED through the forge API when `prune_merged = true`; otherwise listed as `deletable` |
| anything else | `unmerged-stale` | ALARMED (`stale-branch`) with its age, never deleted |

- **Remote deletion is a human decision, expressed as data.** `prune_merged` defaults to `false`. Until a repo
  opts in, `forge integration` and `forge queue` print each merged branch as `deletable`, and nothing is deleted.
  An agent never deletes a remote ref by a raw push (`PUSH-REMOTE-DELETE`); it deletes one through LOSSLESS-DELETE,
  `python -m dev_lab.dev.branchprune delete <branch>...`, which refuses unless every commit lives elsewhere.
- **Each deletion is pinned to the sha the survey judged.** The live tip is read from the forge first. A branch
  that moved is kept, because its new tip is somebody's new work.
- **Each deletion is logged** as one line, `{"event": "lab_commons.forge.prune", "ref", "sha", "rule"}`. The
  tick then raises one `pruned` alarm naming every deleted branch and its sha, so a deletion can be undone by
  pushing that sha back.
- **Idle means the tip's committer date.** A branch nobody has committed to for `grace_hours` is idle, whenever
  it was pushed.

### Landed pull requests close

An open PR holds its head branch against every delete, so a PR whose head reached its base some other way (a
break-glass or containment merge) would hold it forever. Each `forge serve` tick, before the prune, closes every
OPEN PR whose head sha is an ancestor of `origin/<base>` (`merge-base --is-ancestor`, the only criterion): one
comment `landed: head <sha12> is on <base> (merged by <sha12>)`, close, then the head branch through
LOSSLESS-DELETE when the branch set allows it (an `ephemeral` namespace, or `prune_merged` for an undeclared
branch). A PR not contained is never touched; a closed PR is not listed again. Each close is one
`{"event": "lab_commons.forge.pr-close-landed", "pr", "head", "sha", "base", "merged_by"}` line. A person or
agent runs the same: `python -m dev_lab.dev.forge pr close-landed [<n>...]` (no number: every open PR),
which refuses a named PR whose head is not contained (`dev_lab.dev.prlanded`).

### Mirrors

A gitea push mirror runs a mirror push, which PRUNES: a branch deleted on gitea is deleted on the mirror at its
next sync. Measured 2026-10-13: lab-commons mirrors to `github.com/DawnEver/lab-commons` (`sync_on_commit = true`,
`interval = 8h`), and both carry the same 14 heads. consumer-a and consumer-b have no push mirror. What the
repository admin must keep set (Settings > Repository > Mirror settings):

- a PUSH mirror, not a pull mirror. Its mirror push is what carries a deletion, and nothing else does.
- `interval` non-zero. `sync_on_commit` fires on a push, and a deletion through the API is not a push, so the
  interval sync is the one guaranteed to carry it. Expect up to `interval` (8 h here), or the next push to any
  branch, before the mirror drops the branch.
- a mirror credential with delete rights on the GitHub side (a token with `contents: write`). Without them
  the mirror's `last_error` says so, under the same settings page.
