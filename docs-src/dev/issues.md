# Issues

An issue records intent: what should change and why. Its state (todo, in progress, ready, done) is derived from
origin's refs and the forge's parts, never kept by hand. Reference it from commits (`Refs #N`, `Closes #N`),
claim it with `forge issue claim N`, and use labels only for what the scheduler and the store read. Write
issues only through `python -m dev_lab.dev.forge issue ...` ([the forge](forge.md#issues-and-pull-requests-the-door)).

## Linking a branch to an issue

- **`feat/<slug>` covers many issues, by commit**: each commit that works on one says `Refs #N` in its body.
- **`fix/<N>-<slug>` is one issue, by name.**
- **`Closes #N` goes on the commit that lands the change**; the forge closes the issue when that commit
  reaches the default branch.
- The reference lives in the body, never in the conventional-commit subject. A malformed reference (`Refs#12`,
  `closes 12`, `#12abc`) is warned about by the `issue-ref` commit-msg hook (`dev_lab.dev.issueref`), never
  refused.

## Claims

- A claim is a comment `claim <branch>`, written by `python -m dev_lab.dev.forge issue claim N [--branch B]`.
  Its provenance line `[<machine> · <agent> · <branch>]` says who claimed it, since every agent on a box shares
  one forge account.
- A later claim by the same claimant replaces its earlier one. Two claims naming different branches are a
  CONFLICT, reported and decided by the human.
- `@<user>` in a comment is a hint for a human, never a trigger for an agent.

## The derived state

`python -m dev_lab.dev.forge issue status N [--json]` computes it every time:

| state | derived from |
|---|---|
| `done` | the issue is closed, or a `Closes #N` (`Fixes`, `Resolves`) commit is on the default branch |
| `ready` | a branch referencing it has a tip whose `tests/<part>` parts stand PASS |
| `in-progress` | an origin branch carries a commit referencing `#N` not yet on the default branch, or is named `fix/<N>-...` |
| `todo` | open, and nothing on origin references it |

- It reads local remote-tracking refs, so run `git fetch --prune origin` first; each branch's tip is printed, so
  a stale answer is visible. It also lists every current claim and flags a conflict.

## Reds are area issues

- `python -m dev_lab.dev.forge route <run-record>` groups a record's reds by AREA and keeps each area in one
  open issue titled `area:<name>`. The repo declares its areas once, in `pyproject.toml`:

  ```toml
  [tool.lab_commons.areas]
  default = "triage"                       # where a red no glob claims goes
  jmag = ["src/pkg/adapters/jmag/**", "tests/**/jmag/**"]
  ```

- A row `- [ ] `<id>` (<part>) <outcome>` means: the latest record of the part that NOW selects `<id>`
  reported it red. Routing a record of part P replaces P's rows with its reds, and drops every other row
  whose part the record says no longer selects that id -- a retired part name, an id moved to another
  part, an id no longer collected. A green id has no row; nothing is ever ticked.
- An INCONCLUSIVE record is routed too: its reported reds are rows, and the ids it never reported are one
  `<part>: never reported` row per area. A record covering no test routes nothing.
- Every open `area:*` issue is re-rendered on each record. Routing never closes one: with no `- [ ]` left,
  `forge tidy` (`green_areas`) closes it ([issues never rot](#issues-never-rot)).
- Routing the same record twice writes nothing. This list replaces every hand-kept list of open reds.

## Issues never rot

`forge serve` runs `forge tidy` on every host, every tick, for every repo it serves (user ruling 2026-10-15;
`python -m dev_lab.dev.forge tidy --dry-run` shows the plan). Every rule is ON; a repo only tunes it in
`[tool.lab_commons.forge.issue_hygiene]` -- these are the defaults:

```toml
[tool.lab_commons.forge.issue_hygiene]
host_duplicates = true       # DELETE every machine-made `forge hosts` issue but the oldest (the one home)
green_areas = true           # close an `area:*` issue with no `- [ ]` row
request_max_age_days = 14    # close a `forge:request` issue older than this
work_max_idle_days = 14      # close a WORK issue not updated for longer than this
```

- A WORK issue is one no machinery keeps: not the hosts issue, not `area:*`, not a request, not an alarm kept
  as an issue (`integration: ...`, `starved: ...`; `forgealarm.ISSUE_KINDS`), and with no hidden marker in its
  body. A comment, a claim or an edit counts as an update.
- A comment carrying a hidden `<!-- lab-commons:<kind>... -->` marker whose kind is no `forgepulls.Marker`
  member is DELETED, always: its writer is retired and nothing else will touch it. The writers take their
  kind from that enum, so the set of live kinds is the writers' own.
- An `integration: <branch> is BLOCKED on a red part` issue is kept by `forge serve`'s prompt pass
  (`forgeroute.reconcile`), not by tidy: a row the queue no longer derives closes its issue on the next tick.
- Everything is said in ONE summary comment on the hosts issue; a closed issue reopens to undo.
- lab-commons declares no table: it runs on the defaults. A downstream repo declares the table only to tune
  a value; the keys are refused by name when unknown.

## Labels the machinery reads

| label | read by | effect |
|---|---|---|
| `priority:user` | the scheduler | adds the declared boost to a PR or issue |
| `priority:<n>` | the scheduler | adds `n` |
| `forge:request` | the scheduler | makes the issue a queued request (`producer = "<declared name>"` and `sha = "<40-hex>"` in its body) |
| `request:done` | serve | a request whose producer exited 0; its requester closes it to sign off |
| `keep` | the artefact store | pins its sha's artefacts past retention ([artefacts](artefacts.md)) |

No other label carries state.
