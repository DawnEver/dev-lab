# HPC clusters

A Slurm cluster is one more `forge serve` host. Its login node pulls work from the forge over HTTPS, submits a
commit's suite as a Slurm array, gathers the record and posts the `linux` part; nothing reaches it inbound.
To serve a cluster account, store your forge token there and paste the one deploy line below. To see what a
cluster is doing, run `forge queue` from anywhere; ssh is only a human's debugging door.

## Deploy: one line per account

On the login host you chose, store your own forge token once (`git config --global credential.helper store`,
`chmod 600 ~/.git-credentials`, then `python -m lab_commons.dev.forge auth login`), then paste:

```
F=https://<forge>/<org>; D=~/src/lab-commons; { [ -d $D/.git ] || git clone -q -b integrate/main $F/lab-commons.git $D; } && git -C $D pull -q --ff-only && cd $D && PYTHONPATH=src ~/.local/bin/uv run --no-project --python 3.13 python -m lab_commons.hpc deploy --host <login host> --repo lab-commons=$F/lab-commons.git@integrate/main --repo <repo>=$F/<repo>.git@integrate/main
```

- **The same line is the upgrade.** The first run stores the declaration (`[deploy]` in the account's machine
  file: host, root, python, served repos); later runs read it, and flags that disagree with it are refused.
- **What it does** (`lab_commons.hpc.deploy`): refuses off the declared host; checks every served repo with
  `git ls-remote` before changing anything; clones or fast-forwards each checkout; builds each `.venv` with the
  repo's own `[tool.lab_commons.hpc] install` and `native` build on a uv-managed CPython (skipped while its
  inputs are unchanged); installs `cmake` through `uv tool` when a repo needs it and the host lacks it;
  replaces its own marked crontab lines; runs one tick of each repo and prints it.
- `--dry-run` prints every action; `--remove` deletes the marked crontab lines only.
- **The crontab line**, per repo, every 5 minutes:
  `cd ~/src/<repo> && flock -n ~/.cache/lab-forge-<repo>.lock .venv/bin/python -m lab_commons.dev.forge serve --mode integrate >> ~/.cache/lab-forge-<repo>.log 2>&1 # lab-commons-deploy:<repo>`.
  Route its alarm lines, or enable `[alerts]` in the machine file.
- **One login host per account.** Cron is per host and `flock` on a shared filesystem does not lock across
  hosts. A second host finding a live run owned by another host of its account leaves it alone until that
  owner's lease lapses on the forge's clock.
- **Identity is read, never typed**: the claim names `<cluster>/<account>` from Slurm's `ClusterName` and
  `id -un` (`lab_commons.hpc.account`).
- `git`, `uv` and `cargo` must be on the cron `PATH`; `module load` lines go in `~/.bashrc`.

## Grants: the machine file

The account's `[hpc]` table in `~/.config/lab-commons/config.toml` (`$LAB_COMMONS_CONFIG` overrides the path)
holds one `[[hpc.grant]]` per Slurm share. Partitions, QOS and compute-node set-up are cluster facts, so they
live on the grant.

```toml
[[hpc.grant]]
user = "me"                          # equal to the login on that cluster
hosts = ["login2.cluster", "login1.cluster"]
slurm_account = "acct-free"
cpus = 64                            # this account's share of the CPU quota
partitions = ["shortq", "defq"]      # optional, in preference order
qos = { devq = "dev" }               # optional
setup = ["module load git/2.42.0"]   # optional, prepended to every array task
```

- A missing table, a duplicate account, an empty `hosts` or a non-positive share is refused with the key named.
  No secrets in the file.
- **Usage is read, never stored.** Every job carries `--comment=lc:ws=<host>`; headroom is the share minus what
  the account's jobs hold, read from `squeue --me`.
- Each tick the host publishes its headroom, partitions and quota on its forge host card.

## Runs on the cluster

`forge serve` drives two short calls on the login node, one step per tick. They refuse (exit 2) on a box
without `sbatch`.

1. `python -m lab_commons.hpc run submit --sha <40-hex> --scope full|incremental --repo-url <https> [--only ids.txt] [--collect "<paths>"] [--select "<marker expr>"] [--python 3.13]`
   checks the login node's prerequisites, fetches, builds, collects, plans and submits round 0, writes
   `~/ci/runs/<sha>/state.json` and returns in minutes. `incremental` needs `--only`; `full` refuses it.
