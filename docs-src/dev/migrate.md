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
platform; `--no-status` keeps it local. A consumer repo may declare its own targeted door (consumer-a:
`python scripts/gate/runner.py measure <paths>`). Details: [the verdict model](verdict-model.md#the-tiers).

### 3. Push

```
git push origin <your-branch>
```

Through the repo's retry wrapper where it declares one. The push is the hand-off: the forge queues the new
sha, a producer claims it and posts `tests/<part>`. Open a pull request into `integrate/main` when you
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

## One queue for every serving host

Serve modes are gone (user ruling 2026-10-13): every host serves every class -- integration, PRs into it,
feature branches, lanes, requests -- from one queue ([scheduling](forge.md#scheduling)). Each retired spelling
is refused by name with its remedy (`lab_commons.hpc.retired`). To migrate:

- **A cluster account's machine file**: delete the `serve` key from `[deploy]` (on Ada it named the
  integration mode), then re-run `python -m lab_commons.hpc deploy` so the crontab lines become plain
  `forge serve`. A `[deploy]` still carrying the key is refused.
- **A workstation**: re-run `python -m lab_commons.dev.workstation deploy ...` without the mode flag; it
  rewrites the `lab-forge-serve` Task, whose old action is refused until then.
- **A host that should take no foreign work**: have its owner reserve it whole
  (`forge reserve <host> cpu=<all> --for login:<owner> --until ...`) instead of serving it quietly.
- **A consumer's `pyproject.toml`**: replace the opted-in branch list under `[tool.lab_commons.schedule]` and
  the prefix list under `[tool.lab_commons.integrator]` with ONE ordered rule, `[tool.lab_commons.schedule]
  classes_by_ref = {"feat/*" = "feature", "fix/*" = "feature", "lane/*" = "branch"}` (the family default;
  declare it only to differ, and a declaration replaces it whole). A branch no pattern matches is neither
  served nor a child. Starvation bounds take a `feature` row (default 18 h).
- **Who is prompted to integrate**: declare `[tool.lab_commons.integrator] host = "<card name or login>"`; that
  host's serve tick raises an `integration` alarm when the queue changes.
- **How often an alarm repeats** is the receiver's: `[alerts] repeat_hours` in the machine file (absent: 6).

## Migrating a repo to need-set parts

A part is no longer an OS or an engine but a NEED-SET ([parts by need-set](hpc.md#parts-by-need-set)). The old
per-OS and per-engine tables under `[tool.lab_commons]` and the per-part producer keys are retired
(`lab_commons.hpc.retired`); a kit reading a commit that still declares one refuses it, naming the
replacement. Migrate in ONE commit, in the same window as the lab-commons that reads it:

1. **Delete** the OS table and the capability table under `[tool.lab_commons]` (the `marker -> [OSes]` rows and
   the engine / `on = [...]` rows), and every per-part producer key under `[tool.lab_commons.parts]`. Keep
   `[tool.lab_commons.parts] output` (and `inert`).
2. **Add one table**: every marker that names a resource, and the ONE local producer, told its part by
   `{part}`:

   ```toml
   [tool.lab_commons.tests]
   resources = ["<marker>", ...]
   produce = ["-m", "lab_commons.dev.verify", "--part", "{part}"]   # or the repo's own door, "{part}" in it
   ```

   A marker belongs in `resources` when some host may lack what it names. A marker whose tests run on every
   host (a solver built on every OS) is no resource: leave it out and its tests are `base`. Mark the TOOL a
   test drives, never the OS the tool runs on; mark an OS only for a test that proves that OS's behaviour.
3. **Markers**: every name in `resources` stays registered in `[tool.pytest.ini_options] markers`, and every
   test needing it carries it (module `pytestmark` or a conftest hook). Nothing else in the suite changes.
4. **A repo's own producer door** (not `verify`) takes the part name, selects with
   `platformparts.select(root, sha, part, collect=...)` -- it returns `(its ids, {other id: its part})`, and
   `collect` is now asked for `''` and for each resource marker alone -- and writes a run record whose
   `platform` is the part and whose `handed` maps each other id to its part NAME (a string, no longer a list
   of OSes). Its full-suite refusal names `platformparts.part_context(part or platformparts.BASE)`.
5. **Hosts**: a host has a resource when its machine file declares `[capabilities.<name>]` (and, for `jmag`,
   `matlab`, `node`, the probe finds it). A Windows box that should run FEMM parts declares
   `[capabilities.femm]`; one that should run Windows-only parts declares nothing (its OS is measured).
6. **Promotion**: `forge promote` now needs `tests/base` and every part a part hands to. A server-side
   required status context should be `tests/base` only.

### consumer-a (a solver repo with JMAG, FEMM, MATLAB and SIMBA tests)

- `pyproject.toml`: delete the OS table (`femm`, `simba`, `xfemm`, `ngspice`, `matlab` rows), the capability
  table (`jmag`, `node`) and the two `produce.<part>.full` keys; add

  ```toml
  [tool.lab_commons.tests]
  resources = ["femm", "jmag", "matlab", "node", "simba"]
  produce = ["scripts/gate/runner.py", "part", "{part}", "--full"]
  ```

  `xfemm` and `ngspice` ran on every OS, so they are no resource and their tests join `base`. `simba` was a
  glibc constraint (the cluster's 2.28 < 2.29): it becomes a resource that the hosts able to import
  `aesim.simba` declare as `[capabilities.simba]`. `matlab` is probed on `PATH`; NOTE the cluster account's
  supply measures no tool, so `tests/matlab` is claimed only by a box with `matlab` until the account probe
  reads tools.
- `scripts/gate/_platform_part.py` and `runner.py part <name>`: accept any part name (`base`,
  `femm+jmag`, ...), not an OS list; `select` gets the part; the record's `handed` is `{id: part}`; the
  collection store answers `''` and each single resource marker; `part_context(part or this_platform())`
  becomes `part_context(part or BASE)`. A base part for the incremental run is the newest record of the SAME
  part.
- Retired-name registry (its retired-entries modules): add the rows this lab-commons retired
  if the repo mirrors them.

### consumer-b (no part tables yet)

- Declares no part tables today, so step 1 is empty. To have a box produce its parts (not only the cluster's
  `base` from `[tool.lab_commons.hpc]`), add `[tool.lab_commons.parts] output` and
  `[tool.lab_commons.tests] produce = ["-m", "lab_commons.dev.verify", "--part", "{part}"]`; add `resources`
  only for markers naming something a host may lack.
