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
  and then the repo at their deployed refs, rebuilds the repo's venv where its inputs or the kit's HEAD moved
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
  uv-managed CPython (skipped while its inputs are unchanged); installs the served lab-commons checkout over
  the sha each other repo pins (`uv pip install --no-config`, run outside the project so its sources cannot
  put the pin back; keyed by the lab-commons HEAD, so the next deploy after a lab-commons update reinstalls
  it); replaces its own marked crontab lines; runs one tick of each repo and prints it.
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

[hpc.session.wdg-design]             # one per session; $LC_HPC_SESSION picks this process's
tasks = 2                            # pending + running tasks, across EVERY account
cpus = 128
mem_gb = 600
task_cpus = 64                       # optional per-task ceilings
task_mem_gb = 300
```

- A missing table, a duplicate account or an empty `hosts` is refused with the key named; a `cpus` share is retired
  and refused by name: admission fits each job against what the account has free now ([admission](forge.md#admission)).
  No secrets in the file.
- **The accounts are one pool; a session has the cap.** No session owns an account. Every job carries
  `--comment=lc:session=<$LC_HPC_SESSION>`; the planner sums what that tag holds (tasks, CPUs, memory; pending
  included, `squeue -r`) over every account and, past `[hpc.session.<name>]`, plans with room 0 and a throttle
  of 1 -- the job waits, it is never refused. Only a task past `task_cpus`/`task_mem_gb` is refused. Without
  `$LC_HPC_SESSION` jobs are untagged and uncapped; a name with no table is refused.
- **Usage is read, never stored.** Account headroom is the quota minus what the account's jobs hold, read from
  `squeue --me`; a grant with room (group memory included, `AssocGrpMemLimit`) is chosen over one without.
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

To run ANY entry (not pytest) at a commit, `python -m lab_commons.hpc run build --sha <40-hex> --repo-url <https>`
on each grant's login node does step 1's fetch and build alone -- no collection, no submission, no state -- and
prints the job-file lines that reuse that tree and env: `workdir = "~/ci/trees/<sha>"`, `setup = [". .lab-ci/env.sh"]`.
A job file with them and `entry = "<module>:<function>"` is then submitted with `submit -c <job.toml>`.

The cluster run state is a resumable tick (`forgerun`): `claimed -> submitted -> gathered -> published`, kept
per repo + sha + part + scope in `forge-runs/` beside the machine file. Slurm is the truth: jobs named
`run-<sha12>` with no recorded state are orphans, alarmed and never resubmitted.

### What a run reuses

- **Preparation is keyed by its inputs, never by commit** (`lab_commons.hpc.builds`), declared once:
  `[tool.lab_commons.hpc] dependency_inputs`, `source_roots`, `install`, `needs`, `collect`, `outputs`,
  `timeout_s = {incremental = ..., full = ...}` and `native = { inputs = [...], build = "..." }`. A fresh sha
  with unchanged inputs builds nothing. The committed `uv.lock` is the one dependency input (D8); no remote is asked.
- Everything lives under `~/ci/` in the account's home: `cache.git`, `envs/<key>`, `native/<key>`,
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
  (`femm`, `jmag`, `matlab`, `node`, `simba`; `lab_commons.compute.presence`) that is FOUND, reads the version
  the serving repo declares once in `[tool.lab_commons.tools]` (`femm = "<version>"`), passed its SMOKE (cached
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
- **The tree is ensured per grant.** `[job] sha` + `repo_url` run the batch in `~/ci/trees/<sha>` with `.lab-ci/env.sh`
  sourced (no `workdir` beside them): before submitting, each chosen grant gets `run build`'s fetch and build in its
  own home, the env reused by its key. A grant whose build fails is dropped and the batch re-spanned without it.
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

## Debugging by hand

A human with VPN access may ssh to the login node and read `squeue --me`, `~/ci/runs/<sha>/<part>/state.json`, the
`forge-runs/` state files and `~/.cache/lab-forge-<repo>.log`. No tool path does this.
