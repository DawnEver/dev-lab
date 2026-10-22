# The verdict model

A verdict says whether one tree, in one environment, passes one selection of tests. It starts INCONCLUSIVE and
is promoted only when the run proves it covered what it selected. A full-suite verdict is produced once per sha
by the forge's producer and posted as a part ([the forge](forge.md)); what you run yourself is a targeted
measurement of the tests you touched. Run it through the repo's entry point, never a hand-written test line.

## The tiers

| tier | selection | who runs it |
|---|---|---|
| measure | the paths you name, else the working tree's diff; lightweight only | you, after each edit |
| gate | the increment's reach; lightweight only; 30-minute wall | the forge's producer only |
| heavy | everything, including the local live engines the repo declares | the forge's producer only |

- The family entry is `python -m lab_commons.dev.verify -- <paths>`; a repo may add its own driver (consumer-a:
  `python scripts/gate/runner.py measure <paths>`). Exit codes: `0` pass, `1` fail, `2` refused argv,
  `3` inconclusive.
- **A full tier refuses outside the producer** (`VERDICTS-FROM-THE-FORGE`) and names the remedy: push.
- **A measurement runs on a dirty tree** and answers "where am I"; it never decides whether anything may land.
- **Only the producer posts.** A `verify` that `forge serve` spawned for a part posts that part on a clean,
  unmoved HEAD; any other `verify` is a local measure and posts nothing. A dirty tree posts nothing.
- **An engine is enabled by the tier, never by the shell**: the heavy tier sets the live-engine environment
  itself. A skip says which fact stopped it: not installed on this box, or installed but not enabled.
- A resource on another host is never part of a verdict about this tree.
- **The 30-minute wall is a budget on the wait, not on the work.** A run over it is INCONCLUSIVE; split,
  parallelise or move the work, never raise the ceiling.
- **What the partition removed is reported**: the run counts what it was asked to collect before deselection.
  A run with no census is INCONCLUSIVE, and one that executed nothing is an error.

## What each destination needs

| destination | the bar |
|---|---|
| a child branch | none: push; the forge produces its parts afterwards |
| the integration branch | none: the forge merges on the children's parts |
| `main` | every `tests/<part>` part of HEAD a PASS at scope `full`, read from the forge |

- **The bar is the increment, not the tree** (`VERDICT-BAR-IS-THE-INCREMENT`): a red your change did not cause
  is inventory, routed to its `area:*` issue, never your blocker.
- No push hook runs a test. The merge audit runs at commit time on every destination
  ([the integration branch](integration.md#the-merge-audit)).
- The one implementation of these bars is `lab_commons.dev.pushgate`; a consumer copy is refused
  (`famtests.localadmission`).

## A duplicate request never runs twice

- A request with the same `(tree, env, selector)` as a run in flight attaches to it and receives its answer
  (`lab_commons.dev.inflight`).
- A key the run cache already holds is cited without running (`lab_commons.dev.runcache`); `--rerun` overrides.
- A measure waits at most `verifybox.MEASURE_WAIT_S` for the box and then refuses naming the holder.
- A measure's pytest step runs in the box at its declared claim (`verifybox.selection_demand`: one core per
  worker its `-n` runs, from `verifybox.selection_workers` -- one when serial, else `compute.learned.fit_width` of
  `SELECTION_CPU`, the files selected and the box's free room unless the caller names a width -- the memory its files measured, `verifybox.selection_mem_gb`, and `SELECTION_WALL_S`) beside whatever else fits; a producer runs
  at the demand serve admitted it at ([box resources](box-resources.md)).
- A heavy part is offered only for the refs its `[tool.lab_commons.parts.refs.<part>] <scope>` admits
  (`platformparts.part_refs`), and every producer runs below normal OS priority (`forgeproduce.below_normal`).

## The verdict itself

- A verdict is a tree, an environment, a selector, a result and a log. A different tree or a different
  environment means the verdict does not exist (`lab_commons.dev.verdict`, `content`, and `lab_commons.envkey`).
- **It starts INCONCLUSIVE** and is promoted only when every proof holds: a clean tree, inside the wall, no
  truncation, a non-empty selection, at least one test executed, a census that reconciles with the summary, a
  real runner exit, and collection arithmetic that accounts for every collected test. A new way of running
  incompletely therefore degrades to "we do not know", never to "it passed".
- The verdict line is written at the end of the run's own log; the full log is the evidence.
- The tree stamp carries its dirty bit on a measurement too; it records which tree the counts are about.
- Numerical regression uses tolerances, never hashes.

## Reading a result

- Trust the log over an exit code: a pipe or chain reports the last command's status, so append nothing.
- A missing log means not finished, never not started. A present log need not be yours: check its tree.
- INCONCLUSIVE names the missing proof, and each reason calls for a different next action.
- **When a run reds in code you never touched**: set your diff aside with a scratch commit (never a stash),
  check whether the base moved, and run the suspect file alone.
- A timing from a busy box is not a property of the file: count what else is running before quoting it.
