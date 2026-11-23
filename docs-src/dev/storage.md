# Storage kinds

A checkout's bulky state -- run output, virtual environments, worktrees, caches, build trees -- is a fixed
set of KINDS, resolved by ONE function: `lab_commons.storage.root(kind, repo, tree)`. dev-lab reaches it only
through `dev_lab.dev.storage` (`kind_root`, `output_path`), so a writer, a cleaner and the write guard agree.

- **Unbound** (the default): each kind lives in the checkout (`lab_commons.storage.KINDS`).
- **Bound**: a machine with a small disk declares `[storage.roots]` in its machine file, an absolute root
  per kind with a `{repo}` placeholder (the MAIN checkout's name, shared by its worktrees).
- **Remotes**: the family file declares `[storage.remotes.<name>]` once, no secret; a machine declares
  `reach` and `secrets` (the directory `ops secret place` fills, one `<name>.toml` per remote).
- **The run store**: the family file's `[storage] runs = "<remote>:<path>"` is where every run's result files
  too large for the forge go. `dev_lab.dev.largeobjects.run_objects(repo)` derives it, proves the reach
  (`storage check`) and returns the store; undeclared it is `None` (an oversize result stays local, `TooLarge`);
  declared but unreached is refused naming `secretplace enter|distribute --remote <name>`. The compute-unit
  runner (`forgeunit`) takes no flag for it; a downstream repo pairs it with `forgeunit.shared_tier(repo)`.

Doors, `python -m dev_lab.dev.storage ...`:

- `where [<kind>...]` -- each kind's root here, bound or default.
- `render [--to P]` -- the reached rclone remotes, family options plus the placed secret, owner-only and
  outside every repo. Nobody hand-edits an rclone config.
- `migrate <kind>` -- move a bound kind's in-tree copy once, leaving a marker; a later in-tree copy is
  refused by name, never read as a fallback.
- `publish [--to P]` -- the bound roots as JSON (`~/.config/lab-commons/storage-roots.json`) for the agent-guard
  engine, which reads no TOML: WORKTREES-STAY-INSIDE admits a worktree under a bound `worktrees` root only
  through it (`admits: bound-worktree-home`). Re-run it after changing `[storage.roots]`.

The write guard (WRITES-STAY-IN-THE-TREE) admits a bound root and nothing else. Junctions are not used: they
hide the real place from the cleaners and the guards, and break when the target drive is absent.

Moved: the forge outbox and intent journal, the run cache, the metrics and walls logs, the supervise journal
and state, every dated log and the pytest base temp (`datedlog.dated_base`), a worktree's outputs going home, and
the worktree home (`worktreeplace.home`: placement, the misplaced-tree detector, the shatree trees, orphan and
retention scans, reclaim). Not moved: the venv layout -- its pointer rule has three twins (Python, the node
resolver, the POSIX shell function) held to one answer, and a bound venv home needs all three to read it
(task toolchain, D75).
