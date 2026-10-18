# HPC clusters

A Slurm cluster is one more `forge serve` host. Its login node pulls work from the forge over HTTPS, submits a
commit's suite as a Slurm array, gathers the record and posts the `linux` part; nothing reaches it inbound.
To serve a cluster account, store your forge token there and paste the one deploy line below. To see what a
cluster is doing, run `forge queue` from anywhere; ssh is only a human's debugging door.

## Deploy: one line per account

On the login host you chose, store your own forge token once (`git config --global credential.helper store`,
`chmod 600 ~/.git-credentials`, then `python -m lab_commons.dev.forge auth login`), then paste:

```
[ -x ~/.local/bin/uv ] || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh; F=https://<forge>/<org>; D=~/src/lab-commons; { [ -d $D/.git ] || git clone -q -b integrate/main $F/lab-commons.git $D; } && git -C $D pull -q --ff-only && cd $D && PYTHONPATH=$D/src ~/.local/bin/uv run --no-project --python 3.13 python -m lab_commons.hpc deploy --host <login host> --repo lab-commons=$F/lab-commons.git@integrate/main --repo <repo>=$F/<repo>.git@integrate/main --partition <partition> ...
```

- **The same line is the upgrade.** The first run stores the declaration (`[deploy]` in the account's machine
  file: host, root, python, served repos, partitions, and `--slurm-account` when Slurm names several); later
  runs read it, and flags that disagree with it are refused. `lab-commons` is always served: every tick runs it.
- **The host refreshes; a repo never updates itself.** Each cron line runs the HOST's kit,
  `python -m lab_commons.hpc tick <repo>` from the lab-commons checkout: it checks out `~/<root>/lab-commons`
  and then the repo at their deployed refs, rebuilds the repo's venv where its inputs (its committed `uv.lock` among them) moved
  (the deploy's own keyed steps), and only then serves it: THE HOST KIT's `forge serve` with the repo checkout
  as its cwd. The repo's venv only runs its producers, in their trees, so one host runs one scheduler. A repo whose refresh fails is
  released for that tick, its reason in its log; a kit that cannot move is reported and the repo serves with
  the kit it has. Only the crontab itself changes when you re-run the line.
- **What it does** (`lab_commons.hpc.deploy`): refuses off the declared host; checks the account before changing
  anything -- `credential.helper` set and `~/.git-credentials` mode 600, `git ls-remote` per repo, and
  `forge auth check` per repo (the API calls a tick makes: `GET /user`, push permission for commit statuses,
  the issue list); writes the account's own `[[hpc.grant]]` when it has none (user from `id -un`, account and
  `cpu=` limit from `sacctmgr`, this host, the declared partitions); clones or fast-forwards each checkout;
  installs `uv` and the Rust toolchain from their official installers into `~/.local` and `~/.cargo` (no PATH
  edit) and `cmake` through `uv tool` when the tick PATH lacks them, and refuses any other missing `needs` by
  name; builds each `.venv` with the repo's own `[tool.lab_commons.hpc] install` and `native` build on a
  uv-managed CPython (skipped while its inputs are unchanged) -- exactly what the repo's committed `uv.lock`
  pins, with nothing installed over it, so a repo's producers import the lab-commons its commit was tested
  with (PIN + FRESHNESS, user ruling 2026-10-17); replaces its own marked crontab lines; runs one tick of each repo and prints it.
- A grant's compute-node `setup` (e.g. `module load git`) is a cluster fact the deploy cannot read: add it to
  the written grant by hand.
- `--dry-run` prints every action; `--remove` deletes the marked crontab lines only.
- **The crontab line**, per repo, every 5 minutes:
  `PATH=...; cd ~/src/lab-commons && flock -n ~/.cache/lab-forge-<repo>.lock .venv/bin/python -m lab_commons.hpc tick <repo> >> ~/.cache/lab-forge-<repo>.log 2>&1 # lab-commons-deploy:<repo>`.
  Every alarm a tick raises rides on the host's card and `forge queue` prints it; `[alerts]` in the machine
  file adds Telegram/email/webhook delivery.
