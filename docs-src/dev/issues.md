# Issues — intent on the forge, state derived from the refs

- This page is how the family uses forge ISSUES. The forge itself (protection, tokens, the door) is on [the forge](forge.md); readiness as ref movement is on [the three participants](the-three-participants.md).
- **An issue records INTENT only: what should change and why.** Its state is never kept by hand: no status labels, no "in progress" field, no assignee as a lock. A hand-kept state is a second copy of a fact the refs already hold, and it goes stale the first time a branch is deleted or rebased without anybody editing the label.
- Rule IDs: `ISSUE-IS-INTENT` (this page) and `VERDICT-AS-STATUS` (the `lab/gate` status this page reads).

## Linking a branch to an issue

- **`feat/<slug>` covers MANY issues, by commit.** Each commit that works on one says `Refs #N` in its message body; a branch can carry several.
- **`fix/<N>-<slug>` is ONE issue, by name.** The branch name alone links it; a `Refs #N` commit is still welcome.
- **`Closes #N` goes on the commit that LANDS the change** — it is what moves the issue to done when it reaches the default branch, and the forge closes the issue itself when that commit is pushed there.
- Every commit message stays a conventional commit; the reference lives in the body, never in the subject.
- **A malformed reference is WARNED about at `commit-msg`, never refused.** The family base's `issue-ref` hook (`lab_commons.dev.issueref`) names `Refs#12`, `closes 12` or `#12abc` — spellings the derivation cannot see — and lets the commit through; add a follow-up `Refs #N` if it matters.

## Claims

- **A claim is a comment `claim <branch>`, written through the door** (`python -m lab_commons.dev.forge issue claim N [--branch B]`; the branch defaults to the current one). The door opens it with the provenance line `[<machine> · <agent> · <branch>]`, which is what says WHO claimed it: every agent on a box shares one forge account, so an assignee cannot.
- A claimant is its `machine · agent`; a later claim by the same claimant replaces its earlier one.
- **Two claims naming different branches are a CONFLICT, reported and never resolved by a tool.** The human decides which lane keeps the issue.
- **`@<machine>` in an issue comment is a HINT, never a trigger.** It tells a human or an observer who should look; no agent starts work because it was mentioned, for the same reason a chat message is not readiness: origin is the only shared medium.

## The derived state

`python -m lab_commons.dev.forge issue status N [--json]` computes it every time it is asked:

| state | derived from |
|---|---|
| `done` | the issue is closed, or a `Closes #N` (also `Fixes`/`Resolves`) commit is on the default branch |
| `ready` | a lane referencing it has a tip whose `lab/gate` status is `success` |
| `in-progress` | an origin branch carries a commit referencing `#N` that is not on the default branch, or is named `fix/<N>-...` |
| `todo` | open, and nothing on origin references it |

- **Fetch-free: the caller fetches.** The branches are read from the local remote-tracking refs (`refs/remotes/origin/*`), so run `git fetch --prune origin` first when freshness matters. The output prints each lane's tip, so a stale answer is visible.
- `ready` reads the status the lane's own gate published: `python -m lab_commons.dev.verify` posts `lab/gate` on a clean HEAD after a judged run (see [the forge](forge.md), layer C). A lane whose gate never ran stays `in-progress`, which is the truth.
- The output also lists every current claim and flags a conflict.
