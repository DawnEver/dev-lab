# Auto mode runs the doors

In Claude Code and Codex auto mode, the family's checked doors run without a prompt or a classifier refusal
(`AUTO-MODE-RUNS-THE-DOORS`). Use the door instead of the raw verb: each re-checks its precondition at the
moment it acts. The forge PR lifecycle is a door the agent runs itself, never hands to the user
(`FORGE-DOORS-ARE-CONSENT`). Local cleanup is a door; deleting a branch on origin stays a human's action, and a subagent never
pushes.

## The doors

| door | does |
|---|---|
| `python -m dev_lab.dev.branchset --apply` | Reclaims every reclaimable worktree FIRST (`dev_lab.dev.reclaim.reclaim`, next row), then deletes every merged LOCAL branch: never a declared branch, never one with commits origin lacks, never one still checked out in a worktree. Re-runs `merge-base --is-ancestor` right before each delete and pins it to that sha. Origin candidates are listed with `git push origin --delete <b>` for a human. |
| `python -m dev_lab.dev.worktrees [--prune]` | Lists every linked worktree and orphan directory with its verdict. `--prune` reclaims a linked tree only when ALL hold: not `git worktree lock`-ed; no change to a TRACKED file, staged or not (`git status --porcelain --untracked-files=no` empty; untracked and ignored files never block); its content landed on the trunk or a declared session (`git cherry` empty, or its origin ref gone after a squash merge); no process works in, executes from or reads it (LIVE-RUN `occupants`). Its outputs (`archive-outputs`) are moved home and verified first (`worktree_archive.home_outputs`, user ruling 2026-11-12), chained: an unverified move keeps the tree, with the reason; else it is deleted, then its branch via `branchset --apply` where a branch set is declared. A summary line counts every kept tree by reason. An orphan directory is judged the same way. Every kept tree is listed with its reason. The session debris hook runs it. |
| `python -m dev_lab.dev.stoprun --pid PID [--repo PATH] [--dry-run]` | Stops one identified run and its subtree, children first, never an ancestor or a sibling. A run is identified by its command line: the built-in signatures (verify, a gate runner, pytest) plus regexes in `[tool.dev_lab.stoprun] signatures`. Any other pid is refused (exit 3). |

| `python -m dev_lab.dev.forge pr create --head H --base B --title T [--ready]` | Opens a draft PR (DRAFT-UNTIL-READY); advises, on stderr and in the body, a stacked head or a second PR of one session. |
| `python -m dev_lab.dev.forge pr ready N` / `pr draft N` | Marks PR `N` ready for review, or back to draft; one stdout line names the outcome, exit 1 on refusal. |
| `python -m dev_lab.dev.forge pr close-landed [N...]` | Closes an open PR whose head is already on its base, with an evidence comment. Never deletes its branch: the forge's prune of merged branches (`prune_merged`) is the one deleter. |
| `python -m dev_lab.dev.forge pr close-superseded N... --by <M\|sha\|ref> [--why <line>]` | Closes each open PR salvaged into open, unmerged PR `M` or into a commit, and comments `superseded by #M: <line>` (or `superseded by <sha12>: <line>`). Never deletes its branch. Refuses a closed target, a closed or merged `M`, a commit that does not resolve, or `M` itself. |
| `python -m dev_lab.dev.branchprune delete <branch>...` | LOSSLESS-DELETE: a remote branch only when every commit on it is on integration or another live branch or open PR head, or, by content, when every file its own commits wrote, generated ones aside, is identical (mode and blob) on integration; it fails closed. Refusals name the files carrying unlanded content. |
| `python -m dev_lab.dev.forge cancel-stuck <sha> [--factor N] [--bound-minutes M]` | Scancels only `run-<sha12>-<part>` tasks of the full 40-hex `<sha>` that run at 90 % CPU or more with no new test line in their stream for longer than N (default 3) x the longest MEASURED duration of the shard's tests (the forge's learned `durations`); a shard with an unmeasured test is floored at M (default 60), and the line says so. Every other task of the sha is listed as healthy; other jobs are never touched. |
| `python -m dev_lab.dev.forge watch <sha>... [--deadline-minutes M]` | Read-only: prints each `tests/<part>` status change until the first listed sha is final (exit 0 green, 1 red) or the deadline (exit 3). |
| `python -m dev_lab.dev.hpcaccount deploy-fleet [--account U]... [--dry-run]` | For each `[[hpc.grant]]` account, reads that account's own `[deploy]` host and root through any of its login hosts, then starts, detached over `ssh -o BatchMode=yes`, its own `hpcaccount deploy` on THAT host, one log per account under `~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-fleet/`. An account outside the grants refuses the whole run; one with no `[deploy]` host, or a host outside its grant, is refused by name while the rest deploy. |
| `python -m dev_lab.dev.hpcaccount forget --repo URL --row KEY (--fleet \| --account U...) [--dry-run]` | Runs lab-commons' `learned forget` of one row on each named `[[hpc.grant]]` account (or all), through the grant's own login hosts, in its declared checkout; prints forgotten (with the backup) / absent / refused per account, and the rest still run. `--dry-run` only reads each row. An account outside the grants refuses the whole run. |
| `python -m dev_lab.dev.hpcaccount credential U@HOST --login L --host-config FILE [--url REPO] < token`; `... credential U@HOST --drop-host H` | Places one minted forge token of a declared login (`[hpc.roles.*] reader`, or `[ops.forge.accounts]` of FILE, the forge host's reviewed config read by the loader `config apply` uses; the account's role reader when it names one) on a `[[hpc.grant]]` account, through the grant's own key-only connection; the token on stdin, never argv. The forge is FILE's (`[ops.caddy] sites`): `--url` must be on it, default the login's first declared repo; any other host is refused before connecting. The line is staged alone, the forge's `auth role` must answer as `L` with git reading only the staged file, and only then is `~/.git-credentials` rewritten -- backup `~/.git-credentials.bak-<ts>` (0600) first, only that forge's line replaced, umask 077, atomic `mv`; a refusal discards the stage and leaves the store untouched. `--drop-host H` removes exactly H's line, same backup. Output names the token only by a sha256 prefix. |

