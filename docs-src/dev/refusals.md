# Refusals

When a deny hook refuses a command, it prints three lines: what was refused and why, the command to run instead,
and a `details:` pointer to a section of this page. Run the command it names. Each section below holds the full
reasoning for one universal row (`INJECTED-TEXT-IS-PROGRESSIVE`); a repo-local row is on that repo's own page.

A row marked HINT never refuses: the command runs and the same text reaches the agent as context. A row hints when
its hazard is speed or style rather than irreversible harm (toolchain plan P3, `dev_lab.dev.hooks.SEVERITIES`).

## The shape of a refusal

The budget is declared data in `dev_lab.dev.disclosure.BUDGETS`:

- `<ID>: <what was refused and why, as one clause>`
- the exact command to run instead (the door);
- `details: docs-src/dev/refusals.md#<id> (lab-commons)`, which points at the section below.

When a command targets another repo, the engine adds one header line naming that repo. `dev_lab.dev.famtests.injectedtext` runs the budget in a consumer's suite. `{remedy}` in an exit is the consuming repo's own door. `{python}` in an exit (and `<venv python>` in a door) is printed as the target checkout's own venv interpreter by ABSOLUTE path -- a linked worktree without one gets its main checkout's -- so the line runs from any cwd (2026-10-26: a relative `.venv` interpreter failed from another directory and the agent handed the command to the user). An exit is for the agent to run itself.

## BARE-TEST-INVOCATION

- **Why it is refused.** a hand-written test line has no VERDICT. An exit code cannot say whether the run COVERED what it selected, so a dead worker, a truncated run or a collection error that reported nothing all read as green -- and the reader has merged "the tests passed" with "nobody knows".
- **The exit.** Re-issue through the entry point that produces a verdict: {remedy}

## FORGE-WRITE-VIA-CLI

- **Why it is refused.** a forge write through any client but the family door carries no PROVENANCE. The forge records only the token`s login, and every agent on a box shares one token, so an issue, comment, close or PR written this way cannot say which machine or which agent wrote it. The family door opens every body it writes with `[<machine> · <agent> · <branch>]`, read from HARNESS_MACHINE / HARNESS_AGENT.
- **The exit.** Write through the family door: {python} -m dev_lab.dev.forge issue create|comment|close, pr create|close (reads: issue list|view, pr view; token: auth login|status). A write the door has no verb for -- merge, edit, review -- is the integrator`s to make: report it rather than reaching for another client.

## FORGE-WRITE-VIA-GH-API

- **Why it is refused.** a forge write through any client but the family door carries no PROVENANCE. The forge records only the token`s login, and every agent on a box shares one token, so an issue, comment, close or PR written this way cannot say which machine or which agent wrote it. The family door opens every body it writes with `[<machine> · <agent> · <branch>]`, read from HARNESS_MACHINE / HARNESS_AGENT.
- **The exit.** Write through the family door: {python} -m dev_lab.dev.forge issue create|comment|close, pr create|close (reads: issue list|view, pr view; token: auth login|status). A write the door has no verb for -- merge, edit, review -- is the integrator`s to make: report it rather than reaching for another client.

## FORGE-WRITE-VIA-HTTP

- **Why it is refused.** a forge write through any client but the family door carries no PROVENANCE. The forge records only the token`s login, and every agent on a box shares one token, so an issue, comment, close or PR written this way cannot say which machine or which agent wrote it. The family door opens every body it writes with `[<machine> · <agent> · <branch>]`, read from HARNESS_MACHINE / HARNESS_AGENT.
- **The exit.** Write through the family door: {python} -m dev_lab.dev.forge issue create|comment|close, pr create|close (reads: issue list|view, pr view; token: auth login|status). A write the door has no verb for -- merge, edit, review -- is the integrator`s to make: report it rather than reaching for another client.

## GIT-COMMIT-AMEND

- **Why it is refused.** `--amend` does not act on YOUR last commit, it acts on HEAD -- and on a shared lane HEAD belongs to whoever committed most recently. This family has NO single-agent mode, so "I just committed" is not a safety argument; it is the exact condition under which this fires. MEASURED 2026-09-18 on `feat/consumer-c`: agent A committed, agent B committed 40 seconds later, and A amended to fix two digits in its OWN message -- rewriting B's commit and replacing B's message with A's. It was caught inside a minute through `git reflog` and the tree recovered byte-identical, so only the SHA moved; nothing about the recovery made that outcome likelier than losing the work.
- **The exit.** Do not rewrite -- land the correction FORWARD. Read what HEAD actually is first: git log -1 --format="%h %an %s". If the CONTENT is wrong, commit the fix on top. If only the message is wrong and nothing a reader acts on changes, record the correction where the work is reported and leave the commit alone; that is the right call once anything sits on top of it.

