# Refusals

When a deny hook refuses a command, it prints three lines: what was refused and why, the command to run instead,
and a `details:` pointer to a section of this page. Run the command it names. Each section below holds the full
reasoning for one universal row (`INJECTED-TEXT-IS-PROGRESSIVE`); a repo-local row is on that repo's own page.

## The shape of a refusal

The budget is declared data in `lab_commons.dev.disclosure.BUDGETS`:

- `<ID>: <what was refused and why, as one clause>`
- the exact command to run instead (the door);
- `details: docs-src/dev/refusals.md#<id> (lab-commons)`, which points at the section below.

When a command targets another repo, the engine adds one header line naming that repo. `lab_commons.dev.famtests.injectedtext` runs the budget in a consumer's suite. `{remedy}` in an exit is the consuming repo's own door.

## BARE-TEST-INVOCATION

- **Why it is refused.** a hand-written test line has no VERDICT. An exit code cannot say whether the run COVERED what it selected, so a dead worker, a truncated run or a collection error that reported nothing all read as green -- and the reader has merged "the tests passed" with "nobody knows".
- **The exit.** Re-issue through the entry point that produces a verdict: {remedy}

## FORGE-WRITE-VIA-CLI

- **Why it is refused.** a forge write through any client but the family door carries no PROVENANCE. The forge records only the token`s login, and every agent on a box shares one token, so an issue, comment, close or PR written this way cannot say which machine or which agent wrote it. The family door opens every body it writes with `[<machine> · <agent> · <branch>]`, read from HARNESS_MACHINE / HARNESS_AGENT.
- **The exit.** Write through the family door: .venv/Scripts/python.exe or .venv/bin/python -m lab_commons.dev.forge issue create|comment|close, pr create (reads: issue list|view, pr view; token: auth login|status). A write the door has no verb for -- merge, edit, review -- is the steward`s to make: report it rather than reaching for another client.

## FORGE-WRITE-VIA-GH-API

- **Why it is refused.** a forge write through any client but the family door carries no PROVENANCE. The forge records only the token`s login, and every agent on a box shares one token, so an issue, comment, close or PR written this way cannot say which machine or which agent wrote it. The family door opens every body it writes with `[<machine> · <agent> · <branch>]`, read from HARNESS_MACHINE / HARNESS_AGENT.
- **The exit.** Write through the family door: .venv/Scripts/python.exe or .venv/bin/python -m lab_commons.dev.forge issue create|comment|close, pr create (reads: issue list|view, pr view; token: auth login|status). A write the door has no verb for -- merge, edit, review -- is the steward`s to make: report it rather than reaching for another client.

## FORGE-WRITE-VIA-HTTP

- **Why it is refused.** a forge write through any client but the family door carries no PROVENANCE. The forge records only the token`s login, and every agent on a box shares one token, so an issue, comment, close or PR written this way cannot say which machine or which agent wrote it. The family door opens every body it writes with `[<machine> · <agent> · <branch>]`, read from HARNESS_MACHINE / HARNESS_AGENT.
- **The exit.** Write through the family door: .venv/Scripts/python.exe or .venv/bin/python -m lab_commons.dev.forge issue create|comment|close, pr create (reads: issue list|view, pr view; token: auth login|status). A write the door has no verb for -- merge, edit, review -- is the steward`s to make: report it rather than reaching for another client.

## GIT-COMMIT-AMEND

- **Why it is refused.** `--amend` does not act on YOUR last commit, it acts on HEAD -- and on a shared lane HEAD belongs to whoever committed most recently. This family has NO single-agent mode, so "I just committed" is not a safety argument; it is the exact condition under which this fires. MEASURED 2026-09-18 on `feat/consumer-c`: agent A committed, agent B committed 40 seconds later, and A amended to fix two digits in its OWN message -- rewriting B's commit and replacing B's message with A's. It was caught inside a minute through `git reflog` and the tree recovered byte-identical, so only the SHA moved; nothing about the recovery made that outcome likelier than losing the work.
- **The exit.** Do not rewrite -- land the correction FORWARD. Read what HEAD actually is first: git log -1 --format="%h %an %s". If the CONTENT is wrong, commit the fix on top. If only the message is wrong and nothing a reader acts on changes, record the correction where the work is reported and leave the commit alone; that is the right call once anything sits on top of it.

## GIT-NETWORK-VERB

