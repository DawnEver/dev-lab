# Submitting research from a workstation

A session on any workstation submits its own non-test workloads to a Slurm cluster. It needs no forge role:
serving the forge ([Adding a forge workstation](./adding-a-workstation.md)) and submitting research are
independent. The mechanisms are stated once in [HPC clusters](./hpc.md); this page is the order to do them in.

## Once per workstation (a person at the machine)

1. **Reach the login hosts.** Be on the network the cluster requires (its VPN, if any), and hold an ssh key
   for each account you are granted. Check with `ssh -o BatchMode=yes <user>@<login host> true`. A prompt
   means the key is not loaded; this step cannot be automated.
2. **Declare the grants.** In `~/.config/lab-commons/config.toml`, add one `[[hpc.grant]]` per account you
   may use: `user`, `hosts`, `slurm_account`, and `partitions` where it has them
   ([Grants](./hpc.md#grants-the-machine-file)). Never put a secret in this file.
3. **Have the tools.** You need a checkout of the repository whose code the job runs, with its own `.venv`
   (`<venv python> -m dev_lab.dev.dep --bootstrap <checkout>`), and lab-commons on that venv.

## Each time a session submits

1. **Name the session.** Set `LC_HPC_SESSION=<session>`. Every job then carries its tag, and the pool's
   shares are computed per tag ([sessions](./hpc.md#grants-the-machine-file)). An untagged job is uncapped
   and raises a forge alarm.
2. **Build the commit once per grant.** `python -m lab_commons.hpc run build --sha <40-hex> --repo-url <https>`
   on a grant's login node prints the `[job]` lines (`sha`, `repo_url`, `artifact`). The commit must be pushed:
   a job never checks out the repository ([Artifacts](./hpc.md#artifacts-one-file-per-sha)).
3. **Describe the workload.** Write a job file (`[job]` with `entry = "<module>:<function>"`, `[cost]` and
   `[policy]`), as described in [Job files](./hpc.md#job-files).
4. **Run it.** `python -m lab_commons.hpc plan -c job.toml` shows the split; then use `submit`, `status`,
   and `gather -c job.toml -o out.json --wait`. `retry` moves the slice of a grant that stopped answering.

## Which account takes the work

The account a job lands on follows the cluster's placement rules ([paged placement](./hpc.md#grants-the-machine-file)).
A research job never lands on an account that produces the forge's verify parts, unless you opt in with
`allocate --borrow research->verify --until <iso>` ([the rule and the opt-in](./hpc.md#grants-the-machine-file)).

## When it does not work

- **`ssh` prompts or is refused:** step 1 above. The key or the network is missing.
- **A grant is refused by key name:** step 2. The machine file names the missing or retired key.
- **`run build` fails:** the commit is not pushed, or its install does not build on the login node. The error
  names which.
- **Jobs stay pending:** read `status`. A session past its share waits by design
  ([sessions](./hpc.md#grants-the-machine-file)); `python -m dev_lab.dev.hpchost allocate --show` prints any
  override in force.
