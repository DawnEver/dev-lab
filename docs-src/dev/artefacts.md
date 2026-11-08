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
5. Check it: `rclone lsd hpc-data: --max-depth 1`, then `python -m dev_lab.dev.hpcaccount deploy` (below).

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

- Only declared outputs are packed (`dev_lab.dev.artefactpack.collect`, `pack`). A declared output that
  matched nothing fails the run loudly, naming it. Nothing undeclared is uploaded.
- The output budgets live in the same `[tool.lab_commons.artefacts]` table and are read once before packing:

  ```toml
  expanded_output_max_entries = 1000  # example only; omitted = no selected-footprint budget
  expanded_output_max_bytes = 10485760  # logical selected-file bytes
  member_index_max_members = 1000  # REQUIRED for declared outputs; no default
  member_index_max_bytes = 262144  # the record's whole {archive_sha: index} value, serialized
  member_index_max_path_bytes = 4096  # one member's relative POSIX path, UTF-8 bytes
  ```

  `expanded_output_*` are nonnegative integers; `member_index_*` (and the two `record_max_*` below) positive
  integers; a boolean is never an integer budget. Entries count the unique selected regular files and their
  unique parent directories through the work-tree root (no files: zero); a zero-byte file still costs an entry.
  The budget is checked before any archive or Ref exists. It is a stat snapshot of the selected footprint --
  not live peak usage, compressed bytes, a quota reservation or a runtime limit; `cap_gb` and `threshold_mb`
  keep their own meanings.
- An over-budget or missing `member_index_*` policy ends the run with an error and a named alarm
  (`OutputBudgetRefused`) and is never retried unchanged; a store or network failure is not reclassified and
  keeps its own recovery.
- `pack` returns `PackedOutputs` (`dev_lab.dev.artefactindex`): the archive, its sha256 and bytes, and one
  `MemberFact(path, logical_bytes, sha256)` per member, hashed on the very stream fed to `tar.addfile`. A hard
  link becomes its own regular member. Member paths refuse traversal, backslashes, colons and control
  characters and allow Unicode -- not a promise that every target platform can materialize them.
- `store_outputs` returns `StoredOutputs(ref, members)` and checks the stored Ref's sha256 and bytes against
  the sealed archive; a disagreement is `OutputIntegrityRefused`, its own terminal alarm, not a budget one.
  The run record carries the unchanged four-field Ref in `artefacts` and, beside it, `artefact_indexes`:
  `{archive_sha: {"schema": "lab-commons-members-v1", "members": [...]}}`. The index byte budget measures
  that value with the record's own serializer (`json.dumps(sort_keys=True, ensure_ascii=True)`), not the
  whole record. File-descriptor checks catch ordinary source drift, not an adversary restoring every
  attribute.

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
- The `folder` writer (`dev_lab.dev.artefactfolder`) publishes the archive BEFORE its manifest. A put
  interrupted between them is retried by verifying the existing archive's full sha256 and size before the
  missing manifest is committed; different bytes are never overwritten. An existing manifest is accepted only
  when its whole Ref matches and its archive still verifies. Concurrent identical writers are idempotent;
  conflicting ones are refused; aliases are refused. Not power-loss durable, not a transaction with the run
  record, and not extended to the other backends.
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
- `python -m dev_lab.dev.hpcaccount deploy` runs the same probe for every served repo that declares an rclone store
  and WARNS with this recipe when it fails; it is never a refusal, since most parts declare no large outputs.

</details>

<details>
<summary>Credentials</summary>

- The rclone config is never in a repo, never logged, and must be mode 600 (`check_rclone_config`). No argv
  carries a secret.

</details>

## Reading a record's member index

- `query_members(root, record_path, ref, paths, case_sensitive=...)` (`dev_lab.dev.artefacts`) reads the
  policy once from the trusted repo root BEFORE opening the record and needs all seven budgets:
  `record_max_compressed_bytes`, `record_max_decompressed_bytes`, the three `member_index_max_*` and both
  `expanded_output_max_*`. An omission is `OutputBudgetRefused`, never a default. It reads the record with
  `lab_commons.hpc.records.read_record` (strict JSON, those byte budgets, an optional `expected_sha256` over
  the same compressed buffer; a malformed record stays `RecordRefused`), then `catalogue` and `select_members`.
  No store or archive is touched: the answer is a declaration, not verified contents.
