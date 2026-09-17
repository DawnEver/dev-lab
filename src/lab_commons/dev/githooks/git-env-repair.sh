#!/usr/bin/env bash
# SOURCE THIS. Repair an INHERITED, self-contradictory `GIT_CONFIG_*` environment before any git
# call in a hook, and say out loud that it did. It is a FRAGMENT: running it is a no-op, which is
# why `lab_commons.dev.githooks` refuses to run it rather than reporting success for nothing.
#
# WHAT IT IS, MEASURED 2026-08-13 on a Windows box in the consuming family:
#
#   python -c "import os,subprocess; os.environ['GIT_CONFIG_COUNT']='1';
#              os.environ['GIT_CONFIG_KEY_0']='credential.helper';
#              os.environ['GIT_CONFIG_VALUE_0']='';
#              subprocess.run(['git','rev-parse','--show-toplevel'])"
#   -> VALUE_0=[UNSET]
#      error: missing config value GIT_CONFIG_VALUE_0
#      fatal: unable to parse command-line config      (exit 128)
#
# ON WINDOWS AN ENVIRONMENT VARIABLE CANNOT HOLD THE EMPTY STRING. `os.environ[k] = ''` reaches
# `SetEnvironmentVariableW(k, "")`, which DELETES the variable. So a caller that clears
# `credential.helper` the documented way -- `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=credential.helper`,
# `GIT_CONFIG_VALUE_0=''` -- and installs it into its OWN process environment rather than passing it
# as a subprocess `env=` mapping ends up exporting a COUNT and a KEY with no VALUE. Every git command
# any descendant runs then dies at 128 before doing anything, including the first git call in
# `with-venv.sh`. What that looked like was the WRAPPED TOOL failing: a type checker "failed" on
# every push and was never invoked.
#
# Passing the triple as `env=` survives the same chain intact -- measured, python -> git push ->
# pre-commit -> bash -> git, `VALUE_0=[]`, rc 0. So this is a defect in whoever exports it, NOT in
# git and not in pre-commit, and it cannot be fixed from inside a hook.
#
# WHAT A HOOK CAN DO is refuse to be judged by it. An incomplete set is not a configuration with a
# missing piece -- git rejects it wholesale, so there is nothing to preserve. Dropping it restores
# exactly the behaviour of a process that never set it, and the notice names what was dropped so the
# repair can never be mistaken for "the environment was fine".
#
# A COMPLETE SET IS LEFT ALONE, and that half is as load-bearing as the repair: a caller that
# deliberately passes config through the environment must reach git with it intact.
_repair_git_config_env() {
  local count="${GIT_CONFIG_COUNT-}"
  [ -n "${count}" ] || return 0
  case "${count}" in *[!0-9]*) ;; *) : ;; esac

  local i=0 missing=''
  while [ "${i}" -lt "${count}" ] 2>/dev/null; do
    # `${!name+set}` distinguishes UNSET from EMPTY -- the whole distinction this repairs.
    local key="GIT_CONFIG_KEY_${i}" value="GIT_CONFIG_VALUE_${i}"
    [ -n "${!key+set}" ] || missing="${missing} ${key}"
    [ -n "${!value+set}" ] || missing="${missing} ${value}"
    i=$((i + 1))
  done
  [ -n "${missing}" ] || return 0

  echo "[git-env] DROPPING an incomplete GIT_CONFIG_* set inherited from the calling process." >&2
  echo "[git-env]   GIT_CONFIG_COUNT=${count}, but these are UNSET:${missing}" >&2
  echo "[git-env]   git rejects the whole set with 'missing config value ...' (exit 128), so every" >&2
  echo "[git-env]   git call in this hook would fail before running anything. On Windows an env var" >&2
  echo "[git-env]   cannot hold ''; a caller clearing credential.helper via os.environ loses the" >&2
  echo "[git-env]   VALUE and keeps the COUNT. Pass the triple as a subprocess env= mapping instead." >&2

  i=0
  while [ "${i}" -lt "${count}" ] 2>/dev/null; do
    unset "GIT_CONFIG_KEY_${i}" "GIT_CONFIG_VALUE_${i}"
    i=$((i + 1))
  done
  unset GIT_CONFIG_COUNT
}

_repair_git_config_env
