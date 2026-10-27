---
name: p3-local-gates-keep-harm-and-format-only
description: Toolchain plan P3 -- the local hook and PreToolUse inventory, its measured fire counts, and what moved to the forge or became a hint.
metadata:
  type: decision
tags: [hooks, guards, forge, toolchain-plan]
created: 2026-10-23
accessed: 2026-10-23
---
# P3: local gates keep irreversible harm and second-scale format checks

The forge already judged most of what the local hooks refused, so one plain push could be refused two or three times
(root cause R2). The rule now: a local check stays only if it guards against irreversible harm or is a format check
that runs in seconds. Anything the forge judges on the pushed sha is the forge's alone. A style guard is a hint.

## Measured fire counts

There is no refusal JSONL log, so these counts come from scanning the Claude transcripts in
`~/.claude-evans/projects/**/*.jsonl` modified since 2026-10-09 (489 files). A refusal can be quoted again later in
the same transcript, so each count is an UPPER BOUND, roughly double the real number. Nothing on disk records false
positives. Three were seen live in this session: RECURSIVE-GREP on a grep over one small src dir, and
PUSH-REMOTE-DELETE and PUSH-FORCE firing on Python heredoc text that only MENTIONED those flags.

| guard | mentions |
|---|---|
| BARE-TEST-INVOCATION | 362 |
| RECURSIVE-GREP | 254 |
| GIT-NETWORK-VERB | 246 |
| BARE-INTERPRETER | 137 |
| RAW-PROCESS-KILL | 32 |
| OUTPUT-REDIRECT-IS-DATED (consumer-c row) | 22 |
| ENV-MUTATION-THROUGH-THE-DOOR (consumer-c row) | 21 |
| WORKTREES-STAY-INSIDE | 20 |
| CODE-IN-CODE-ROOTS (codeplace write hook) | 16 |
| GIT-STASH | 12 |
| SUBAGENT-NO-PUSH | 8 |
| PUSH-REMOTE-DELETE / PUSH-NO-VERIFY / REPORTS-LIVE-IN-MEMORY / GIT-COMMIT-AMEND | 5 / 4 / 3 / 3 |
| git hook: commit-msg merge-audit | 100 |
| git hook: pre-commit ruff + ruff-format (repo layers) | 159 |
| git hook: pre-commit architecture-fast (consumer-c layer) | 68 |
| git hook: pre-push session-branch | 30 |
| git hook: pre-commit ephemeral-refs | 22 |
| git hook: pre-push branchset-push | 22 |
| git hook: pre-push lock | 15 |
| git hook: pre-commit stray-files / scratch-commit | 8 / 8 |

## Decisions

- Now forge-only, no longer in the family base table:
  - `ephemeral-refs` is checked by `famtests.ephemeralrefs`.
  - `scratch-commit` is checked by `scratch.assert_scratch_never_committed`.
  - `branchset-push` is checked by `famtests.branchset.assert_origin_branches_declared` and by the pruner's alarms.
  - `behind-push` is raised as a `forgeintegration` `integration` alarm.
  - `pr-admit` is enforced by `forge pr create`, which calls `pradmit.create_refusal`.

  Each of these modules can still be declared as a repo's own row.
- `stray-files` is now a post-commit hint, because the forge cannot see untracked files.
- The PreToolUse rows GIT-NETWORK-VERB and RECURSIVE-GREP, and the codeplace CODE-IN-CODE-ROOTS write check, are now
  hints. The engine sends them as `additionalContext`, and any refusing row that also fires still wins
  (`hooks.SEVERITIES`).
- Unchanged and still local:
  - the file checks;
  - `commitizen` and the stamping commit-msg rows;
  - `session-branch` (history only grows; publish from the local ref);
  - the `lock` pin, which costs milliseconds (user ruling 2026-10-22);
  - `pushgate` for trunk pushes;
  - every irreversible deny row: force, delete, no-verify, amend, reset, stash, stage-everything, subagent push,
    process kill, worktree placement, and forge writes.
- Open, for the user to decide: `merge-audit` stays local even though the plan calls it forge-only. Its remedy is a
  trailer inside the merge commit. A pushed merge cannot be amended, so a red from the forge would have no way out.
