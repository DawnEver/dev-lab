# Issues

An issue records intent: what should change and why. Its state (todo, in progress, ready, done) is derived from
origin's refs and the forge's parts, never kept by hand. Reference it from commits (`Refs #N`, `Closes #N`),
claim it with `forge issue claim N`, and use labels only for what the scheduler and the store read. Write
issues only through `python -m lab_commons.dev.forge issue ...` ([the forge](forge.md#issues-and-pull-requests-the-door)).

## Linking a branch to an issue

- **`feat/<slug>` covers many issues, by commit**: each commit that works on one says `Refs #N` in its body.
- **`fix/<N>-<slug>` is one issue, by name.**
- **`Closes #N` goes on the commit that lands the change**; the forge closes the issue when that commit
  reaches the default branch.
- The reference lives in the body, never in the conventional-commit subject. A malformed reference (`Refs#12`,
  `closes 12`, `#12abc`) is warned about by the `issue-ref` commit-msg hook (`lab_commons.dev.issueref`), never
  refused.

## Claims

- A claim is a comment `claim <branch>`, written by `python -m lab_commons.dev.forge issue claim N [--branch B]`.
  Its provenance line `[<machine> · <agent> · <branch>]` says who claimed it, since every agent on a box shares
  one forge account.
- A later claim by the same claimant replaces its earlier one. Two claims naming different branches are a
  CONFLICT, reported and decided by the human.
- `@<user>` in a comment is a hint for a human, never a trigger for an agent.

## The derived state

`python -m lab_commons.dev.forge issue status N [--json]` computes it every time:

| state | derived from |
|---|---|
| `done` | the issue is closed, or a `Closes #N` (`Fixes`, `Resolves`) commit is on the default branch |
| `ready` | a branch referencing it has a tip whose `tests/<platform>` parts stand PASS |
| `in-progress` | an origin branch carries a commit referencing `#N` not yet on the default branch, or is named `fix/<N>-...` |
| `todo` | open, and nothing on origin references it |

- It reads local remote-tracking refs, so run `git fetch --prune origin` first; each branch's tip is printed, so
  a stale answer is visible. It also lists every current claim and flags a conflict.

## Reds are area issues

- `python -m lab_commons.dev.forge route <run-record>` groups a record's reds by AREA and keeps each area in one
  open issue titled `area:<name>`. The repo declares its areas once, in `pyproject.toml`:

  ```toml
  [tool.lab_commons.areas]
  default = "triage"                       # where a red no glob claims goes
  jmag = ["src/pkg/adapters/jmag/**", "tests/**/jmag/**"]
  ```

- The body is the area's current list: a red id is `- [ ]`, an id this record ran green is ticked `- [x]`, an
  id this record did not run is left alone. With no `- [ ]` left, the issue is closed naming the sha.
- Routing the same record twice writes nothing. This list replaces every hand-kept list of open reds.

## Labels the machinery reads

| label | read by | effect |
|---|---|---|
| `priority:user` | the scheduler | adds the declared boost to a PR or issue |
| `priority:<n>` | the scheduler | adds `n` |
| `forge:request` | the scheduler | makes the issue a queued request (`platform = "<p>"` in its body) |
| `keep` | the artefact store | pins its sha's artefacts past retention ([artefacts](artefacts.md)) |

No other label carries state.
