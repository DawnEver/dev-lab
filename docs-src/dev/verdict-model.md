# The verdict model — one entry, one measurement, two verdicts

- **One entry point produces a verdict, and a hand-written test-runner line never does** — only the entry distinguishes INCONCLUSIVE from PASS/FAIL. In this family the portable one is `python -m lab_commons.dev.verify`; `consumer-a` additionally has a case-library and vendor-engine aware driver under its own `scripts/gate/`, which the other three repos do not have and do not need.
- A MEASUREMENT and a VERDICT are different acts. A verdict answers "may this land" and needs a tree it can name, so a dirty one disqualifies it; a measurement answers "where am I" and runs on a dirty tree because that is what development is. A measurement never speaks PASS/FAIL/INCONCLUSIVE.
- **The stdout line is the verdict, never the evidence.** The run writes a full log and the summary line does not name it, so a reader who only has the line cannot see WHICH test failed. Two runs of the same tier on the same day overwrite each other unless one is given its own log name, which is why a run whose failures you intend to read gets one.

## The three tiers

| tier | selection | wall | who runs it |
|---|---|---|---|
| measure | the paths you name, else the working tree's diff; lightweight only | seconds of feedback | the agent, after each edit |
| gate | the push increment's reach (last-pushed sha to HEAD, else the integration branch, else `main`), lightweight only | 30 min HARD | the forge's producer only, never a developer |
| heavy | everything, including every LOCAL live engine the repo declares | unbounded, NEVER blocking | the forge's producer only, never a developer |

- **An engine is enabled by the TIER, never by the shell.** The heavy tier sets the live-engine environment itself, so a heavy verdict always covers the engines this box has. Do not re-copy the engine list into prose: measured in consumer-a, a prose row promised an engine whose variable was never set, and 27 plus 13 tests skipped as "opt-in" on a machine where both were installed.
- **A skip says WHICH fact stopped it.** "Not installed on this box" is about the machine and no variable fixes it; "installed but not enabled" is about the caller. Conflating those makes every skipped line read as a choice when it is a gap.
- **A resource on ANOTHER host is never part of a verdict about this tree.** Reachability of someone else's machine is not a property of your tree and may not gate a judgement about it — it reddened a blocking tier that way once already.
- The 30-minute wall is ONE AGENT RESPONSE, not a taste in test duration: past it the prompt cache is gone and the agent reading the answer is no longer the agent that asked.
- A run over the wall has not become slow — it has become a different TIER: the runner returns INCONCLUSIVE and says to re-issue as heavy, and nothing may ask for a bigger number.
- **A budget is a ceiling on the WAIT, not on the work** — split it, parallelise it, or move it off the blocking path; never raise the ceiling.
- **What the partition removed is REPORTED, never assumed to be nothing.** Count what the runner was ASKED to collect, before deselection, and ship it from the workers: under parallel execution the controller is told NOTHING about a deselection. Measured 2026-09-01, the same two targets read 138 collected plain and 186 collected with the heavy tests included, and the plain line carried no warning. A run with no census is INCONCLUSIVE, and one that executed nothing is an error rather than a pass.

## What each tier GATES — the DESTINATION decides the bar

| destination | the bar | what does NOT block it |
|---|---|---|
| a lane (`feat/...`, `fix/...`) | NONE: the forge produces its parts after the push; a developer may run a targeted `measure` | everything |
| the integration branch | NONE: the forge produces its parts after the push | everything |
| `main` | every `tests/<platform>` part of HEAD a PASS of scope `full`, read from the forge | nothing — this is the ONE hop where everything must be green |

- **THE BAR IS THE INCREMENT, NOT THE TREE** (user ruling 2026-09-07): a lane answers for the code it developed and a merge answers for what it brought in, so a red your increment did not cause is INVENTORY the integrator assigns, never a personal blocker.
- **No tier blocks a push, and no developer runs a full one** (`VERDICTS-FROM-THE-FORGE`, user report 2026-10-11): a full tier runs only in the producer `forge serve` spawns for a claimed part (`lab_commons.dev.producer`); anywhere else it refuses with the remedy -- push, the forge produces the part. A settled run posts its `tests/<platform>` part on the forge (`lab_commons.dev.platformparts`) and is cached on this box (`lab_commons.dev.runcache`, `output/runcache/runs.jsonl` in the main checkout) so a judged key is cited rather than re-run. Lane and integration pushes are admitted with no result; the merge audit still runs on every destination. The trunk reads the forge, never a log or a cache: every part of HEAD a PASS of scope `full`. An INCONCLUSIVE run is no part and is never cached. ONE implementation, `lab_commons.dev.admission` (library and CLI); `famtests.localadmission` refuses a consumer copy.
- **A duplicate request never runs twice.** A producer whose box is held QUEUES (`boxwait.WAIT_S`); a measure waits at most `MEASURE_WAIT_S` and then refuses naming the holder, and a request with the same `(tree, env, selector)` as a run in flight ATTACHES to it and receives its answer (`lab_commons.dev.inflight`). A key the ledger already holds is CITED without running; `--rerun` overrides. Measured 2026-10-08 in one consumer: 95 of 98 logs that day were one key, re-launched by polling agents.
- **Inventory is CARRIED, not asserted.** "That red was not mine" from an agent is self-certification; the honest form is an enumerated table that only shrinks, red on a NEW entry and red on a STALE one alike.
- No mechanism distinguishes "my increment caused this red" from "this red pre-existed inside my increment's reach". The honest test is a baseline comparison — restore the prior file, re-measure, diff the residuals — and it is done BY HAND.

## The verdict itself

- A verdict is a tree, an environment, a selector, a result and a log: the tree and the environment are PART of it, so a different tree or a different set of installed packages means the verdict does not EXIST, not that it is stale. `lab_commons.dev.verdict` is the algebra; `lab_commons.dev.content` and `lab_commons.dev.envkey` are the two halves of its address.
- The result STARTS INCONCLUSIVE and is PROMOTED only when every completeness proof holds: a clean tree, inside the wall, no truncation marker, a non-empty selection, a run that executed at least one test, a census that reconciles with the summary, a real runner exit, and collection arithmetic that accounts for every collected test.
- **That polarity is the whole design**: a new way of running incompletely — one nobody has thought of yet — degrades to "we do not know", never to "it passed".
- There is no central verdict store and no citation protocol: the process that ran the tests writes the verdict line at the END of its own log, and a citer reads that log and checks the tree against their own HEAD.
- The tree stamp carries its dirty bit on a MEASUREMENT exactly as on a verdict, and it changes no count — it records WHICH tree the counts are about. A producer that drops the bit it already computed lets a run measured dirty and summarised after the tree went clean compare EQUAL to the clean sha.
- Numerical regression uses tolerances, never hashes.

## Reading a result

- An operation's exit is NOT its effect, and never trust an exit code over a log: anything piped or chained reports the LAST thing's status, so never append anything after the command.
- A missing log means "not finished", never "not started" — the runner writes the file once, at the end.
- A present log need not be YOURS — check its tree against your own HEAD before quoting it.
- INCONCLUSIVE is not "no information": its reason names the missing proof, and each reason calls for a different next action.
- When a run reds in code you never touched: set your diff aside (a scratch commit, never a stash — the stash ref is repo-wide across every worktree), check whether the base branch is ahead, and run the suspect file ALONE. "Contention" is wrong as a presumed root cause, since new-deps-against-old-code reproduces in isolation.
- A timing from a busy box is not a property of the file: count what else is running before quoting any duration.