- **Why it is refused.** the forge is a REMOTE service that nobody in this family restarts, and a single transient auth/DNS/connection failure on any of these verbs reads as "blocked" -- which is the report the retry wrapper exists to prevent. Measured 2026-08-21 on a `git fetch`: it failed auth once and succeeded on the retry, and was reported blocked in between.
- **The exit.** Re-issue through the retry wrapper, which retries 3x and then REPORTS with a diagnosis: {remedy}

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
- **The exit.** LOSSLESS-DELETE: `python -m lab_commons.dev.branchprune delete <branch>...` fetches, deletes only when every commit on the branch is on integration or on another live origin branch / open PR head (naming that container), and otherwise refuses naming the commits that would be lost. Local cleanup stays a door: `python -m lab_commons.dev.branchset --apply` deletes merged LOCAL branches only and lists origin's.

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
- **The exit.** Put it inside the repository: git worktree add --detach .claude/worktrees/<name> <sha> (from the repo root; with -C, git -C <repo> worktree add --detach <repo>/.claude/worktrees/<name> <sha>). To relocate one: git worktree move <tree> <repo>/.claude/worktrees/<name>. A clone takes an explicit target <repo>/.claude/worktrees/<name> -- or is better a worktree.

## BARE-INTERPRETER

- **Why it is refused.** a bare `python`/`py`, `uv run` or `uvx` runs an interpreter somebody else chose -- the PATH's, or uv's managed one -- not this checkout's venv. `uv run` may also mutate the checkout's environment outside the checked dependency door. Each worktree owns `.venv`; main's environment belongs only to main, never to an unpopulated lane.
- **The exit.** Run this checkout's own venv interpreter: `.venv/Scripts/python.exe <args>` on Windows or `.venv/bin/python <args>` on POSIX. If it is missing, an existing checkout interpreter may run `-m lab_commons.dev.dep --bootstrap <worktree>` to create the target's own environment. Use the repo-declared dependency-sync door (`scripts/gate/dep_sync.py` where supplied) for dependency changes. Agents may run these specific checked doors; this does not permit arbitrary installers or silent main-environment mutation. A repo-declared CLI stays allowed.

## RECURSIVE-GREP

- **Why it is refused.** `grep -r` walks the filesystem, so it descends into every git-ignored tree a checkout carries: `.venv`, `output/`, `target/`, nested worktrees. MEASURED 2026-10-05 in one consumer repo: `grep -r` over the repo did not finish in 4 min, `git grep -l` took 0.28 s, and about 66k git-ignored files were walked. A grep on a named file, a grep reading a pipe and `git grep` never walk, so they are permitted; the row keys on the recursion flag (`-r`, `-R`, a cluster such as `-rn`, `--recursive`).
- **The exit.** Search the tracked files: git grep -n <pattern> [-- <paths>] (add `--untracked` for new files), or the agent's built-in Grep tool, which honours `.gitignore` and the family `.rgignore`.

## REPORTS-LIVE-IN-MEMORY

- **Why it is refused.** User ruling 2026-10-11: `output/` holds only what a program can regenerate (run logs, run records, measurements, charts, caches). A report a person or agent writes -- audit, analysis, design, plan, findings, workflow write-up -- cannot be regenerated, so under `output/` it is aged out, swept, and never indexed. Refused: a Write/Edit of a `*.md` under any `output/` segment (`lab_commons.dev.reportplace`, via the `codeplace` write hook) and a shell redirect, `tee`, `Out-File` or `Set-Content` creating one. A program writing its own Markdown is unaffected: it writes through no agent tool.
- **The exit.** Write it as a dated memory entry: `.claude/memory/<yyyy>/<mm>/<dd>/<slug>.md` with the MEMORY-SHAPE frontmatter (name, description, created, accessed, tags, metadata).

## SUBAGENT-NO-PUSH

- **Why it is refused.** Scoped to subagents: the engine judges this row only when the hook payload carries a non-empty `agent_id`, which Claude Code sends only inside a subagent call (forks included; a main session launched with `--agent` carries `agent_type` but no `agent_id`). MEASURED 2026-10-08 in one consumer repo: 95 of 98 runner logs that day were the same `(tree, env, selector)`, re-launched by agents polling a held box. A push is the main session's outward action, and a skipped hook publishes what nobody checked. Refused: `git push` (also `git -C X push`), `with-retry.sh push`, and hook skipping (`SKIP=`, `--no-verify`). A full tier is refused to everyone at the runner instead (VERDICTS-FROM-THE-FORGE).
- **The exit.** Commit on your lane and hand the commit SHA back to the main session. It merges every ready lane and pushes; the forge produces the verdict. A targeted `measure` of the tests you wrote or touched stays yours.

## Cross-repo refusals

When a refused command targets a repo other than the session's (its cwd, `cd X &&`, `git -C X`), the engine in `lab_commons.dev.agenthooks` adds one header line. If the target repo declares a door for the rule in its pyproject `[tool.lab_commons.doors]`, the header names that door and the target repo's exit replaces the session's. If it declares none, the header says so, and the refusal below it is the session repo's: any repo file it names belongs to the session repo and may not exist in the target.