## NETWORK-VERB

HINT: a bare network verb loses only the retry; force, delete and no-verify pushes are refusals of their own.

- **Why it is said.** the forge is a REMOTE service that nobody in this family restarts, and a single transient auth/DNS/connection failure on any of these verbs reads as "blocked" -- which is the report the retry wrapper exists to prevent. Measured 2026-08-21 on a `git fetch`: it failed auth once and succeeded on the retry, and was reported blocked in between. Widened 2026-10-19 to every verb `dev_lab.dev.netverb.is_network_verb` names -- git's `-C`/`-c` spellings, `submodule update`, and uv's resolving verbs -- after a `uv sync` of a git dependency failed once on forge auth and a re-run passed.
- **The exit.** Re-issue through the retry wrapper, which retries 3x and then REPORTS with a diagnosis: {remedy}

## TREE-HAS-A-LIVE-RUN

- **Why it is refused.** a run executes its checkout's code and `.venv` for its whole life, so an edit, a merge, a checkout or an environment sync under it makes its result describe a tree that never existed. Measured 2026-10-19 in consumer-a: during a JMAG `deck run`, an agent edited a test, merged into the checkout and re-synced the venv the run executed from. The run is found WITHOUT its cooperation (`dev_lab.dev.liverun`, read off `lab_commons.census`): a process READS the tree when it is a Python interpreter working in it or an argument names a path in it, and the row binds only while one exists. `output/`, `.claude/` and `.venv/` are not the tree; a process executing from the venv locks the venv (`dep`), not the tree.
- **The exit.** Work in another worktree (git worktree add --detach .claude/worktrees/<name> <sha>), wait for the run, or stop it yourself: {python} -m dev_lab.dev.stoprun --pid <pid>.

## STRAY-FILE-REFUSED

- **Why it is refused.** A file somebody meant is staged; a program's artefact belongs in `output/`; a one-off script belongs in `scratch/`. An untracked, non-ignored file anywhere else is a file nobody claimed -- the 2026-10-20 vendor logs in the checkout root and the stray `uv.lock` (`dev_lab.dev.codeplace.stray_files`). It reports after each shell call and at Stop.
- **The exit.** One per file, by its kind: a file under a code root was meant -- `git add` it; a script is a one-off -- move it to `scratch/<yy>/<mm>/<dd>/<kind>/`; anything else is a program's data -- move it to `output/logs/<yy>/<mm>/<dd>/<kind>/` and make the program write there (a vendor tool writes into its cwd: give it a cwd under `output/`).

## WRITES-STAY-IN-THE-TREE

