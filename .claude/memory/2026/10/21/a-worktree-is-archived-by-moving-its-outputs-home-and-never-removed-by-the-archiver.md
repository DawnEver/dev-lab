---
name: a-worktree-is-archived-by-moving-its-outputs-home-and-never-removed-by-the-archiver
description: "dev_lab.dev.worktree_archive behind `worktrees --archive NAME`: refuses an occupied tree or another volume, saves HEAD/dirty.patch/untracked, MOVES declared outputs to the same path in main (identical skipped, differing -> <file>.<worktree>, no venv), and removes nothing."
created: 2026-10-21
accessed: 2026-10-21
tags: [worktree, output, archive, liverun, incident]
metadata:
  type: project
---

# A worktree is archived by moving its outputs home, and the archiver never removes it

## Incidents (a consumer repo)

- 2026-10-04 and again later: a cleanup chained the move and `git worktree remove` with `;`; the move failed,
  the removal ran, run archives were deleted.
- 2026-10-18: removals moved whole `output/` trees, `.venv` copies included, into one archive (845 GB).
- 2026-10-21: a COPY of ~90 GB of outputs nearly filled the volume. A consumer-local archiver was written
  and never landed; it stalled on a permissions.allow regeneration for its new script.

## Mechanism

- `python -m dev_lab.dev.worktrees --archive NAME` -> `dev_lab.dev.worktree_archive.archive`.
  It is a FLAG of an existing door because every adopting repo already renders
  `Bash(.venv/*/python* -m dev_lab.dev.worktrees *)`: a consumer bumps lab-commons and edits no permission.
- Order: refuse (unknown name, main itself, any `liverun.occupants` -- cwd in, executable in, or reading the
  tree, so another session's node process counts -- or another volume) -> save `HEAD.txt`, `dirty.patch`,
  `untracked/` under `archive-to/<yyyymmdd>/<name>/` -> move each file under `archive-outputs` to the same
  relative path in main with `Path.replace`.
- Same-named file: identical bytes skipped (main untouched); differing -> `<file>.<worktree>`; both names taken
  by different bytes -> the file stays and the tree is NOT safe.
- Data: `[tool.lab_commons.worktrees] archive-outputs` (default `["output/logs"]`), `archive-to` (default
  `output/worktree-archive`).
- Removal stays explicit: the report names `git worktree remove --force <name>` as a separate step.

Tests: `tests/test_dev_worktree_archive.py` (planted worktrees: identical, differing, renamed-not-copied by
inode, live refused, a session's cwd refused, venv excluded, patch + untracked, declared outputs, other volume,
the door's output).
