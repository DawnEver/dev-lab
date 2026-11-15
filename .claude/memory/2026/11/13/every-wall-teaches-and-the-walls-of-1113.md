---
name: every-wall-teaches-and-the-walls-of-1113
description: The every-wall-teaches ruling and the 11-13 walls it closed -- the wall ledger, the exits, the push-door and milestone fixes.
created: 2026-11-13
accessed: 2026-11-13
---
# Every wall teaches: the 11-13 walls wave

User ruling 2026-11-13: every refusal or failure an agent hits names its cause and its door; a wall without
feedback is a MECHANISM GAP, closed (hook row, remedy, test) before the task continues. Never route around it,
never hand the user a command.

## Mechanisms (all on integrate/main)
- #516: principle `every-wall-teaches`; `walls.refused` is the one refusal path and writes the session wall
  ledger (`output/logs/<yy>/<mm>/<dd>/walls/walls.jsonl`, command as sha256 prefix only); a Stop row blocks once
  on an unremedied, unclosed wall (`walls close --rule R --by <sha|issue|path>`); `COMMIT-HOOKS-RUN` refuses
  `--no-verify` / `core.hooksPath`; `docs-src/dev/feedback.md` is the one page; hand-backs list "Walls hit".
- #517: exits for the walls hit that day -- `branchprune delete-tag --approved` (tag contained in a declared
  branch only); stoprun explains a refused pid; the merging door ends the PR in the session record; preflight names
  the missing ssh hold; `forge status show <branch> --against` marks reds inherited/NEW; a venv-less worktree is
  bootstrapped or told how; verify's summary carries each failed step's remedy; push rows fire only on a real push.
- #514: an ssh whose remote command hides behind `$VAR`/`$(...)`/backticks is refused, and any remote
  `dev_lab.ops` call is sent to the consent doors (planrun preflight -> sshhold open -> planrun run).
- #515: the `ops.config` subject is derived HERE (`planrun subject --config <host>`, steps key `config_host`), so a
  plan needs no host session to build; each plan host opens on its declared `[ssh] jump` route.
- #511: a milestone tag ends in `.dev0` -- hatch-vcs refuses to build from `.devN`, N != 0.
- #518: the always-loaded rules ceiling 70 -> 73 for the new principle (user ruling).

## The incident lessons
- A command hidden behind a shell variable evaded the deny row; the hook saw only `"$C"`.
- A permission-classifier denial carries no remedy, so it read as a dead end; the door existed.
- One `--jump` for a whole plan routed every host through the bastion, which refused the direct host.
> Amended 2026-11-13: added the name/description frontmatter the memory shape requires -- approved: "同意补全"