- **Why it is refused.** User requirement 2026-11-05: an agent session left scripts in the OS temp dir (Git Bash `/tmp` is the same directory). Outside a checkout nothing scans, ignores or cleans a file, so it outlives the session and nobody owns it. The write-prone roots are one declared set (`dev_lab.dev.writeroots.write_prone_roots`, extended by the machine file's `[writeroots]` `temp`/`census`/`excluded`): the OS temp dir, POSIX `/tmp` and `/var/tmp`, each fixed drive's and the home's `tmp`, `temp`, `var`, `src`, and a loose non-dot entry in the home. Refused: a Write/Edit/NotebookEdit there (the `codeplace` write hook), and a shell redirect, `tee`, `cp`/`mv`/`Copy-Item`/`Move-Item` target, `mkdir`, `touch`, `New-Item`, `Out-File`, `Set-Content` or `Add-Content` into one. Reading and deleting stay allowed. A write beneath a write-prone root is refused EVEN INSIDE A CHECKOUT there, in both halves: user ruling 2026-11-06 -- a checkout under such a root (the home `src` above all) is an abandoned old version, never a place to work. Never refused: the harness's own `<temp>/claude/` subtree, `lab-commons-notices`, and a cache named by `UV_CACHE_DIR`/`PIP_CACHE_DIR`/`RUFF_CACHE_DIR`. The Stop hook the stray census rides (`python -m dev_lab.dev.codeplace stray`) also names the scripts and notes a session left in a root; `python -m dev_lab.dev.tmpsweep [--apply] [--max-age-days N]` is the census and the sweep, which removes only temp-root entries older than the age in every file they hold, never a link, a checkout or a held file.
- **The exit.** A program's artefact goes to `output/logs/<yy>/<mm>/<dd>/<kind>/` and an experiment to `scratch/` of the checkout you work in.

## AGENT-RUNS-ITS-OWN-COMMANDS

- **Why it is refused.** A turn that ends by handing the user a command to run moves the agent's work onto the user, and the command usually fails from the user's cwd. The Stop hook reads the final message (`dev_lab.dev.handback`).
- **The exit.** Run the command through the shell tool with absolute paths and report the result. A guard's refusal names the door an agent uses; a permission-classifier refusal is a decision for the user, so ask for the decision, not for the command to be run. Only an interactive login, passphrase or GUI step may go to the user as `! <cmd>`, and only these (`handback.INTERACTIVE_ONLY`): `gh auth login`, `gh auth refresh`, `gcloud auth login`, `gcloud auth application-default login`, `az login`, `aws sso login`, `npm login`, `docker login`, `ssh-add`, `ssh-keygen`, `gpg --full-generate-key`, `claude login`, `codex login`, `/login`.

## GIT-STASH

- **Why it is refused.** `refs/stash` is REPO-WIDE. It is one ref per repository, not per worktree, so a stash taken in one checkout is popped by whoever pops next -- in a family whose premise is a shared, possibly concurrent checkout, that is another agent losing work it never knew existed.
- **The exit.** Keep the work where its owner can see it. Either commit it on your own lane branch (a scratch commit is cheap and is named), or take a throwaway checkout: git worktree add --detach .claude/worktrees/<name> <sha>

## GIT-RESET

- **Why it is refused.** every form of `git reset` moves HEAD, the index or the working tree of a checkout, and in a shared checkout another agent may be committing there at that moment: `--hard` discards their edits, `--soft`/`--mixed` silently re-stage or un-stage what they meant to commit. SHARED-CHECKOUT said "never `git reset`" in prose and nothing refused it.
- **The exit.** Name the narrower act: unstage one path with `git restore --staged <path>`; undo a commit FORWARD with `git revert <sha>`; to start over, take a throwaway checkout: git worktree add --detach .claude/worktrees/<name> <sha>

## GIT-STAGE-EVERYTHING

- **Why it is refused.** `git commit -a`, `git add -A`/`--all`, `-u`/`--update`, `.` and a directory stage whatever is modified, including what another agent in the same checkout left unstaged -- an unstaged edit is not storage, and a wide stage turns it into somebody else's commit. The pattern reads only up to the first quote, so a message that mentions a flag is not one.
- **The exit.** Stage the paths you mean and check what is staged: `git add <path> <path>`, then `git diff --cached --stat`.

## PUSH-FORCE

- **Why it is refused.** every branch here is read by someone else, and rewriting a ref silently invalidates any verdict already taken against the old tree -- the verdict still cites a `tree=` address, and the tree it names no longer exists. `--force-with-lease` is refused with the rest: it protects against a ref that MOVED, not against a reader who already judged the ref as it was.
- **The exit.** Do not rewrite a shared ref: land the change FORWARD as a new commit on your own lane, then push without the force flag. If the history really must change, it changes on a branch nobody has judged yet.

## PUSH-REMOTE-DELETE

- **Why it is refused.** a main session may push without asking (MAIN-SESSION-PUBLISHES), and the allow row that opens the push is a glob -- it admits `--delete`, `-d`, `--prune`, `--mirror` and a `:<ref>` refspec exactly as readily as a plain push. Deleting a ref on origin is the one push nothing on the agent's side can undo: the local branch may already be gone, and another reader's verdict may cite the deleted tip. A raw delete checks nothing first; the 2026-10-21 ruling opened deletion only where it is PROVABLY lossless.
- **The exit.** LOSSLESS-DELETE: `{python} -m dev_lab.dev.branchprune delete <branch>...` fetches, deletes only when every commit on the branch is on integration or on another live origin branch / open PR head (naming that container) or, failing that, when every file the branch's own commits wrote is identical (mode and blob) on integration (a generated file, `famfiles.GENERATED`, never counts -- so a branch of sync merges deletes), and otherwise refuses naming the commits and the files carrying unlanded content. Local cleanup stays a door: `python -m dev_lab.dev.branchset --apply` deletes merged LOCAL branches only and lists origin's.

## PUSH-NO-VERIFY

- **Why it is refused.** `--no-verify` skips the pre-push hooks -- admission and the trunk proof -- so the push publishes what no hook checked, while looking exactly like one that did not. No pre-push hook runs a test (VERDICTS-FROM-THE-FORGE), so the flag saves nothing.
- **The exit.** Push without the flag; the forge produces the part after the push. To check a change first, measure what you touched: {remedy}

## RAW-PROCESS-KILL

- **Why it is refused.** a raw kill stops what you NAMED, and a test worker names nothing on its own command line -- so the subtree that actually holds the box survives its parent. Measured twice in this family (2026-07-29, 2026-09-13): stopping a wrapper orphaned its children, and the orphan went on holding the CPU lock for a run whose own process was already dead.
- **The exit.** Kill the process TREE by its ROOT pid, children-first, and verify none remain: {remedy}

## WORKTREE-BASE-IS-EXPLICIT

- **Why it is refused.** `git worktree add <path>` with no commit-ish silently takes the CURRENT HEAD, which on a shared checkout is routinely not the tree you meant. MEASURED 2026-09-01: two agents were handed trees based on the wrong branch and each reasoned about a codebase nobody runs -- one of them for 130k tokens -- before noticing. A bare `HEAD` is accepted because it is a choice rather than an omission, but it is the weakest one available: HEAD moves, so two trees cut from it minutes apart can differ. Prefer the sha.
- **The exit.** Name the commit the tree starts from: git worktree add --detach .claude/worktrees/<name> <sha>

## WORKTREES-STAY-INSIDE

- **Why it is refused.** a checkout created OUTSIDE its repository is outside every scan, ignore rule and search that repository runs over itself, and outside the place the next agent looks for it. MEASURED 2026-10-03: eight worktrees across the family had been created as siblings of their repos, and the user ruled that day that it is forbidden family-wide.
- **The exit.** Put it inside the repository: git worktree add --detach .claude/worktrees/<name> <sha> (from the repo root; with -C, git -C <repo> worktree add --detach <repo>/.claude/worktrees/<name> <sha>). To relocate one: git worktree move <tree> <repo>/.claude/worktrees/<name>. A clone takes an explicit target <repo>/.claude/worktrees/<name> -- or is better a worktree. A FAMILY repo is the one clone that goes outside: into the siblings root, the directory holding the family's checkouts (`[repos]` in the machine file, `dev_lab.dev.family.members.siblings_root`), as `cd`s then ONE `git clone <url> <root>/<repo>` whose <repo> is new and named for the url, from a forge (scheme, host, owner) a sibling's `origin` already uses.

## BARE-INTERPRETER

- **Why it is refused.** `uv run` or `uvx` runs an interpreter somebody else chose -- uv's managed one -- not this checkout's venv, and `uv run` may also mutate the checkout's environment outside the checked dependency door. Each worktree owns `.venv`; main's environment belongs only to main, never to an unpopulated lane.
- **The exit.** Run this checkout's own venv interpreter, printed by absolute path: `{python} <args>`. If it is missing, `{python} -m dev_lab.dev.dep --bootstrap <worktree>` (the main checkout's interpreter, for a linked worktree) to create the target's own environment. Use the repo-declared dependency-sync door (`scripts/gate/dep_sync.py` where supplied) for dependency changes. Agents may run these specific checked doors; this does not permit arbitrary installers or silent main-environment mutation. A repo-declared CLI stays allowed.

