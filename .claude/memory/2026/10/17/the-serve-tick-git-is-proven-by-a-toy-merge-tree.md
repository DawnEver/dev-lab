---
name: the-serve-tick-git-is-proven-by-a-toy-merge-tree
description: Ada's cron PATH resolved /usr/bin/git 2.31.1, so every serve tick's trial merge (git merge-tree --write-tree, git >= 2.38) died on merge-tree's usage line; the grant's `module load git-uoneasy` only reached array tasks. The deploy now proves a serve git on a toy repo (tick PATH, else the grant setup's git, whose dir leads the cron PATH) or refuses naming every git tried
created: 2026-10-17
---
# The serve tick's git is proven by a toy merge-tree (2026-10-17)

- Incident (Ada, user2@login02, after `python -m lab_commons.hpc deploy`): `dev/trialmerge.py` and
  `dev/integrate.py` run `git merge-tree --write-tree` (git >= 2.38). Cron's PATH
  (`~/.local/bin:~/.cargo/bin:/usr/local/bin:/usr/bin:/bin:/opt/slurm/...`) resolved `/usr/bin/git` 2.31.1:
  `usage: git merge-tree <base-tree> <branch1> <branch2>` every tick. The grant's
  `setup = ["module load git-uoneasy/2.42.0-GCCcore-13.2.0", ...]` is prepended to array-task scripts only.
- Fix: a deploy phase `[git]` (`hpc/deploy.py::_serve_git`, after `[declare]`). Candidates in order: the git
  on the tick PATH; the git `bash -lc '<grant setup>; command -v git'` resolves (last stdout line, Lmod noise
  ignored). Each is PROVEN by `deploy_checks.merge_tree_refusal`: init + empty commit + `merge-tree
  --write-tree HEAD HEAD` in a temp dir, accepted only when it prints a tree id -- never by `--version`.
  A setup-loaded git's directory goes FIRST on the cron line's PATH (`deploy_spec.tick_dirs(git=)`), ahead
  of the `/usr/bin` it must shadow. None qualifying: the deploy exits 2 naming every git tried and the
  remedy (a grant `setup` that loads git >= 2.38, or a link in `~/.local/bin`). No degraded tick.
- Why not the repo `needs` list: `needs` is presence by name (`which`); this is a capability floor of the
  serve itself, owed by every repo, so it is the deploy's own phase, like `uv`.
- Not yet redeployed on Ada: re-run the deploy there; the marked cron lines should start
  `PATH=<module git dir>:...`.
- SUPERSEDED same day (the PATH lead only): a module's git does not run outside its module (`libiconv.so.2`);
  the tick now runs inside the grant setup -- `the-serve-tick-runs-inside-the-grant-setup.md`.
