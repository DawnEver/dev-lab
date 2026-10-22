---
name: the-serve-tick-runs-inside-the-grant-setup
description: A module's git does not run outside its module (Ada 2026-10-17, libiconv.so.2), so putting its directory on the cron PATH cannot work. Every cron tick now runs `bash -lc '<tick environment>; cd ... && flock ... tick'` where the tick environment is cron's PATH then the grant setup, and the deploy proves git inside that same environment
created: 2026-10-17
---
# The serve tick runs inside the grant setup (2026-10-17)

- Incident (Ada ezztz@hpclogin02, the redeploy log of 2026-10-17, line 226 (evidence no longer available)): lane/serve-git (959f59f)
  found the EasyBuild git 2.42.0 (GCCcore-13.2.0) under the cluster software tree via
  `bash -lc '<setup>; command -v git'`, but run outside the module environment it fails with
  `error while loading shared libraries: libiconv.so.2`. The deploy refused, the old cron lines stayed, and
  every tick's trial merge kept failing on merge-tree's usage line.
- Cause: two environment definitions -- array tasks ran the grant setup, the cron tick got a PATH entry.
  A module is an environment (LD_LIBRARY_PATH and more), not a directory.
- Fix (one environment definition): `deploy_spec.tick_environment(home, slurm, setup)` =
  `PATH=<tick_dirs>; <setup lines>`. `tick_command` prefixes it, and with a setup wraps the whole tick in
  ONE `bash -lc <shlex-quoted>` (`module` is a login-shell function); the log redirect stays outside. The
  deploy's `[git]` phase proves `git` via `[*sh, '<tick environment>; exec git "$@"', 'git', ...]` -- the
  very prefix the cron line runs -- and on success hands the setup to `[cron]` and `[tick]`. The PATH-prepend
  `git=` mechanism and `tick_dirs(git=)` are gone; no candidate list, no fallback.
- Without a grant setup the tick line is unchanged (`PATH=...; cd ... && flock ...`), so a host whose cron
  git qualifies sees no diff.
- Quoting: setup lines are this account's own machine-file shell (by design), quoted once as a whole into
  `bash -lc`; pinned by `tests/test_hpc_deploy.py::test_a_setup_with_spaces_semicolons_and_quotes_reaches_bash_verbatim`.
- Supersedes the PATH-lead half of `the-serve-tick-git-is-proven-by-a-toy-merge-tree.md`; the toy
  merge-tree proof itself stands. Not redeployed: re-run the deploy on Ada; the marked lines should read
  `*/5 * * * * bash -lc 'PATH=...; module load git-uoneasy/...; cd ... && flock -n ... tick <repo>' >> ...`.