## BARE-PYTHON

HINT: a bare interpreter mutates nothing; the hazard is a wrong interpreter, not harm.

- **Why it is said.** a bare `python`/`py` runs the interpreter the PATH chose, not this checkout's venv, so an import
  resolves against packages this checkout never declared and a result cannot be reproduced from the lock. It mutates
  no environment, which is why it hints (toolchain plan P3, 2026-10-23) while BARE-INTERPRETER, whose `uv run` may
  sync one, refuses.
- **The exit.** The same as BARE-INTERPRETER's: this checkout's own interpreter by absolute path,
  `{python} <args>`. If it is missing, `{python} -m dev_lab.dev.dep --bootstrap <worktree>` to create the target's own environment; main's environment belongs
  only to main.

## RECURSIVE-GREP

HINT: the hazard is minutes, not harm.

- **Why it is said.** `grep -r` walks the filesystem, so it descends into every git-ignored tree a checkout carries: `.venv`, `output/`, `target/`, nested worktrees. MEASURED 2026-10-05 in one consumer repo: `grep -r` over the repo did not finish in 4 min, `git grep -l` took 0.28 s, and about 66k git-ignored files were walked. A grep on a named file, a grep reading a pipe and `git grep` never walk, so they are permitted; the row keys on the recursion flag (`-r`, `-R`, a cluster such as `-rn`, `--recursive`).
- **The exit.** Search the tracked files: git grep -n <pattern> [-- <paths>] (add `--untracked` for new files), or the agent's built-in Grep tool, which honours `.gitignore` and the family `.rgignore`.

