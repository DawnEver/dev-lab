# Auto mode runs the doors

In Claude Code and Codex auto mode, the family's checked doors run without a prompt or a classifier refusal
(`AUTO-MODE-RUNS-THE-DOORS`). Use the door instead of the raw verb: each re-checks its precondition at the
moment it acts. Local cleanup is a door; deleting a branch on origin stays a human's action, and a subagent never
pushes.

## The doors

| door | does |
|---|---|
| `python -m dev_lab.dev.branchset --apply` | Reclaims every reclaimable worktree FIRST (`dev_lab.dev.reclaim.reclaim`, next row), then deletes every merged LOCAL branch: never a declared branch, never one with commits origin lacks, never one still checked out in a worktree. Re-runs `merge-base --is-ancestor` right before each delete and pins it to that sha. Origin candidates are listed with `git push origin --delete <b>` for a human. |
| `python -m dev_lab.dev.worktrees [--prune]` | Lists every linked worktree and orphan directory with its verdict. `--prune` reclaims a linked tree only when ALL hold: not `git worktree lock`-ed; no change to a TRACKED file, staged or not (`git status --porcelain --untracked-files=no` empty; untracked and ignored files never block); its content landed on the trunk or a declared session (`git cherry` empty, or its origin ref gone after a squash merge); no process works in, executes from or reads it (LIVE-RUN `occupants`). Its outputs (`archive-outputs`) are moved home and verified first (`worktree_archive.home_outputs`); only on a verified archive, `git worktree remove --force`, then its branch via `branchset --apply` where a branch set is declared. An unverified archive keeps the tree, with the reason. An orphan directory goes the same way: outputs home, verified, then deleted. Every kept tree is listed with its reason. The session debris hook runs it. |
| `python -m dev_lab.dev.stoprun --pid PID [--repo PATH] [--dry-run]` | Stops one identified run and its subtree, children first, never an ancestor or a sibling. A run is identified by its command line: the built-in signatures (verify, a gate runner, pytest) plus regexes in `[tool.dev_lab.stoprun] signatures`. Any other pid is refused (exit 3). |

| `python -m dev_lab.dev.forge pr close-landed [N...]` | Closes an open PR whose head is already on its base, with an evidence comment. Never deletes its branch: the forge's prune of merged branches (`prune_merged`) is the one deleter. |
| `python -m dev_lab.dev.forge pr close-superseded N... --by <M\|sha\|ref> [--why <line>]` | Closes each open PR salvaged into open, unmerged PR `M` or into a commit, and comments `superseded by #M: <line>` (or `superseded by <sha12>: <line>`). Never deletes its branch. Refuses a closed target, a closed or merged `M`, a commit that does not resolve, or `M` itself. |
| `python -m dev_lab.dev.branchprune delete <branch>...` | LOSSLESS-DELETE: a remote branch only when every commit on it is on integration or another live branch or open PR head, or, by content, when it adds no line integration lacks outside a generated file. Refusals name the files carrying unlanded content. |
| `python -m dev_lab.dev.forge cancel-stuck <sha> [--factor N] [--bound-minutes M]` | Scancels only `run-<sha12>-<part>` tasks of the full 40-hex `<sha>` that run at 90 % CPU or more with no new test line in their stream for longer than N (default 3) x the longest MEASURED duration of the shard's tests (the forge's learned `durations`); a shard with an unmeasured test is floored at M (default 60), and the line says so. Every other task of the sha is listed as healthy; other jobs are never touched. |
| `python -m dev_lab.dev.forge watch <sha> [--deadline-minutes M]` | Read-only: prints each `tests/<part>` status change until all are final (exit 0 green, 1 red) or the deadline (exit 3). |
| `python -m dev_lab.dev.hpchost deploy-fleet [--account U]... [--dry-run]` | For each `[[hpc.grant]]` account, reads that account's own `[deploy]` host and root through any of its login hosts, then starts, detached over `ssh -o BatchMode=yes`, its own `hpchost deploy` on THAT host, one log per account under `~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-fleet/`. An account outside the grants refuses the whole run; one with no `[deploy]` host, or a host outside its grant, is refused by name while the rest deploy. |

The raw verbs (`git branch -D`, `git worktree remove --force`, `rm -rf`, `taskkill`, a raw `scancel`) stay unallowed.
A bounded verb's row names the verb (`VERB_DOORS`), so the module's other verbs stay prompted.

## One table, two clients

`dev_lab.dev.autodoors` holds `DOOR_MODULES`; `script_doors(root)` adds the repo's tracked `scripts/**.py`
with a `__main__` guard and the shell doors it names (`shell_doors=`, `--shell-door`). Both clients are
rendered from these:

- **Claude Code**: one NARROW `Bash(...)` row per door, e.g. `Bash(.venv/*/python* -m dev_lab.dev.worktrees *)`.
  Auto mode suspends broad rows but keeps a narrow one live. A launcher in another checkout is admitted only
  repo-relative, `.claude/worktrees/*/.venv/...`; run the door from the repository root.
- **Codex**: one `prefix_rule(pattern = [...], decision = "allow")` per door in `.codex/rules/family-doors.rules`;
  `codex execpolicy check --rules <file> <cmd>` probes it.

No rendering may promise a raw verb (`promises_raw`).

## Auto-mode prose: `<repo>/.claude/automode.json` (machine-local, never committed)

Claude Code reads `autoMode` only from user, managed or `--settings` files, so the user's launcher passes a trusted
repo's `<repo>/.claude/automode.json` through `--settings`. The file is LOCAL AND DERIVED: the family `.gitignore`
ignores it in every consumer, and it is never committed, because fleet facts (account names, login hosts,
workstation names, internal addresses) are shared only through their two sources and a committed copy would put
them in git history (user ruling 2026-10-23). `dev_lab.dev.automode` renders
`{"autoMode": {"environment": ["$defaults", ...], "allow": ["$defaults", ...]}}` from:

1. **The repo's declaration** (committed, host-free): `INTENTS`, one prose category per kit door or rule
   (Break-Glass, close-landed, close-superseded, lossless prune, hook install, fleet deploy, cancel-stuck,
   read-only monitoring), each `OPTIONAL_INTENTS` entry named in `[tool.dev_lab.automode] declares`
   (e.g. `"jmag-material-card"`), and the repo's `origin` and branch set.
2. **The machine's fleet sources**: the synced workstation registry `hosts.json` (its path in the machine file's
   `[workstation] registry`), each workstation with its computer, address and roles; and the machine file's
   `[[hpc.grant]]` accounts with their login hosts.

It is rendered by the dependency door's bootstrap and sync, and by
`python -m dev_lab.dev.automode {write [--repo R] | session-start}`; the kit renders no `SessionStart` hook of
its own for automode (its one `SessionStart` row is the background reclaim, `dev_lab.dev.reclaimrun`), so a repo that wants a refresh per session wires `session-start` there (it reads the payload's `cwd`).
When either source is unreadable (a cluster login node holds no registry) nothing is written and the reason is
printed by name; it always exits 0.

Entries are intent, never a command or module spelling (`spelled_commands`); the exact commands are the narrow
rows above. `leaks` scans every committed kit text for a host shape and for each fleet fact this machine holds.

## Adopting

1. Construct `AllowAdoption(..., scripts=script_doors(root, shell_doors=(...)))`, re-render
   `.claude/settings.json` with `permissions_block`, and drop any declared row that now duplicates a door row.
2. Run `python -m dev_lab.dev.autodoors --repo . [--shell-door <path>] --write` and commit
   `.codex/rules/family-doors.rules`; without `--write` it exits 1 when the file is stale.
3. Delete local copies of the doors.
