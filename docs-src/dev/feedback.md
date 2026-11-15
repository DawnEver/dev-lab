# Every wall teaches

A wall is any refusal or failure an agent hits. Each one names its cause and its door; one that does not is a
mechanism gap, and closing it comes before the task (principle `every-wall-teaches`, rule `WALLS-ARE-RECORDED`,
user ruling 2026-11-13). This page is the one description of the loop; the principle and the rule point here.

## The layers, outermost first

| layer | where it refuses | its door is written in |
|---|---|---|
| deny rows | `PreToolUse`: `.claude/hooks/deny-commands.js` judges each shell call | the row's `remedy` ([refusals.md](refusals.md)) |
| door refusals | a family door (`python -m dev_lab.dev.<door>`) refusing its own misuse | the door's message |
| preflight | git hooks at `pre-commit`, `commit-msg`, `pre-push` (`dev_lab.dev.githooks.runner`) | the failed hook's own output |
| stop hooks | `Stop`/`SubagentStop`: hand-back, pushed heads, scratch, walls | the block's reason |
| forge | `tests/<part>` statuses on the pushed sha ([forge.md](forge.md)) | the part's log |

A wall at an outer layer is cheaper: a deny row costs one refused call, a red part costs a push and a wait.
A gap found late is closed at the earliest layer that could have caught it.

## The wall ledger

- `dev_lab.dev.walls.refused` is the refusal choke point: one `metrics` refusal line and one ledger line.
  The deny engine reaches it as `python -m dev_lab.dev.walls refused`; the git hook runner calls it.
  A family hook or CLI refusing with a text (the journal door, the hand-back, pushed-head and scratch stops,
  the plan preflight) goes through `walls.refused_text`, which names the rule and computes the remedy.
- `walls post-tool` (`PostToolUse`, `PostToolUseFailure`) records a denial in a tool's error text that
  carries no family `details:` pointer -- a classifier's or a tool's own -- as a wall with no remedy.
- Where: `output/logs/<yy>/<mm>/<dd>/walls/walls.jsonl` under the main checkout. One line per wall:
  `ts`, `session`, `rule` (or `unknown`), `command_sha256` (a 16-hex prefix; never the command, which may hold
  a token), `remedy_present`. A closure line carries `closed_by` instead.
- `remedy_present` is `walls.has_remedy`: a line beyond the cause that is not only the `details:` pointer.

## Closing a gap

1. Hit a wall. It names a door: take it (`REFUSAL-NAMES-THE-REMEDY`). Done.
2. It names none, or names a door that does not work: that is the gap. Do not route around it -- no
   `--no-verify`, no `-c core.hooksPath=` (`COMMIT-HOOKS-RUN`), no other road to the same act -- and do not
   hand the user a command (`AGENT-RUNS-ITS-OWN-COMMANDS`).
3. Close it before the task: a deny row or a remedy (`dev_lab.dev._deny_*`, a section here in
   [refusals.md](refusals.md)), a door's message naming its cause and door, or a test pinning either. Commit it.
   If it cannot be closed now, record it where the repo keeps tasks (`.claude/rem.json` names the store).
4. Record the closure: `python -m dev_lab.dev.walls close --rule <rule> --by <sha|issue|path>`.
5. Otherwise the `Stop` hook (`walls stop`) refuses the turn once, naming the open walls and this loop.

## A subagent's hand-back

A subagent's final report carries a **Walls hit** section: each wall's rule, whether it named a door, and the
sha, issue or path that closed or recorded it -- or "none". The main session reads it to close what the
subagent could not ([fanout.md](fanout.md)).