## RECURSIVE-DELETE

- **Why it is refused.** INCIDENT 2026-10-27: an agent hand-built a delete list from `git worktree list` and ran `Remove-Item -LiteralPath "\\?\<path>" -Recurse -Force` over it; one entry was a MAIN checkout, deleted with its `.git`, unpushed work and `output/`, past the recycle bin. The door that decides deletability existed and was bypassed. Refused in both shells: `rm -r`/`-rf`/`-fr`/`--recursive` (any order), `Remove-Item -Recurse` (any case or abbreviation, and its aliases `rm`/`ri`/`del`/`rmdir`/`rd`), `rmdir /s`, `rd /s`, `cmd /c rmdir /s`, `git worktree remove` (with or without `--force`), `git clean` with `-x`, `-X`, `-d` or `--directory` (a dry run is exempt only within its own argument list), and `shutil.rmtree` in interpreter code. A recursive delete that NAMES no target (`xargs rm -rf`, `... | Remove-Item -Recurse`) is refused: its targets arrive through a pipe and nothing proves them scratch. Permitted: a delete that names at least one target and whose EVERY target is a single token with no whitespace (even quoted) and no `..` anywhere, under system temp (`/tmp/`, `$TEMP`, `$TMPDIR`, `%TEMP%`, `$env:TEMP`, `AppData/Local/Temp`) or inside an `output/` tree; a non-recursive `rm file`; an `rmdir` of an empty directory; `git clean -n`.
- **The exit.** A checkout's `scratch/` (any checkout, a main one included): `{python} -m dev_lab.dev.scratch list` shows its untracked entries and sizes, `{python} -m dev_lab.dev.scratch clear [NAME ...] [--keep NAME ...] --yes` deletes the named untracked entries, or with no names those THIS session left (its start snapshots what predates it) -- never a tracked file, never outside scratch, refusing a link that escapes it, and clearing the Windows read-only/hidden attributes a nested `.git` carries. A session's `Stop` is blocked once while scratch holds an untracked entry the session left, naming this door; `--keep NAME` acknowledges one. Worktrees and branches: `{python} -m dev_lab.dev.branchset --apply`, whose `reclaim` decides what is deletable, refuses a main checkout and keeps real work.
- **After the user approves** any other recursive delete: an approval opens no deny rule, so the agent moves the approved path under `output/` (a delete there is not refused) and deletes it there itself; the user is never handed the command (AGENT-RUNS-ITS-OWN-COMMANDS).

## REPORTS-LIVE-IN-MEMORY

- **Why it is refused.** User ruling 2026-10-11: `output/` holds only what a program can regenerate (run logs, run records, measurements, charts, caches). A report a person or agent writes -- audit, analysis, design, plan, findings, workflow write-up -- cannot be regenerated, so under `output/` it is aged out, swept, and never indexed. Refused: a Write/Edit of a `*.md` under any `output/` segment (`dev_lab.dev.reportplace`, via the `codeplace` write hook) and a shell redirect, `tee`, `Out-File` or `Set-Content` creating one. A program writing its own Markdown is unaffected: it writes through no agent tool.
- **The exit.** Write it as a dated memory entry: `.claude/memory/<yyyy>/<mm>/<dd>/<slug>.md` with the MEMORY-SHAPE frontmatter (name, description, created, accessed, tags, metadata).

