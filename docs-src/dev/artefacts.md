# Artefacts

Large results live in ONE shared SharePoint document library, the Teams team "HPC Data". Several HPC accounts,
owned by different people, write to it, each through its OWN rclone remote; every run id carries the account
that wrote it, and each account cleans only its own runs. Workstations never write: they read the library
through the OneDrive client's sync of it. A run's verdict travels as its run record; anything else travels
only if it is DECLARED, and small archives stay on the forge.

## Set up an HPC account (once per account)

On the login host (Ada), with a machine that has a browser beside you:

1. `rclone config` -> `n` (new remote), name `hpc-data`, storage `onedrive`; leave client id and secret blank.
2. At "Use web browser to automatically authenticate?" answer `n`. On the machine with a browser run
   `rclone authorize "onedrive"`, sign in as yourself, and paste the token it prints back into Ada.
3. Choose `sharepoint` ("Sharepoint site name or URL"), give the site of the team "HPC Data", and pick its
   `Documents` library. The remote then reads `drive_type = documentLibrary`.
4. `chmod 600 ~/.config/rclone/rclone.conf` -- it holds your token.
5. Check it: `rclone lsd hpc-data: --max-depth 1`, then `python -m lab_commons.hpc deploy` (below).

## Set up a workstation (read only)

Open the team "HPC Data" in Teams, go to **Files**, and click **Sync**. Then point the machine config at the
synced folder:

```toml
[artefacts]
folder = "~/<the synced HPC Data - Documents folder>"
```

<details>
<summary>Declaring outputs</summary>

```toml
[tool.lab_commons.hpc]
outputs = ["output/fields/*.h5"]       # globs or files, relative to the run's work tree
```

- Only declared outputs are packed (`lab_commons.dev.artefacts.collect`, `pack`). A declared output that matched
  nothing fails the run loudly, naming it. Nothing undeclared is uploaded.

</details>

<details>
<summary>Where an archive goes</summary>

```toml
[tool.lab_commons.artefacts]
backend = "rclone"         # the large store: rclone or folder; absent = forge only
remote = "hpc-data:<repo folder>"
threshold_mb = 100         # at or under: a forge attachment; above: the large store
retain_days = 3            # per writer
cap_gb = 0                 # per writer; 0 = no cap
```

- One interface, three backends (`ArtefactStore`): `forge` (a records-home attachment, up to the forge's
  100 MB limit), `rclone` (any rclone remote) and `folder` (a local path).
- **The manifest entry is the reference**: `{backend, ref, bytes, sha256}` in the run record. Reading refuses
  bytes whose sha256 differs.
- **Write-once**: an object is never rewritten; the same bytes again is the object already landed.
- Every writer names the same remote, `hpc-data`, so one `remote` value serves every account.

</details>

<details>
<summary>Layout and names</summary>

```
<repo>/<yyyy>/<mm>/<dd>/<run-id>.tar.gz
<repo>/<yyyy>/<mm>/<dd>/<run-id>.manifest.json      run-id = <sha12>-<platform>-<account>-<utcstamp>
```

- `<account>` is the cluster account of the claim owner (`lab_commons.hpc.account`), never typed. It must be
  lowercase ASCII letters, digits and `._-`, at most 32 characters, starting and ending in a letter or digit
  (OneDrive is case-insensitive); another account is refused.
- One archive per run, because a synced drive pays per FILE. Keys are checked against OneDrive's forbidden
  characters, trailing dots and spaces, and its path limit (`check_key`).

</details>

<details>
<summary>Retention: each writer cleans its own</summary>

- Every `forge serve` tick on a cluster cleans (`clean`) only the runs carrying its own account, in the forge
  and in the large store: runs in day folders older than `retain_days` go unless a `keep` label on an issue or
  PR pins their sha; then that account's oldest first until its own share is under `cap_gb`; emptied folders
  are removed. Another account's runs are never touched.

</details>

<details>
<summary>No working remote, no claim</summary>

- Each tick a cluster host probes its remote read-only (`rclone lsd <remote>: --max-depth 1`,
  `remote_problem`). When it is missing or unusable, the host claims no part with declared `outputs` (they could
  exceed `threshold_mb`) and its host card states why; parts with no declared outputs are still claimed.
- `python -m lab_commons.hpc deploy` runs the same probe for every served repo that declares an rclone store
  and WARNS with this recipe when it fails; it is never a refusal, since most parts declare no large outputs.

</details>

<details>
<summary>Credentials</summary>

- The rclone config is never in a repo, never logged, and must be mode 600 (`check_rclone_config`). No argv
  carries a secret.

</details>

## What is not an artefact

- A report a person or agent writes is a dated `.claude/memory/<yyyy>/<mm>/<dd>/<slug>.md` entry, never a file
  under `output/` (`REPORTS-LIVE-IN-MEMORY`). `output/` holds only what a program can regenerate.
