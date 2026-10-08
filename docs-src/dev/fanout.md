# Fan-out — parallel lanes in worktrees

- Mechanics for working several changes in parallel; every rule below was measured before it was written.
- The tiers, walls and verdict are on [the verdict model](verdict-model.md); what breaks when a tool assumes it owns the checkout is on [the shared checkout](shared-checkout.md).

## Environments — each worktree owns its venv

- Each worktree owns its `.venv`, including an editable install of its own source. A missing environment needs bootstrap, not borrowing the primary checkout's interpreter for a verdict.
- A worktree's runner uses that worktree's own interpreter, so its source and installed dependencies belong to the same checkout. Under fan-out only the coordinator's worktree runs a broad verdict — a lane runs at most a targeted measure (Concurrency, below).
- The runner takes a root, and the root picks the SOURCE and the TESTS together.
- **The dependency door is the agent's to run.** Syncing its own worktree's environment is a local operation requiring no human. Never change the primary checkout's environment from a lane.
- Environment exclusion is per environment: a verdict in worktree A prevents mutation of A's environment, not bootstrap or sync of B's. CPU contention remains the box lock's responsibility.

### Bootstrap and sync

Use an interpreter that already has `lab-commons[dev]` to create or repair a named worktree's environment:

```text
<available python> -m lab_commons.dev.dep --bootstrap <worktree>
<own venv python> -m lab_commons.dev.dep --root <worktree> --sync
```

The available interpreter is only the launcher; the target is always `<worktree>/.venv`, never an inherited `VIRTUAL_ENV`. An empty environment does not need to import lab-commons before bootstrap. Import or sync failures exit non-zero. A worktree cannot target the primary checkout's environment.

Declare the consumer's complete selection and verdict anchors in its own `pyproject.toml`:

```toml
[tool.lab_commons.dep]
extras = ["all", "dev", "img-to-cad", "tooldrivers"]
anchors = ["output/gate-verdict.txt"]
```

These names are examples, not family defaults: every extra must exist in that consumer's optional-dependencies table, and anchors must name its actual verdict files. Without an extras declaration, the door selects all declared extras. With no `--extra`, sync realizes the complete declared selection; repeated explicit `--extra` flags deliberately narrow it and can prune other packages. `--dry-run` checks without mutation. A changed environment retires its declared verdict anchors, including after a failed install that changed packages.

Generated auto-mode allow rows name only these dependency doors under worktree interpreters, on Windows and POSIX. They do not permit arbitrary installers. Regenerate consumers' permissions, deny rows, hooks and refusal docs after upgrading lab-commons; old recorded shared-environment incidents remain historical memory, not current instructions.
- **A log name is a NAME, not a path** (user directive 2026-09-08): the runner puts it under its own dated directory and creates that directory itself, so there is nothing to create and nothing left loose. A name carrying a separator or a drive is REFUSED rather than normalised — the two escape hatches that stood before then excused far more than the destinations they were written for, and every in-repo caller already passed a bare name.

## Setting up

- Branch from the up-to-date INTEGRATION branch, never from `main`, which lags.
- Lane creation seeds the ignored files a checkout cannot work without, and proves each copy by comparison rather than by assumption.
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
- **Ask a subagent for no broad verdict**: it resolves, audits, runs at most a targeted `measure` of what it touched, commits and hands back its SHA (Concurrency, below). Measured 2026-09-15: a subagent's gate launched as a background task is reaped by the agent harness during collection and leaves an EMPTY log — it proves nothing in either direction, and costs the box lock while it lives.
- The coordinator's own run may hold the box lock for hours while its subagents work. Tell each one explicitly **not to kill processes or delete the lock file** — an agent trying to be helpful can destroy a four-hour verdict in one command.

## Concurrency — tests run once, after integration

- **`ONE-RUN-AFTER-INTEGRATION`** (user ruling 2026-10-08; statement in `lab_commons.dev.rules`): a lane or subagent runs no broad verification -- no gate, no heavy. It may run a targeted `measure` of the tests it wrote or touched, then commits and hands back its SHA. The coordinator's MAIN session merges every ready lane into one integration tree and runs the gate ONCE; that verdict, recorded in the verdict ledger, is what the integration push cites. A lane push needs no verdict of its own.
- **ENFORCED.** `SUBAGENT-NO-HEAVY-NO-PUSH` refuses a subagent's push, gate/heavy tier, `--with-heavy` and hook skipping in the agent guard (keyed on the hook payload's `agent_id`); admission admits a lane with no verdict and reads the integration verdict off the ledger; the runner queues on a held box, attaches a duplicate `(tree, env, selector)` to the run in flight, and cites a key the ledger already holds.
- Measured 2026-10-07 in a consumer: five lanes measuring at once queued on the box's ONE CPU lock and re-ran what the combined `gate`/`heavy` runs anyway; one lane measure took 40 minutes to 2.5 hours. Measured 2026-10-08: 95 of 98 runner logs in a day were one key, re-launched by polling agents.
- The hazard is the test SESSION, not the tier, and a serial run is not "small": four lanes once obeyed "never run a full gate" by running 274 tests serially, a slow integration test, and two single files — none of them a gate — and the box hit 54 python processes until the serial gate they were protecting lost a worker and blocked forever waiting on it. A targeted measure is the tests you touched, not a subset of the suite.

## Reading a result

- Reading a verdict — exit versus log, missing logs, the tree stamp, and the reds-in-code-you-never-touched procedure — is owned by [the verdict model](verdict-model.md).
- Two additions for the coordinator reading one under fan-out: the process table answers "is it alive", never "where is it", so dump the stack of the pid a process probe reports rather than guessing from the table; and **a number you cannot reproduce is an anecdote with a decimal point** — two agents measured the same quantity as 3.05 to 5.08 s and 12.24 to 12.64 s, both were right, and one box had 29 busy processes.

## Landing

- Each lane: implement, run the static audits, commit on its branch, then hand back its SHAs and every file touched. It pushes nothing: a push cites a verdict, and a lane has none.
- The coordinator's MAIN session merges the lanes back to back, each through the merge audit, then verifies ONCE — one `gate` and one `heavy` on the combined tip — and bisects over the batch's merges only when that verdict is red (log2 N runs, not N). Two lanes can compose into a broken tree, which is why the batch verdict is the only one that answers. Then it pushes.
- **Never write "merged" from memory**: the ancestor test answers "is this COMMIT in the target", and `git cherry` catches a cherry-pick whose sha changed. Run the ancestry check first, fall back to the other, and state which one answered.
- The moment it says merged, delete the worktree, its output directory, and the lane branch — check the tree is CLEAN first, and trust the branch, not the directory name.
