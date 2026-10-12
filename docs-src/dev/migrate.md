# Migrating a workstation

If you used to run the gate or heavy suite before a push, stop. Verdicts are now produced once per sha, after
the push, by a `forge serve` host, and read from the forge. Your job is to edit, measure what you touched,
commit, push, and read the queue. Upgrade lab-commons, then use the five commands below.

## Stop doing these

- Running a full suite (`verify` with no paths, a runner's `gate` or `heavy`) on your box. It refuses outside the
  producer anyway; the forge runs it once per sha.
- Waiting for a test run before pushing. No push hook runs a test; a lane or integration push needs no result.
- Merging another person's branch into yours. Your branch takes `integrate/main` only, through `forge sync`.
- Opening a pull request against `main`. Every pull request targets `integrate/main`.
- Submitting cluster jobs over ssh, or logging in to ask where a run is. The cluster pulls its own work; its
  progress is on the forge.
- Keeping state in files: a local verdict ledger, a list of open reds, a report under `output/`, a parked tag.
  Reds are `area:<name>` issues, reports are `.claude/memory/` entries, and a branch is merged or deleted.
- Editing a hook framework's YAML or a hand-written CI workflow. Hooks and CI are TOML in `pyproject.toml`
  ([project files](project-files.md#git-hooks-and-ci-workflows-are-toml)).

## Set up once

1. Bootstrap your worktree's own environment:
   `<any venv python> -m lab_commons.dev.dep --bootstrap <worktree> --sync` ([fan-out](fanout.md)).
2. Install the hooks: `.venv/Scripts/python.exe -m lab_commons.dev.hook_install --install --repo .`
   (POSIX: `.venv/bin/python`).
3. Store your own forge token: `python -m lab_commons.dev.forge auth login` ([the forge](forge.md#credentials)).

## The five commands

### 1. `forge sync` -- take integration into your branch

```
python -m lab_commons.dev.forge sync
```

Trial-merges `integrate/main` (and any ref you opted in with `--watch`) and merges only when every merge is
clean. On a conflict it names the files and merges nothing; resolve by hand with `git merge`. It never pushes.
Details: [the integrator](integrator.md#child-branches-sync-from-integration).

### 2. `verify -- <paths>` -- measure what you touched

```
python -m lab_commons.dev.verify -- tests/test_the_thing_you_changed.py
```

Targeted, seconds to minutes, never blocks. On a clean, unmoved HEAD it posts an `incremental` part for your
platform; `--no-status` keeps it local. A consumer repo may declare its own targeted door (motronics:
`python scripts/gate/runner.py measure <paths>`). Details: [the verdict model](verdict-model.md#the-tiers).

### 3. Push

```
git push origin <your-branch>
```

Through the repo's retry wrapper where it declares one. The push is the hand-off: the forge queues the new
sha, a producer claims it and posts `tests/<platform>`. Open a pull request into `integrate/main` when you
want the integrator to take it. A subagent never pushes; it hands its SHA to the main session.

### 4. `forge queue` -- read where everything stands

```
python -m lab_commons.dev.forge queue
```

The one status command: every candidate with its score and why it waits, every run in flight with its owner
and progress, every host card, every starved candidate. It posts nothing. `forge status list <sha>` reads one
commit's parts. Details: [the forge](forge.md#the-queue).

### 5. Issue labels -- ask for priority, keep artefacts

| label | on | effect |
|---|---|---|
| `priority:user` | a PR or issue | adds the declared boost to its value in the queue |
| `priority:<n>` | a PR or issue | adds `n` |
| `forge:request` | an issue | makes the issue a queued request (`platform = "<p>"` in the body) |
| `keep` | a PR or issue | pins its sha's artefacts past retention |
| `area:<name>` | an issue, written by `forge route` | one open list of reds per area; fix them on your branch |

Write issues and comments only through `python -m lab_commons.dev.forge issue ...`. Details: [issues](issues.md).

## Where things moved

| you used to | now |
|---|---|
| read a local log to know if a sha is green | `forge status list <sha>` or `forge queue` |
| push `main` after a local heavy run | `forge promote` (integrator only), when every part is a full PASS |
| hold a branch "for later" | merge it or delete it ([one branch per session](branch-set.md)) |
| submit a cluster job from your box | nothing; the cluster's `forge serve` claims it ([HPC clusters](hpc.md)) |
| write a findings file under `output/` | a dated `.claude/memory/<yyyy>/<mm>/<dd>/<slug>.md` entry |