## HPC-THROUGH-THE-DOOR

- **Why it is refused.** User ruling 2026-11-06: an agent never reaches an HPC login host or Slurm directly. The night before, agents opened dozens of ssh connections per diagnosis to the login nodes (six accounts, two hosts, poll loops with `sleep`) and the cluster stopped answering ssh. Refused: `ssh`, `scp`, `sftp` or `rsync` to a login host, and `sbatch`, `srun`, `salloc` or `scancel` as a command or after `ssh`. A login host is recognised by SHAPE -- a first DNS label carrying `login`, which every declared `[hpc.clusters.<name>] hosts` entry has -- because the committed `deny-rules.json` cannot read the machine file and fleet names stay out of git (user ruling 2026-10-23). A human in a terminal is unaffected.
- **The exits, by purpose** (user ruling 2026-11-11; the refusal prints each shape, `_deny_hpc_row.USAGES`):
  - a command on a key+TOTP account: `python -m dev_lab.dev.sshhold open <user>@<login host> --hours N --code <the code the user gave>`, then `sshhold run <dest> '<cmd>'` (main session only; `--jump <bastion>`, `--plan`/`--digest` for consents);
  - deploy: `python -m dev_lab.dev.hpcaccount deploy-fleet [--account <u>]... [--dry-run]`; forget a learned row: `hpcaccount forget --repo <url> --row <key> --fleet|--account <u> [--dry-run]`; place a minted forge token: `hpcaccount credential (--login <forge login> | --drop-host <host>) [--host-config <host config>] [--url <repo url>] <user>@<login host>` with the token on stdin (rendered from its argparse, `hpcaccount.credential.usage`); `hpcaccount deploy` is run by the user on the account;
  - verify work: push, and the forge's HPC parts run it; read it with `python -m dev_lab.dev.forge queue` and `forge run show <sha>`;
  - a research batch: `python -m lab_commons.hpc submit -c <job.toml>`, then `python -m lab_commons.hpc gather -c <job.toml> --wait` (`plan`, `status`, `retry` alike); a tested commit: `python -m lab_commons.hpc run submit|gather|build --sha <sha>`;
  - clean finished output: `python -m lab_commons.hpc clean --root <abs remote dir> [--dry-run] [--timeout <s>, default 3600] --at <user@host> <name>...` (or `--grant <user>` from the machine file); a timed-out delete is idempotent, re-run it.
  - These `lab_commons.hpc` doors ride key-based `BatchMode` ssh: a KEY-ONLY host (Ada; user ruling 2026-11-11) never needs a code or a held session, so every agent publishes, gathers and cleans through them. `sshhold` is for a key+TOTP host only.
  - They SHARE and are RATE-LIMITED (user ruling 2026-11-11; `lab_commons.hpc.sshgate`): on POSIX every call rides one OpenSSH ControlMaster per host (`ControlPath` under the machine home's `state/hpc-ssh`, `ControlPersist 10m`); on Windows, whose OpenSSH cannot multiplex, a machine-wide per-host lock keeps at most one live ssh per host. Each door invocation takes one machine-wide slot per host: at least 5 s apart, at most 30 per 10 min (`[hpc.ssh] min_interval_s`, `max_per_window`, `window_s` in the machine file). Over it the door refuses with the wait -- never sleep-loop: read `forge queue`, or let ONE `gather -c <job> --wait` poll (its `poll_seconds` floor is 60 s).

## REMOTE-WRITE-THROUGH-A-DOOR

- **Why it is refused.** User ruling 2026-11-07: ssh has two kinds of target, and a write to either goes through the door named for its kind, over the one transport `dev_lab.dev.remote`. A hand-written `ssh <host> sudo ...`, `git pull`, `systemctl restart ...` (any verb that changes a host) or an upload by `scp`/`rsync` (its last argument `host:path`) leaves no record of which door, host or reason changed it. Read-only ssh (`uptime`, `systemctl --no-pager status`, `journalctl`, `cat`, `ls`) and a download stay open. HPC login hosts are refused whole by HPC-THROUGH-THE-DOOR, which fires first.
- **The exit.** A server the integrator deploys: `python -m dev_lab.dev.opsserver <server> install|status|restart|reload|logs|daemon-reload [<unit>]` (the ops account's fixed sudo verbs; the server is a `[[server]]` table of the machine file). A cluster account: `python -m dev_lab.dev.hpcaccount deploy-fleet`.

## STATUS-VIA-DOORS

- **Why it is refused.** User ruling 2026-10-26: `tests/review` and `tests/review-hold` are the RECORD of the forge's review, posted by the forge alone. A raw `forge status post` on either claims a review nobody ran; `tests/review` is `failure` only on a security finding (user ruling 2026-11-06), and a raw post would clear it with no fix and no review behind it. `tests/security` is a merge condition judged with integration's `[tool.dev_lab.security]`, never the head's own; a raw post on it would let a head widen its own exemptions unrecorded, so it is refused as well.
- **The exit.** For a security finding: fix it, then `python -m dev_lab.dev.forge review again <pr>`; the forge reviews the head again. For a continuation's carried finding: `python -m dev_lab.dev.forge review carry <pr> --resolve <id>` or `--defer <id> --reason "..."`. A review that did not run never needs a door: the PR merges with an `Unreviewed:` line. `forge review takeover <sha>` posts a session's review as advice (no status); `forge review plan <sha>` prints the slices. For a head clean only under its own new security exemptions: `python -m dev_lab.dev.forge security release <pr> --why "<reason>"` ([integration.md](integration.md)).

## SUBAGENT-NO-PUSH

- **Why it is refused.** Scoped to subagents: the engine judges this row only when the hook payload carries a non-empty `agent_id`, which Claude Code sends only inside a subagent call (forks included; a main session launched with `--agent` carries `agent_type` but no `agent_id`). MEASURED 2026-10-08 in one consumer repo: 95 of 98 runner logs that day were the same `(tree, env, selector)`, re-launched by agents polling a held box. A push is the main session's outward action, and a skipped hook publishes what nobody checked. Refused: `git push` (also `git -C X push`), `with-retry.sh push`, and hook skipping (`SKIP=`, `--no-verify`). A full tier is refused to everyone at the runner instead (VERDICTS-FROM-THE-FORGE).
- **The exit.** Commit on your lane and hand the commit SHA back to the main session. Every door the policy table gives the main session alone (`actor = main` in `dev_lab.dev.agentpolicy.POLICY`) is refused here too. It merges every ready lane and pushes; the forge produces the verdict. A targeted `measure` of the tests you wrote or touched stays yours.

## CONSENT-CODE-FROM-THE-USER

- **Why it is refused.** A consent credential (`dev_lab.ops.consent`) stands for the USER's word, given with the cluster code (`topology.md` section 5). The user gives the code and the agent runs the grant with it (user ruling 2026-11-08; the retired name is registered in `_deny_rows.RETIRED_IDS`). A code the user did not give is never passed, and none is stored, logged or reused. What stays refused is a shell write under `<machine home>/state/consent/`: a credential no issuer signed. The row matches the whole command line (`matches: 'line'`); the Write/Edit half is `dev_lab.dev.consentguard.refuse_write`.
- **The exit.** Write the request JSON (`action`, `subject`, `params`, and `cap`/`ttl` where the action allows) under `output/logs/<yy>/<mm>/<dd>/consent/` -- never `scratch/` -- and ask the user for the cluster code; once they approve and give it, run `python -m dev_lab.ops.consent grant <request.json> --code <the code they gave>`, then use the credential it wrote (`forge breakglass open --credential <id>`).
- **One code for a session and its consents.** When the work needs a host session AND consents on it, write a plan (`{"host": "<user>@<host>", "grants": [<request>, ...]}`) under `output/logs/<yy>/<mm>/<dd>/consent/`, show it to the user with `python -m dev_lab.ops.consent plan <plan.json>`, and give their ONE cluster code to `python -m dev_lab.dev.sshhold open <dest> --hours H --plan <plan.json> --digest <the digest shown>` (`dev_lab.ops.consent.plan`).

## Cross-repo refusals

When a refused command targets a repo other than the session's (its cwd, `cd X &&`, `git -C X`), the engine in `dev_lab.dev.agenthooks` adds one header line. If the target repo declares a door for the rule in its pyproject `[tool.dev_lab.doors]`, the header names that door and the target repo's exit replaces the session's. If it declares none, the header says so, and the refusal below it is the session repo's: any repo file it names belongs to the session repo and may not exist in the target.
