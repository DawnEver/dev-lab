---
name: the-worktree-interpreter-row-is-anchored-not-wildcarded
description: A consumer's allow guard refuses any row that leads with `*`, and 86 of its 271 rendered rows did — emitted by autodoors.claude_rows, never by glob_for — so the worktree interpreter spelling is anchored on WORKTREES_REL, the derivation refuses a leading wildcard, and the absolute-path spelling is named as the part no tracked row can admit.
metadata:
  type: project
created: 2026-10-06
accessed: 2026-10-06
---

# The worktree interpreter row is anchored, not wildcarded

A consumer's architecture suite carries this property over every row of its block:

```python
body = entry[len('Bash(') : -1]
assert not body.startswith('*'), f'{entry} leads with a wildcard, which permits any invocation prefix'
```

MEASURED 2026-10-06, in that consumer, by rendering the block against this repo's working tree and
reading the result: **271 rows, 86 of them leading with `*`**, every one of the shape
`Bash(*/.venv/Scripts/python.exe scripts/... *)`.

## Where they came from, and where they did not

- **Not `glob_for` / `portable`.** The derivation renders `Bash(.venv/*/python* ...)` for every
  remedy spelling a venv interpreter, prefix literal or `./`. The first hypothesis to test was that
  `portable` emitted the worktree spelling; it does not, and `glob_for`'s own pinned row is the
  proof.
- **`lab_commons.dev.autodoors.claude_rows`**, one line:
  `heads = [*_interpreters(), *(f'*/{"/".join(parts)}' for parts in VENV_LAYOUTS.values())]`. The
  leading `*` was there BY CONSTRUCTION, added 2026-10-05 (`1f96c91`, "isolate worktree dependency
  environments") for doors whose LAUNCHER may be another checkout's interpreter: the dependency
  bootstrap and every tracked script door. 5 derived + 266 door rows = 271; the 86 are
  2 layouts × (42 script doors + the bootstrap door).
- **The 55 → 271 expansion is spellings, not roads.** The pre-2026-10-05 block was one row per door
  (head `.venv/*/python*`): 5 derived + 7 door modules + 1 shell door + 42 script doors = 55. The
  same population now renders six spellings for each of 43 special doors (four relative, two
  worktree) and one for each of the other eight = 271. Same roads, more spellings.

## The fix, and what it does not cover

`WORKTREES-STAY-INSIDE` is real and enforced (deny row + `famtests.worktreeplace` detector + the
gitignore base, all derived from `worktreeplace.WORKTREES_REL`), so the directory that varies is
KNOWN and the row opens with a literal:

    Bash(.claude/worktrees/*/.venv/Scripts/python.exe scripts/gate/dep_sync.py *)

The `*` is the worktree's NAME and nothing else. What it does NOT admit: the same interpreter
reached by an ABSOLUTE path (`D:/repo/.claude/worktrees/lane/.venv/...`) or a `..` route. No row
that does not lead with `*` can — the command's first character is a drive or a root this file,
TRACKED IN GIT, cannot know — and the price is one permission prompt for an agent that spells it
that way. The road that stays prompt-free is the one `docs-src/dev/fanout.md` already spells: run
the door from the repository root, where the interpreter is this checkout's `.venv/...`.

## The second emitter, refused rather than rendered

`glob_for` CAN still produce the shape, one step later than it looks: `portable` rewrites the venv
spelling but keeps whatever precedes it, and a remedy whose path opens with a metavariable
(`<repo>/.venv/Scripts/python.exe ...`, `{root}/.venv/...`) has that prefix turned into `*` by
`_METAVAR`. No family remedy does this today (measured over `DENY_RULES` and the consumer's
adoption), and no spelling of such a road exists, so the derivation now REFUSES it by name
(`UnarguedAllow`) instead of rendering a row that leads with a wildcard.

A DECLARED row is deliberately outside both halves: it is the repo's own text, verbatim, which is
what the escape hatch is — the kit judges what it derives, the reader judges what somebody argued
for. A consumer whose guard also refuses declared `*` rows is stricter than this kit, and that is
its own decision to make.

## Row-count delta

None from this change: 271 → 271, with 86 rows re-spelled and none added or removed. A consumer that
re-renders sees a diff of exactly those 86 lines (plus the row order the dict insertion produces).
Its floor/headroom pins still move for the 55 → 271 reason above, which is that consumer's own
re-measurement to make.
