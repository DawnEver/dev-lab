---
created: 2026-09-18
accessed: 2026-09-18
---

# The recorded remedy for a swept commit does not work, and three commits in one day proved it

## The rule this repo has on record, and why it is now known to be insufficient

`.claude/rules/workflow.md` and the 2026-09-05 entry
`a-commit-swallowed-another-agents-rows-and-then-described-itself-falsely.md` both name one remedy:

> **`git commit -F - -- <explicit paths>` commits ONLY those paths.**

and one cheap check:

> Before writing a commit message that makes a CLAIM, read `git diff --cached -- <path>`.

Both were FOLLOWED today, by two different agents, and both commits were swept anyway.

## THE MECHANISM: the race window is INSIDE the commit

`pre-commit` STASHES unstaged files and RESTORES them from a patch around every hook run. So when
two agents commit in one checkout, each one's stash/restore cycle rewrites the other's index
entries mid-flight. The index a commit writes is not the index its author staged.

That is why the recorded remedy fails. `git commit -- <paths>`, `git apply --cached` against a
synthesized HEAD blob, and a `git diff --cached --stat` verified clean IMMEDIATELY BEFORE the
commit are all checks OUTSIDE the window. One agent did all three and still landed seven files
against four staged.

**Staging by named path is not sufficient on a shared checkout with pre-commit installed. The box
CPU lock does not cover `git commit`, so nothing serialises this.**

## The three commits, measured from the history rather than from a report

| sha | its message says | its diff carries |
|---|---|---|
| `6019d20` | the pre-commit ceiling arm, four paths | seven -- plus another lane's `_famconfig_refusals.py`, `_famconfig_rows.py`, `test_dev_famconfig.py` |
| `e41aa13` | (vanished from the log entirely) | deleted a lane's test file and 87 census lines |
| `a2045dd` | "re-land the pre-commit hook-unit arm" | NONE of that arm -- 987 lines of the `[tool.ruff]` lane's section base instead |

`a2045dd` is the sharpest of the three: its title names an arm, and not one file of that arm is in
its diff. The arm it names is in `6019d20`, its ancestor, so the CONTENT is all present and green.

## THE CONTENT IS CORRECT. THE RECORD IS NOT.

Same shape as 2026-09-05. Nothing was lost; `verify` passes over every affected path. What is wrong
is that a reader reconstructing where the ruff section base came from is misled by both halves --
the commit that carries it does not mention it, and the commit whose message describes it does not
carry it.

Not repaired, for the same reason as last time and one more: `--amend` is a family deny row,
`reset` is forbidden here, and rewriting a shared branch under lanes that are still live would
trade a misleading record for a real hazard. **This file is the correction.**

## What actually fixes it, and it is not a rule

Three in one day is a MECHANISM failure, not three mistakes by three agents -- and the two agents
who hit it had each read the rule and applied it. Adding a fourth sentence to the rule page would
be re-arguing a refused hazard in prose.

The fix is structural, and there are two shapes:

- **one lane per worktree**, so no two agents share an index; or
- **a commit queue** -- a lock that covers `git commit` the way the box lock covers the CPU.

Until one of those exists, the operating rule is CONCURRENCY LIMIT ONE: lanes may edit a shared
checkout in parallel, but exactly one may hold a commit at a time, and serialising them is the
coordinator's job rather than each lane's.

## The coordinator's error, stated plainly

The fan-out that caused this was fenced BY TOPIC on the assumption the surfaces were disjoint.
They were not: `famconfig.py` and `_famconfig_survey.py` were shared by all three lanes. A fence
that names topics does not bound files, and the lanes correctly reported the collision before any
damage -- the first one flagged it in advance, which is the first time that has happened here.
The damage came from continuing to let them commit after the collision was known.