The raw verbs (`git branch -D`, `git worktree remove --force`, `rm -rf`, `taskkill`, a raw `scancel`) stay unallowed.
A bounded verb's row names the verb, so the module's other verbs stay prompted.

## One table: `dev_lab.dev.agentpolicy.POLICY`

Every door is ONE row (user ruling 2026-11-07): its argv prefix, its actor, ONE string that is both the allow
row's provenance and the classifier's intent, and the deny row it is the exit from. Actors:

- `subagent`: any agent (the verdict, stoprun, netverb, the censuses, the forge's read side, issue writes).
- `main`: the main session alone -- a PR's lifecycle, `forge sync`, `integrate promote`, `forge pr breakglass`
  (inside a wave the user opened), `forge review takeover|again`, `forge security release`, `cancel-stuck`,
  `git merge --ff-only`, `branchprune delete`. `SUBAGENT-NO-PUSH`'s pattern is derived from these rows.
- `user`: no agent -- opening a Break-Glass wave. It renders no allow row and no intent.

A deny row's remedy that lists doors is derived from the rows linked to it (`exits_of`):
`FORGE-WRITE-VIA-CLI` names every `forge issue|pr` write door the table holds. A repo-specific row lives in
that repo's `[tool.dev_lab.policy]`, never in a hand-written module.

## Two clients

`dev_lab.dev.autodoors` renders `POLICY`; `script_doors(root)` adds the repo's tracked `scripts/**.py`
with a `__main__` guard and the shell doors it names (`shell_doors=`, `--shell-door`). Both clients are
rendered from these:

- **Claude Code**: one NARROW `Bash(...)` row per door and interpreter layout, e.g.
  `Bash(.venv/Scripts/python.exe -m dev_lab.dev.worktrees *)` and its `.venv/bin/python` twin. Never the
  `.venv/*/python*` glob: its trailing `*` admits `python.exe -c <code>` ahead of the door, and the blanket
  `Bash(.venv/*/python* *)` row is gone. A door run through another checkout's interpreter is prompted once;
  run it from the repository root.
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

1. **The repo's declaration** (committed, host-free): `INTENTS`, every agent door's one string of
   `POLICY`, the repo's own standing intents as prose in `[tool.dev_lab.policy] intents` (the retired
   `[tool.dev_lab.automode] declares` is refused by name), and the repo's `origin` and branch set.
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