- **One login host per account.** Cron is per host and `flock` on a shared filesystem does not lock across
  hosts. A second host finding a live run owned by another host of its account leaves it alone until that
  owner's lease lapses on the forge's clock.
- **Identity is read, never typed**: the claim names `<cluster>/<account>` from Slurm's `ClusterName` and
  `id -un` (`lab_commons.hpc.account`).
- The cron `PATH` is `~/.local/bin:~/.cargo/bin:/usr/local/bin:/usr/bin:/bin` plus the directories `sbatch`, `sacct` and `squeue` resolve in when the deploy runs (it refuses without them); the deploy checks every tool
  there, not on the login shell's PATH.

## Grants: the machine file

The account's `[hpc]` table in `~/.config/lab-commons/config.toml` (`$LAB_COMMONS_CONFIG` overrides the path)
holds one `[[hpc.grant]]` per Slurm account it may reach. Partitions, QOS and compute-node set-up are cluster facts, so they
live on the grant.

```toml
[[hpc.grant]]
user = "me"                          # equal to the login on that cluster
hosts = ["login2.cluster", "login1.cluster"]
slurm_account = "acct-free"
partitions = ["shortq", "defq"]      # optional, in preference order
qos = { devq = "dev" }               # optional
setup = ["module load git/2.42.0"]   # optional, prepended to every array task

[hpc.paging]                         # optional; every key required when declared
page_cpus = 8                        # one page -- a SMALL task fits it
page_mem_gb = 20
large_pages = 4                      # more pages than this is LARGE; between is MEDIUM
movable_minutes = 30                 # rerun-safe AND this short = movable
```

- A missing table, a duplicate account or an empty `hosts` is refused with the key named; a `cpus` share is retired
  and refused by name: admission fits each job against what the account has free now ([admission](forge.md#admission)).
  No secrets in the file.
- **The accounts are one pool; a session has a share, and no machine file holds it** (user ruling 2026-10-17:
  an allocation between sessions is temporary). Every job carries `--comment=lc:session=<$LC_HPC_SESSION>`; the
  planner sums what each tag holds (tasks, CPUs, memory; pending included, `squeue -r`) over every account.
  - *Derived default.* The pool is measured: every account's `GrpTRES` ceiling summed (Ada: `cpu=96, mem=360G`
    per account). It is divided by max-min fairness, work-conserving, among the ACTIVE streams -- the tags
    holding tasks now, plus `untagged` for jobs without one (the forge alarms on those). An idle session gets 0
    and its share lends out; two busy sessions meet at equal halves. No registry, no heartbeat: Slurm is the
    source of truth (`hpc.allocation`).
  - *Override.* One expiring record, `hpc-allocation.json` on the forge's records home, read by every submitter:
    `python -m lab_commons.hpc allocate --until 2026-10-18T09:00Z alice=64/240 bob=32/120` (`name=cpus/mem_gb`),
    `allocate --show`, `allocate --clear`. While unexpired it fixes the named sessions' shares; the remainder (the pool less what each named session
    uses of its share, floored at 0) is divided by the same max-min among the unnamed active streams, untagged
    included -- a named session's slack lends out.
    Expired or absent, the derived default stands.
  - Past its share a session plans with room 0 and a throttle of 1 -- new submissions wait; nothing is ever
    cancelled. Only a task past a record's `task_cpus`/`task_mem_gb` is refused. Without `$LC_HPC_SESSION`
    jobs are untagged and uncapped. A leftover per-session machine table is refused by name.
- **Usage is read, never stored.** Account headroom is the quota minus what the account's jobs hold, read from
  `squeue --me`; a grant with room (group memory included, `AssocGrpMemLimit`) is chosen over one without.
- **Paged placement** (user design 2026-10-17, OS memory management over the pool), only with `[hpc.paging]`:
  - *Paging.* A task's size is its pages, the larger of `cpus/page_cpus` and `mem_gb/page_mem_gb`: small (one),
    medium, large (more than `large_pages`). Page-sized tasks keep free memory from shattering into holes.
  - *Movable.* Rerun-safe (declared: `[job] rerun_safe`, forge test parts always) AND a wall within
    `movable_minutes`. Declared, never guessed.
  - *Region.* The emptiest account (most group memory free) is the large-job region; it belongs to no session
    and rotates (`hpc.region.region`). A pending large task (`@@@ pending` in the probe) pins it where it waits.
  - *Placement.* A large job goes only to the region, and never spreads. Small and medium tasks best-fit onto
    the FULLEST account with room (the least group memory free). Only a small movable task may borrow the
    region (`hpc.region.may_place`).
  - *Drain, not kill.* While a large task waits nothing new enters the region, so it empties within one
    movable wall. Running work is never cancelled. The session caps still apply on top.