2. `python -m lab_commons.hpc run gather --sha <40-hex> -o <dir> [--wait]`: still running, it prints where the
   run is and exits 3; a finished round is folded and its unfinished ids re-submitted as the next round; once
   nothing is left it writes `<dir>/run-<sha>-<platform>-<req>.json.gz` and exits 1 if any id is red, lost or
   missing.

The cluster run state is a resumable tick (`forgerun`): `claimed -> submitted -> gathered -> published`, kept
per repo + sha + platform + scope in `forge-runs/` beside the machine file. Slurm is the truth: jobs named
`run-<sha12>` with no recorded state are orphans, alarmed and never resubmitted.

### What a run reuses

- **Preparation is keyed by its inputs, never by commit** (`lab_commons.hpc.builds`), declared once:
  `[tool.lab_commons.hpc] dependency_inputs`, `source_roots`, `install`, `needs`, `collect`, `outputs`,
  `timeout_s = {incremental = ..., full = ...}` and `native = { inputs = [...], build = "..." }`. A fresh sha
  with unchanged inputs builds nothing. A floating git dependency adds its remote tip to the key.
- Everything lives under `~/ci/` in the account's home: `cache.git`, `envs/<key>`, `native/<key>`,
  `trees/<sha>`, `runs/<sha>`, `collect/`, `uv-cache`, `cargo-target`. A day-to-day checkout is never touched.
- **Collection is cached per test file** (`lab_commons.hpc.collect`); only files with no entry are collected.
- **A failed build stops the run** with the tail of `~/ci/trees/<sha>/.lab-ci/build.log`; prerequisites
  missing from the login node's `PATH` are named before anything is fetched.

### How a run is planned and executed

- **The plan is measured.** Each record carries `durations`, `overheads` and `peaks_mb`; the next submit reads
  them back (`lab_commons.hpc.learned`), packs whole files into shards inside the `[policy]` window, and sets the
  wall limit and memory from the slowest shard and worst peak times `policy.safety`.
- The array asks for every declared partition that admits its shard (`--partition=shortq,defq`). A task pending
  past `stall_minutes` while a declared partition has a free slot is reported as a STALL with its remedy.
- **Outcomes are streamed**, one JSON line per test phase keyed by pytest's `nodeid`, so a killed shard keeps
  what it reported. Its unfinished ids are re-submitted in halves for up to two more rounds, with doubled memory
  after an out-of-memory kill; only what is still unfinished after that is `lost`.
- The record holds `{sha, req, scope, platform, system, env, account, job_ids, cluster, python, prep, plan,
  rounds, outcomes, reasons, handed, durations, overheads, peaks_mb}`. Outcomes: `passed`, `failed`, `error`,
  `skipped`, `xfailed`, `not-covered`, `lost`, `missing`. Only `passed` means passed.

## Platform parts

- **One table**, per marker, in the tested repo's `pyproject.toml`, read at the sha (`lab_commons.hpc.platforms`):
  `[tool.lab_commons.platforms] femm = ["windows"]`. An unlisted marker runs everywhere. A host requirement is a
  marker too: `dev_checkout = ["windows"]` sends a test that needs a developer checkout to a part that runs in one.
- **Every id is assigned to exactly one part**: the first of `linux`, `windows`, `macos` that can run it
  (`platforms.assign`). Parts are independent and can run in any order, in parallel.
- **A part is strict**: PASS only if every covered id is `passed`/`skipped`/`xfailed`; any `failed`/`error` is
  FAIL; any `lost`/`missing` id makes it INCONCLUSIVE and it is not posted.
- A non-cluster part calls `platformparts.select(root, sha, platform, collect=...)`, runs its assigned ids and
  records what it handed to other platforms. A consumer exposes it as its runner's `--platform <name>`.

## Job files

`python -m lab_commons.hpc {plan,submit,status,gather,retry} -c job.toml` runs a non-test workload described
by a job file (`[job]`, `[cost]`, `[policy]`) on the grant whose plan finishes earliest. `submit` records the
grant it chose in `<job>.submission.json`, so the other verbs return to the same cluster. These verbs reach the
login host over ssh and are not how a commit's suite runs.

## Debugging by hand

A human with VPN access may ssh to the login node and read `squeue --me`, `~/ci/runs/<sha>/state.json`, the
`forge-runs/` state files and `~/.cache/lab-forge-<repo>.log`. No tool path does this.
