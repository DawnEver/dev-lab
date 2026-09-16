# Fan-out — parallel lanes in worktrees

- Mechanics for working several changes in parallel; every rule below was measured before it was written.
- The tiers, walls and verdict are on [the verdict model](verdict-model.md); what breaks when a tool assumes it owns the checkout is on [the shared checkout](shared-checkout.md).

## Environments — own venv preferred, borrowing is the fallback

- A lane MAY have its own virtual environment, and when it does, that one wins; borrowing the primary checkout's is the fallback.
- The lane's runner must resolve the interpreter the same way every time — the lane's own environment first, then the primary's — so a verdict on a lane runs the lane's code with the right environment.
- The runner takes a root, and the root picks the SOURCE and the TESTS together.
- **When BORROWING and stepping outside the runner** — a standalone probe, a single-file run — setting the import path to the worktree's source is not a safety flag, it is the only thing making your code the code under test: omit it and the editable install answers for the package, so everything imports the PRIMARY checkout's source. Green, plausible, silent, and about the wrong tree.
- **Never install or reinstall from a worktree.** A resolver run inside one builds a base-only environment while resolving executables from the primary, and a reinstall into the shared environment drops compiled extensions for every borrowing lane.
- **A log name is a NAME, not a path** (user directive 2026-09-08): the runner puts it under its own dated directory and creates that directory itself, so there is nothing to create and nothing left loose. A name carrying a separator or a drive is REFUSED rather than normalised — the two escape hatches that stood before then excused far more than the destinations they were written for, and every in-repo caller already passed a bare name.

## Setting up

- Branch from the up-to-date INTEGRATION branch, never from `main`, which lags.
- Lane creation seeds the ignored files a lane cannot produce a verdict without, and proves each copy by comparison rather than by assumption.
- **Lane creation does NOT push, and the FIRST push is yours.** Until you make it, the lane has no last-pushed sha, so its first gate falls back to a much older base and measures far more than the increment — see [the shared checkout](shared-checkout.md).
- **Split by FILE-DISJOINTNESS**: shared hotspots — an entry-point module, the central chain, the registries every feature touches — go to ONE lane, or serialize.
- There is no lane ledger: the live audit of what exists is a script that classifies every worktree, and another that disposes of them. A ledger is a second source for a fact git already holds.

## Fanning out to SUBAGENTS — the base is not the one you are standing on

- MEASURED 2026-09-01, twice in one session: an agent spawned with an automatic worktree isolation gets a worktree based on the PRIMARY CHECKOUT's HEAD, not on the lane the coordinator is working in. **Every commit the lane has not merged is ABSENT from it.**
- The failure is quiet and expensive rather than loud: the agent greps for the symbol its task names, finds ZERO, and either reports the premise false or — worse — reasons about a different codebase and returns a confident answer about code nobody runs. Both happened; one agent burned 130k tokens designing a patch against the wrong file.
- Two agents that day were told to diagnose two exception classes. Neither existed on the primary; both lived on the integration lane. The agents were right to stop, and **stopping is the GOOD outcome of this defect** — the bad one is an agent that does not notice.
- An isolated agent is also bound to WRITE only inside its own tree. It cannot be redirected into a worktree the coordinator prepared: reads reach across, writes and shell commands refuse. Handing it a path is not a remedy.

**The pattern that works.** Spawn the agent WITHOUT automatic isolation, and make creating the worktree the first step of its own task, AT AN EXPLICIT COMMIT:

```
git worktree add --detach <path> <sha>
```

- Then have it verify it landed where you meant before doing anything else: the resolved HEAD against the sha you named, PLUS a count of a symbol the task depends on that must be NON-ZERO.
- **A base check that only prints the sha is not a check.** Name a symbol the task cannot proceed without, and make a zero count a STOP.
- **Give it the sha, never a branch name**: the integration branch moves under a long-running agent, and two agents on "the same branch" can be on two trees.
- The coordinator may create the worktree instead, but only for a NON-isolated agent; for an isolated one the tree is unreachable and the work is lost.
- One shared hazard bites subagents harder: if a long run holds the box lock, an agent invoking the runner gets a refusal rather than a result. Tell it that is EXPECTED, and tell it explicitly **not to kill processes or delete the lock file** — an agent trying to be helpful can destroy a four-hour verdict in one command.

## Concurrency — one test session at a time

- Not "one gate at a time": the hazard is the SESSION, and a serial run is not "small".
- Four lanes once obeyed "never run a full gate" by running 274 tests serially, a slow integration test, and two single files — none of them a gate — and the box hit 54 python processes until the serial gate they were protecting lost a worker and blocked forever waiting on it.
- When fanning out, lanes do the non-pytest work — static reading, standalone probes with the import path set, direct lint runs — until the lock frees.

## Reading a result

- Reading a verdict — exit versus log, missing logs, the tree stamp, and the reds-in-code-you-never-touched procedure — is owned by [the verdict model](verdict-model.md).
- Two lane-specific additions: the process table answers "is it alive", never "where is it", so dump the stack of the pid a process probe reports rather than guessing from the table; and **a number you cannot reproduce is an anecdote with a decimal point** — two agents measured the same quantity as 3.05 to 5.08 s and 12.24 to 12.64 s, both were right, and one box had 29 busy processes.

## Landing

- Each lane: implement, own verdict green, commit on its branch and PUSH it — every green commit, through the retry wrapper — then report SHAs, measured verification, and every file touched.
- Integrate onto an integration worktree and then RE-GATE: two green branches can compose into a broken tree.
- **Never write "merged" from memory**: the ancestor test answers "is this COMMIT in the target", and `git cherry` catches a cherry-pick whose sha changed. Run the ancestry check first, fall back to the other, and state which one answered.
- The moment it says merged, delete the worktree, its output directory, and the origin branch — check the tree is CLEAN first, and trust the branch, not the directory name.