- `catalogue(record, ref, ...)` validates the one requested exact Ref and its sha-keyed index; a record
  without it is UNINDEXED, refused, never an empty catalogue. Other archives and record fields are not
  validated.
- `select_members(members, paths, ...)` revalidates every supplied fact, then selects explicit paths: an empty
  selection costs nothing, otherwise the fresh root, unique parents and files count as entries, each file's
  bytes once. Unknown or duplicate paths and file/directory collisions are refused; `case_sensitive=False`
  also refuses case-fold aliases (not Windows reserved names, Unicode normalization or long paths).

## Verifying an archive against its index

- `verify_newpack_stream` (`dev_lab.dev.artefactscan`) checks an already decompressed stream, writing nothing,
  with every limit an explicit positive integer. It accepts only what `pack` emits -- regular payloads, each
  optionally preceded by ONE local PAX header of `path`, `size` and integer `mtime` -- and every payload must
  match the index's order, path, length and sha256, unselected ones too. A PAX header's size is checked before
  its body is read; checksums, padding, end markers and the zero tail stay inside the scan budget. Links,
  GNU/global extensions, extra members and malformed metadata are refused; there is no legacy fallback.
- `verify_newpack_archive(path, ref, expected, max_compressed_bytes=..., ...)` does it for a local gzip archive
  and its COMPLETE index: aliases and non-regular sources are refused, the compressed length and sha256 are
  authenticated in bounded chunks BEFORE anything is decompressed, the same opened file is rewound and
  decompressed in process, and its identity must hold to the end. Two input passes, not a transport
  protocol; the caller owns the Ref's and index's provenance. A monolithic gzip tar is not randomly
  accessible, so a full verification reads every decoded byte.

## Materializing a selection

- `materialize_newpack_archive(path, ref, complete_expected, explicit_paths, destination_parent, ...)`
  (`dev_lab.dev.artefactrestore`) needs an existing, trusted, non-alias parent and returns a newly claimed
  unique directory under it. It reuses the verifier, not a second extractor: every payload is verified, and
  only selected regular files are opened create-new and written in bounded chunks.
- The expanded budget counts the root, unique parents, selected files and ONE `materialization-complete.json`
  receipt, and the receipt's exact bytes; an empty selection still costs two entries and verifies the whole
  archive. Windows device names, forbidden characters, trailing dots or spaces and a receipt collision are
  refused rather than renamed.
- The receipt (schema `lab-commons-materialized-v1`, the archive Ref, the selected paths) is written LAST,
  after full verification and the final identity checks. A directory without it is incomplete.
- A failure removes only the still-matching files and empty directories in its ownership ledger; a foreign
  replacement survives and the failure says cleanup was incomplete. Not directory-atomic or power-loss
  durable; hostile ancestors, every Unicode alias, permissions/timestamps, legacy archives and resume are
  not handled.

## What is not an artefact

- A report a person or agent writes is a dated `.claude/memory/<yyyy>/<mm>/<dd>/<slug>.md` entry, never a file
  under `output/` (`REPORTS-LIVE-IN-MEMORY`). `output/` holds only what a program can regenerate.
- A file outside every checkout is nobody's artefact: an agent writes into the checkout's
  `output/logs/<yy>/<mm>/<dd>/<kind>/` or `scratch/`, never into a temp, `var` or `src` root -- not even into a
  checkout there, an abandoned old version (user ruling 2026-11-06) -- or loose into the home
  (`WRITES-STAY-IN-THE-TREE`, [refusals](refusals.md#writes-stay-in-the-tree)). `python -m dev_lab.dev.tmpsweep`
  lists those roots; `--apply` ages old temp entries out (a person's command or a scheduled task; hooks only report).