- Each tick the host publishes its supply, partitions and quota on its forge host card.

## Runs on the cluster

`forge serve` drives two short calls on the login node, one step per tick. They refuse (exit 2) on a box
without `sbatch`.

1. `python -m lab_commons.hpc run submit --sha <40-hex> --scope full|incremental --repo-url <https> [--only ids.txt] [--collect "<paths>"] [--select "<marker expr>"] [--part <need-set>] [--python 3.13]`
   checks the login node's prerequisites, fetches, builds, collects, plans and submits round 0, writes
   `~/ci/runs/<sha>/<part>/state.json` and returns in minutes. `--part` (default `base`) is the need-set it runs; every
   other collected id is handed to its own part. `incremental` needs `--only`; `full` refuses it.
2. `python -m lab_commons.hpc run gather --sha <40-hex> -o <dir> [--wait]`: still running, it prints where the
   run is and exits 3; a finished round is folded and its unfinished ids re-submitted as the next round; once
   nothing is left it writes `<dir>/run-<sha>-<part>-<req>.json.gz` and exits 1 if any id is red, lost or
   missing.

To run ANY entry (not pytest) at a commit, `python -m lab_commons.hpc run build --sha <40-hex> --repo-url <https>
[--artifact tarball]` on a grant's login node builds that commit's ONE artifact file and prints the `[job]` lines
(`sha`, `repo_url`, `artifact`) a job file names; with `entry = "<module>:<function>"` it is submitted with
`submit -c <job.toml>`. A job never checks out the repository (see [Artifacts](#artifacts-one-file-per-sha)).

The cluster run state is a resumable tick (`forgerun`): `claimed -> submitted -> gathered -> published`, kept
per repo + sha + part + scope in `forge-runs/` beside the machine file. Slurm is the truth: jobs named
`run-<sha12>` with no recorded state are orphans, alarmed and never resubmitted.

### What a run reuses

- **Preparation is keyed by its inputs, never by commit** (`lab_commons.hpc.builds`), declared once:
  `[tool.lab_commons.hpc] dependency_inputs`, `source_roots`, `install`, `needs`, `collect`, `outputs`,
  `timeout_s = {incremental = ..., full = ...}` and `native = { inputs = [...], build = "..." }`. A fresh sha
  with unchanged inputs builds nothing. The committed `uv.lock` is an input, so its hash keys the venv.
- Everything lives under `~/ci/` in the account's home: `cache/<owner>-<name>-<hash8>.git` (one bare cache per repository, `origin` its URL, heads fetched with `--prune`), `envs/<key>`, `native/<key>`,
  `trees/<sha>`, `runs/<sha>`, `collect/`, `uv-cache`, `cargo-target`. A day-to-day checkout is never touched.
- **Collection is cached per test file** (`lab_commons.hpc.collect`); only files with no entry are collected.
- **A failed build stops the run** with the tail of `~/ci/trees/<sha>/.lab-ci/build.log`; prerequisites
  missing from the login node's `PATH` are named before anything is fetched.

### How a run is planned and executed

- **The plan is measured.** Each record carries `durations`, `overheads` and `peaks_mb`; the next submit reads
  them back (`lab_commons.compute.learned`), packs whole files into shards inside the `[policy]` window, and sets the
  wall limit and memory from the slowest shard and worst peak times `policy.safety`.
- The array asks for every declared partition that admits its shard (`--partition=shortq,defq`). A task pending
  past `stall_minutes` while a declared partition has a free slot is reported as a STALL with its remedy.
- **Outcomes are streamed**, one JSON line per test phase keyed by pytest's `nodeid`, so a killed shard keeps
  what it reported. Its unfinished ids are re-submitted in halves for up to two more rounds, with doubled memory
  after an out-of-memory kill; only what is still unfinished after that is `lost`.
- The record holds (`platform` is the part's name) `{sha, req, scope, platform, system, env, account, job_ids, cluster, python, prep, plan,
  rounds, outcomes, reasons, handed, durations, overheads, peaks_mb}`. Outcomes: `passed`, `failed`, `error`,
  `skipped`, `xfailed`, `not-covered`, `lost`, `missing`. Only `passed` means passed.

## Parts by need-set

- **One vocabulary, one table**, in the tested repo's `pyproject.toml`, read at the sha
  (`lab_commons.hpc.needsets`):

  ```toml
  [tool.lab_commons.tests]
  resources = ["femm", "jmag", "windows"]                          # markers that name a resource
  produce = ["-m", "lab_commons.dev.verify", "--part", "{part}"]   # the ONE local producer, {part} filled
  ```

  Every resource is equal: a tool, an OS, a host fact. A test that needs one carries its marker (registered in
  `[tool.pytest.ini_options] markers` as usual). A test needing a tool marks the TOOL, never the OS the tool
  runs on -- the OS follows from where the tool exists. A test marks an OS only when it proves that OS's
  behaviour.
- **A test's need-set is its part** (`needsets.need_sets`): the declared markers it carries, named sorted and
  `+`-joined (`femm+windows`), or `base` for none. Every id belongs to exactly one part; parts are independent
  and run in any order, in parallel. Status context `tests/<part>`; the name round-trips (`needsets.needs_of`).
- **A part selects with one `-m`** (`needsets.selecting`): its own resources, and `not` every other declared
  one -- `tests/base` of the table above is `not femm and not jmag and not windows`.
- **Parts are discovered, not listed.** Every run collects the whole suite once plus once per resource and
  records, per id it does not cover, the part it belongs to (`handed`); the posted description says
  `hands=<part>:<n>,...`. `base` is always wanted, and a part handed to is wanted next (`platformparts.derived`).
- **A host claims a part when it HAS its need-set** (`lab_commons.compute.admission.admit`). What a host has is
  measured (`lab_commons.compute.probe`): its OS (a Slurm account is `linux`), and every checked tool
  (`femm`, `jmag`, `matlab`, `node`, `simba`; `lab_commons.compute.presence`) that is FOUND, reads a version at or above
  the FLOOR the serving repo declares once in `[tool.lab_commons.tools]` (`femm = {floor = "5.0", reason =
  "<why>"}`; no pin -- an undeclared tool is present at any version, and the version read is recorded in every
  local run record's `tools`), passed its SMOKE (cached
  6 h, re-run each serve tick when due) and has not failed a real unit (exit 4) here since; any other
  `[capabilities.<name>]` is present as declared. `seats` is its concurrency, the only declaration. A part no live host has the needs of waits
  `no host provides <resource>` in `forge queue`: blocked, never red, never skipped.
- **A part is strict**: PASS only if every covered id is `passed`/`skipped`/`xfailed`; any `failed`/`error` is
  FAIL; any `lost`/`missing` id makes it INCONCLUSIVE and it is not posted.
- A producer other than `verify` calls `platformparts.select(root, sha, part, collect=...)` (``(its ids, every
  other id -> its part)``), runs its ids and writes a record of the same shape. The cluster runs a part with
  `hpc run submit --part <part>`; `forge serve` passes the claimed part.
- **Demand is learned per need-set** (`lab_commons.compute.learned`): a finished run is kept under
  `(producer, need-set)`, the producer `local` for a box part and `slurm` for a cluster part.

## Job files

`python -m lab_commons.hpc {plan,submit,status,gather,retry} -c job.toml` runs a non-test workload described
by a job file (`[job]`, `[cost]`, `[policy]`) over EVERY grant that makes it finish sooner (`lab_commons.hpc.span`).
These verbs reach the login hosts over ssh and are not how a commit's suite runs.

- **The split follows throughput.** Each grant that can take the batch is planned on the whole of it -- its CPU
  headroom, free slots, QOS limits and its home's free inodes (`df -i`, the file-count quota is a resource: a plan
  writing more files than are free is refused) -- and its throughput is the batch's padded seconds over that
  makespan. The items are cut into consecutive slices in proportion, so the slices end about together. The spread
  is kept only when every slice holds at least one `shard_minutes_min` shard and its slowest slice beats the best
  single grant (`plan.allocate`); otherwise one grant takes it all. Nothing is reserved anywhere.
- **The artifact is ensured per grant.** `[job] sha` + `repo_url` run the batch from that commit's artifact (no
  `workdir` beside them): before submitting, each chosen grant gets `run build`'s artifact in its own home, reused
  when it exists. A grant whose build fails is dropped and the batch re-spanned without it. A `workdir` under
  `~/ci/trees/` is refused by name: that tree is a test run's.
- **One results file per run.** A run directory (`~/ci/jobs/<sha>/<name>-<stamp>`, else `<workdir>/.lab-hpc/...`)
  holds the manifest, `job.sh` and `results.jsonl`. Each task appends one line per item and, after the worker
  exits, one `shard` line with its exit code and the tail of its output; the output itself stays in node-local
  `$TMPDIR` (`--output=/dev/null`). A shard is returned by a `shard` line with exit 0; `gather` and `retry` read
  only this file. A run an earlier worker wrote (`results/<shard>.json`) is read through a one-way upgrade.
- **A file budget.** `[policy] file_budget` (default 10) is checked at `gather`: a run directory holding more
  files fails the gather (exit 1, `OVER FILE BUDGET`). An upgraded earlier-layout run is named, not judged.
- **One record.** `<job>.submission.json` holds `placements` -- per grant its targets, item range, run directory,
  job ids, shards and plan -- and `moved`. `status` prints a line per grant, `gather` merges every slice back into
  batch order and names any grant that did not answer. A record without `placements` is refused: submit again.
  `gather -c job.toml -o out.json --wait` polls as `status` does every `[policy] poll_seconds`, prints the status
  line only when it changes (`pending: <why>` while a grant does not answer), and gathers once no shard is queued
  or running. `--wait` belongs to `gather` and `run gather` only.
- **A dead grant's slice moves.** `retry` re-submits each shard with no results file that is not active, on its own
  grant. A grant none of whose login hosts answers meets that rule for every shard, so its whole slice is spanned
  again over the grants still answering and the old placement moves to `moved`.
- **The forge's test runs do not span yet.** `run submit` still builds on one login node and plans each round on
  the grants sharing that home (`run.shares_home`); spreading a round over them is the named follow-up in
  `.claude/memory/2026/10/15/one-job-spans-every-grant.md`.

## Artifacts: one file per sha

A job ships one file, `~/ci/artifacts/<sha>.<suffix>` (`lab_commons.hpc.artifact`), never a checkout; a test run
keeps its tree. The format is declared (`[job] artifact`, `run build --artifact`):

- `tarball` -- a gzip tar of `env/` (the venv), `tree/<path>` for each `source_roots` and `artifact_paths` entry
  (`[tool.lab_commons.hpc] artifact_paths = ["cases"]`), `native/` when declared, and `activate.sh`. Built in a
  scratch directory under the login node's `$TMPDIR` (`git archive`, a fresh venv with `UV_CACHE_DIR` there,
  removed on exit); only a native build stays keyed in `~/ci/native/<key>`. A task unpacks it into node-local
  `$TMPDIR`, sources `activate.sh` and runs in `$ART/tree`. Needs only `tar` on the node.
- `image` -- an Apptainer `.sif` or squashfs, REFUSED by name until the compute nodes are probed:
  `which apptainer singularity squashfuse` and `df -h $TMPDIR` inside `srun`.

Not carried: git submodules (`git archive` omits them) -- declare their data in `artifact_paths` from a
checkout that has them, or keep that job on a test layout. Retention keeps an artifact while a queued or
running job submits from `~/ci/jobs/<sha>`, plus the newest; `artifact-not-live` otherwise. Every forge env build
ends with `uv cache prune --ci`.

## Debugging by hand

A human with VPN access may ssh to the login node and read `squeue --me`, `~/ci/runs/<sha>/<part>/state.json`, the
`forge-runs/` state files and `~/.cache/lab-forge-<repo>.log`. No tool path does this.
