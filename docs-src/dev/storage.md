# Storage kinds

A checkout's bulky state -- run output, virtual environments, worktrees, caches, build trees -- is a fixed
set of KINDS, resolved by ONE function: `lab_commons.storage.root(kind, repo, tree)`. dev-lab reaches it only
through `dev_lab.dev.storage` (`kind_root`, `output_path`), so a writer, a cleaner and the write guard agree.

- **Unbound** (the default): each kind lives in the checkout (`lab_commons.storage.KINDS`).
- **Bound**: a machine with a small disk declares `[storage.roots]` in its machine file, an absolute root
  per kind with a `{repo}` placeholder (the MAIN checkout's name, shared by its worktrees).
- **Remotes**: the family file declares `[storage.remotes.<name>]` once, no secret; a machine declares
  `reach` and `secrets` (the directory `ops secret place` fills, one `<name>.toml` per remote).

Doors, `python -m dev_lab.dev.storage ...`:

- `where [<kind>...]` -- each kind's root here, bound or default.
- `render [--to P]` -- the reached rclone remotes, family options plus the placed secret, owner-only and
  outside every repo. Nobody hand-edits an rclone config.
- `migrate <kind>` -- move a bound kind's in-tree copy once, leaving a marker; a later in-tree copy is
  refused by name, never read as a fallback.

The write guard (WRITES-STAY-IN-THE-TREE) admits a bound root and nothing else. Junctions are not used: they
hide the real place from the cleaners and the guards, and break when the target drive is absent.

Moved so far: the forge outbox and intent journal, the run cache. The other writers of the output kind, the
venv and worktree layouts and the cleaners move next (task toolchain, D75).
