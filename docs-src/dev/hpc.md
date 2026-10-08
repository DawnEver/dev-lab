# HPC: grants, shared accounts and remote verdicts

- **Two files, two owners.** The JOB file (`-c hpc.toml`, travels with the project) says WHAT runs: `[job]` entry/items/setup/workdir, `[cost]` of one item, `[policy]` for cutting. The MACHINE file (`~/.config/lab-commons/hpc.toml`, or `$LAB_COMMONS_HPC_GRANTS`) says WHERE this box may run: its `workstation` name and one `[[grant]]` per share it holds. Partitions and QOS are cluster facts, so they live on the grant, not the job.

```toml
workstation = "lab-ws-07"            # stable, unique among boxes sharing an account

[[grant]]
account = "user@login.cluster"       # the ssh target; keys stay in ~/.ssh/config
slurm_account = "acct-free"
cpus = 64                            # this box's share of the account's CPU quota
priority = 0                         # optional tie-break
partitions = ["shortq", "defq"]      # optional, in preference order
qos = { devq = "dev" }               # optional
```

- **Many-to-many, refused by name.** A box may hold several grants; an account may be shared by several boxes, each with its own share. A missing file, a duplicate `account` or a non-positive share is refused with the file and the key named. No secrets in the file.
- **Usage is READ, never stored.** Every job carries `--comment=lc:ws=<workstation>`. The one-round-trip probe also runs `squeue -h --me -A <acct> -o "%C %k"` and sums CPUs per tag (an untagged job counts as someone else's). `--me` matters: a university free-tier account carries thousands of other people's jobs that count against nothing of ours.
- **Allocation is pure** (`plan.allocate`). Per grant: `headroom = min(share, quota - CPUs held by OTHER workstations) - CPUs held by this one`; plan on that headroom with the existing planner; take the grant whose plan finishes earliest (tie: higher `priority`, then file order). No headroom anywhere raises naming every account and why. `probe` prints, per grant, the shares known here against the quota and what each tag holds.
- **Verbs.** `python -m lab_commons.hpc {probe,plan,submit,status,gather,retry} -c job.toml`; `submit` records the grant it chose in `<job>.run.json`, so `status`/`gather`/`retry` go back to the same cluster.

## Remote verdict

`python -m lab_commons.hpc verdict --sha <40-hex> --repo-url <https> --install "<cmd>" [--collect "<pytest args>"] [--not-covered "<marker expr>"] [--python 3.13] [--bundle <local repo>] [-c job.toml] -o record.json`

- Everything on the cluster lives under `~/ci/`: `cache.git` (bare, fetched read-only over HTTPS), `bundles/<sha>.bundle` (only when the commit is not on the remote: `git bundle ... --not --remotes`, base64 over the runner's stdin), `trees/<sha>` (a worktree with its OWN `.venv`, built once on the login node and reused), `bin/lab_ci_pytest_item.py` (the item runner, shipped from this checkout so its parser does not depend on the tested project's `lab_commons` pin). A day-to-day `~/<repo>` checkout is never touched.
- Node ids come from `pytest --collect-only -q` in the tree; one item per test file; the planner shards items as usual; each item runs `pytest <ids> -p no:cacheprovider -q --junitxml=<file>` and returns per-id outcomes read from the junit file.
- The record `{sha, platform, cluster, python, plan, outcomes}` is written to `-o`. Outcomes: `passed`, `failed`, `error`, `skipped`, `xfailed`, `not-covered` (selected out by `--not-covered`, e.g. Windows-only vendors), `lost` (its shard died), `missing` (absent from junit). Only `passed` means passed.
- The tested tree's venv must provide `lab_commons.hpc.worker` (any `lab-commons` since the hpc tier); the array task runs `python -m lab_commons.hpc.worker` there.
