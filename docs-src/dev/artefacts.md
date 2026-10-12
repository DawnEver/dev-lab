# Artefacts

A run's verdict travels as its run record; anything else a run produces travels only if it is DECLARED. List the
files a part must keep under `[tool.lab_commons.hpc] outputs`; the producer packs them into one archive per run
and stores it behind the record's manifest. Nothing undeclared is uploaded, and archives expire after three
days unless a `keep` label pins their sha.

## Declaring outputs

```toml
[tool.lab_commons.hpc]
outputs = ["output/fields/*.h5"]       # globs or files, relative to the run's work tree
```

- Only declared outputs are packed (`lab_commons.dev.artefacts.collect`, `pack`). A declared output that matched
  nothing fails the run loudly, naming it.

## Where an archive goes

```toml
[tool.lab_commons.artefacts]
backend = "rclone"         # the large store: rclone or folder; absent = forge only
remote = "<remote>:<path>"
threshold_mb = 100         # at or under: a forge attachment; above: the large store
retain_days = 3
cap_gb = 0                 # 0 = no cap
```

- One interface, three backends (`ArtefactStore`): `forge` (a records-home attachment, up to the forge's
  100 MB limit), `rclone` (any rclone remote) and `folder` (a local path).
- **The manifest entry is the reference**: `{backend, ref, bytes, sha256}` in the run record. Reading refuses
  bytes whose sha256 differs.
- **Write-once**: an object is never rewritten; the same bytes again is the object already landed.
- The reader side maps the store to a local path in the machine config (`[artefacts] folder`): a synced mirror,
  read, never written.

## Layout

```
<repo>/<yyyy>/<mm>/<dd>/<run-id>.tar.zst
<repo>/<yyyy>/<mm>/<dd>/<run-id>.manifest.json        run-id = <sha12>-<platform>-<utcstamp>
```

- One archive per run, because a synced cloud drive pays per FILE. Names are short ASCII and checked against
  OneDrive's forbidden characters, trailing dots and spaces, and its path limit (`check_key`).

## Retention

- The single writer cleans (`clean`): whole runs in day folders older than `retain_days` go, unless a `keep`
  label on an issue or PR pins their sha; then oldest first until the store is under `cap_gb`; emptied folders
  are removed.

## Credentials

- The rclone config is never in a repo, never logged, and must be mode 600 (`check_rclone_config`). No argv
  carries a secret.

## What is not an artefact

- A report a person or agent writes is a dated `.claude/memory/<yyyy>/<mm>/<dd>/<slug>.md` entry, never a file
  under `output/` (`REPORTS-LIVE-IN-MEMORY`). `output/` holds only what a program can regenerate.
