# Auto mode runs the doors

In Claude Code and Codex auto mode, the family's checked doors run without a prompt or a classifier refusal
(`AUTO-MODE-RUNS-THE-DOORS`). Use the door instead of the raw verb: each re-checks its precondition at the
moment it acts. Local cleanup is a door; deleting a branch on origin stays a human's action, and a subagent never
pushes.

## The doors

| door | does |
|---|---|
| `python -m dev_lab.dev.branchset --apply` | Deletes every merged LOCAL branch: never a declared branch, never one with commits origin lacks, never one checked out in any worktree. Re-runs `merge-base --is-ancestor` right before each delete and pins it to that sha. Origin candidates are listed with `git push origin --delete <b>` for a human. |
| `python -m dev_lab.dev.worktrees [--prune]` | Lists the worktrees. `--prune` removes one only when it is clean (`git status --porcelain` empty), holds no ignored content but regenerable artefacts (caches, `.venv`, `*.egg-info`, `build/`, `target/`, plus `[tool.lab_commons.worktrees] regenerable`), and its HEAD is on a remote branch. Removal is `git worktree remove` without `--force`; an unregistered empty directory is removed with `rmdir`. Anything else is listed with what blocks it. |
| `python -m dev_lab.dev.stoprun --pid PID [--repo PATH] [--dry-run]` | Stops one identified run and its subtree, children first, never an ancestor or a sibling. A run is identified by its command line: the built-in signatures (verify, a gate runner, pytest) plus regexes in `[tool.lab_commons.stoprun] signatures`. Any other pid is refused (exit 3). |

| `python -m dev_lab.dev.forge pr close-landed [N...]` | Closes an open PR whose head is already on its base, then deletes its branch losslessly. |
| `python -m dev_lab.dev.forge pr close-superseded N... --by M [--why <line>]` | Closes each open PR salvaged into open, unmerged PR `M`, comments `superseded by #M: <line>`, then deletes its branch through `branchprune delete` (kept, naming the commits, if any exists nowhere else). Refuses a closed target, a closed or merged `M`, or `M` itself. |
| `python -m dev_lab.dev.branchprune delete <branch>...` | LOSSLESS-DELETE: a remote branch only when every commit on it is on integration or another live branch or open PR head. |
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

## Auto-mode prose: `<repo>/.claude/automode.json`

Claude Code reads `autoMode` only from user, managed or `--settings` files, so the user's launcher passes a trusted
repo's `<repo>/.claude/automode.json` through `--settings`. `dev_lab.dev.automode` renders it:
`{"autoMode": {"environment": ["$defaults", ...], "allow": ["$defaults", ...]}}`.

- `environment`: the repo's `origin` and declared branch set, and the trusted hosts BY NAME so the classifier
  recognises them: each workstation of the synced workstation registry (`hosts.json`, named by the machine file's
  `[workstation] registry`) with its computer, address and roles, and each `[[hpc.grant]]` account with its login
  hosts. The committed file is therefore a derived artefact of machine-local sources: the check re-renders it, and
  where a source is unreadable (a cluster login node has no registry) it exits 3, INCONCLUSIVE, naming the source,
  and `--write` writes nothing.
- `allow`: `INTENTS`, one prose category per door or rule (Break-Glass, close-landed, close-superseded,
  lossless prune, hook install, fleet deploy, cancel-stuck, read-only monitoring), plus each `OPTIONAL_INTENTS`
  entry the repo names in `[tool.lab_commons.automode] declares` (e.g. `"jmag-material-card"`).

Entries are intent, never a command or module spelling (`spelled_commands`); the exact commands are the narrow
rows above.

## Adopting

1. Construct `AllowAdoption(..., scripts=script_doors(root, shell_doors=(...)))`, re-render
   `.claude/settings.json` with `permissions_block`, and drop any declared row that now duplicates a door row.
2. Run `python -m dev_lab.dev.autodoors --repo . [--shell-door <path>] --write` and commit
   `.codex/rules/family-doors.rules` and `<repo>/.claude/automode.json`; without `--write` it exits 1 when either is stale.
3. Delete local copies of the doors.
