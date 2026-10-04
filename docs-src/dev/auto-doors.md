# Auto mode runs the doors

Rule `AUTO-MODE-RUNS-THE-DOORS` (statement in `lab_commons.dev.rules`). In Claude Code and Codex auto mode, the family's checked doors run without a prompt or a classifier refusal. Destructive LOCAL cleanup goes through a door. Pushes and remote deletions are never automatic.

## Why

User directive, 2026-10-04: in both clients' auto mode, the sanctioned script doors must run without being blocked. On the same day, every refusal that cost a session time came from Claude Code's auto-mode classifier, and none came from a deny hook. The refused commands were a `taskkill` of the agent's own gate run, `git push origin --delete` of an ancestry-checked branch, and `rm -rf` of untracked worktree leftovers.

User ruling, same day: agents may not push or delete remote branches at will, but they must be able to clean local branches and worktrees. So:

- **Remote is human.** A push goes through the gated push hook. A remote branch deletion is run by a human, and the door prints the command for it.
- **Local is a door.** The raw verbs (`git branch -D`, `git worktree remove --force`, `rm -rf`, `taskkill`) stay unallowed. Each one is replaced by a door that re-checks its precondition at the moment it acts.

## The doors

| door | does |
|---|---|
| `python -m lab_commons.dev.branchset --apply` | Deletes every merged LOCAL branch: never a declared branch, never a branch with commits origin lacks, never a branch checked out in ANY worktree, so a tree must be committed or cleared and removed first. It re-runs `merge-base --is-ancestor` right before each delete and pins the delete to that sha (`update-ref -d <ref> <sha>`). Origin candidates are LISTED with `git push origin --delete <b>` for a human to run. |
| `python -m lab_commons.dev.worktrees [--prune]` | Lists the worktrees. `--prune` removes a worktree only when it is CLEAN (user ruling 2026-10-04: `git status --porcelain` empty, so nothing modified, staged or untracked), holds no ignored content beyond caches (an ignored `output/` blocks it), and has its HEAD on a remote branch. Removal is `git worktree remove` WITHOUT `--force`. A tree that is not clean is listed with the paths that block it; the door never moves work aside. The ONE automatic move: an EMPTY directory under `.claude/worktrees/` that git does not register goes to `output/logs/<yy>/<mm>/<dd>/worktree-archive/`. One that holds files is listed and refused. |
| `python -m lab_commons.dev.stoprun --pid PID [--dry-run]` | Stops one gate/verify/pytest run, identified by its command line, and its subtree, children first. Any other pid is refused (exit 3). The process table comes from `Get-CimInstance` or `ps`, so the door needs no new dependency. |

The worktree door encodes the consumer-a incident of 2026-10-04. A cleanup loop chained `git worktree remove --force` after an archive step with `;`. The archive step failed, and the removal deleted five worktrees' `output/` folders anyway. Here, every destructive step runs only after its precondition has been verified.

## One table, two clients

`lab_commons.dev.autodoors` holds `DOOR_MODULES`. Each repo also has `script_doors(root)`: the tracked `scripts/**.py` files that carry a `__main__` guard, plus the shell doors the repo names (`shell_doors=`, `--shell-door`, e.g. its netverb wrapper). Both clients are rendered from these:

- **Claude Code.** There is one NARROW `Bash(...)` row per door, for example `Bash(.venv/*/python* -m lab_commons.dev.worktrees *)`. In auto mode, Claude Code suspends broad rows (`Bash(*)` and wildcarded interpreters such as `Bash(.venv/*/python* *)`), but a narrow row stays live and skips the classifier. `allow_adoption.allow_entries` appends these rows to every adopting repo's block, and `settings_problems` (the allowguard famtest) refuses a block that lacks them.
- **Codex** (checked against codex-cli 0.160.0). There is one execpolicy `prefix_rule(pattern = [...], decision = "allow")` per door, in `.codex/rules/family-doors.rules`. Codex reads that file for a trusted project. `codex execpolicy check --rules <file> <cmd>` is the probe, and the suite drives it when `codex` is on PATH.

No rendering may promise a raw verb. `promises_raw` checks for this, and the suite asserts it on both renderings.

## Adopting

1. Construct `AllowAdoption(..., scripts=script_doors(root, shell_doors=(...)))`, re-render `.claude/settings.json` with `permissions_block`, and re-measure the allow floor and headroom. Drop any declared row that now duplicates a door row; construction refuses the duplicate.
2. Run `python -m lab_commons.dev.autodoors --repo . [--shell-door <path>] --write` and commit `.codex/rules/family-doors.rules`. Without `--write`, the command exits 1 when that file is stale.
3. Retire local copies of the doors, for example a repo-local `stop_sweep.py --pid`, in favour of the family door.
