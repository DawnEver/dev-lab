#!/usr/bin/env bash
# Refuse a push that would put an UNDECLARED branch on origin. A HOOK, wired as a pre-commit
# `pre-push` entry:
#
#   python -m lab_commons.dev.githooks branchset-push
#
# THE DECISION IS NOT MADE HERE. It is `lab_commons.dev.branchset_push`, which reads the declared
# branch set out of the pushed checkout's `pyproject.toml` with the same reader the census and the
# famtests use -- one rule, one implementation, no second copy of "which branches are declared" for
# a bash script to drift from. This file exists because a shipped hook is a file in this directory
# (`SCRIPTS` is derived from the directory) and because reading git's refspec stdin is what bash is
# here for.
#
# WHICH INTERPRETER, AND WHY IT IS NOT GUESSED. The check must run where `lab_commons` is importable,
# and the only process that KNOWS which interpreter that is is the dispatcher that started this file:
# `python -m lab_commons.dev.githooks branchset-push` was itself run by the consumer's venv, and it
# exports that interpreter as LAB_PYTHON. Resolving one here instead would be a second opinion about
# the environment -- and a hook that ran under a bare `python` would fail to import the package and
# report it as a policy refusal, which is the misattribution `with-venv.sh` and `git-env-repair.sh`
# were each written about.
#
# THE FALLBACK REFUSES RATHER THAN CHECKS NOTHING. With LAB_PYTHON unset (a caller that reached this
# file without the dispatcher) an interpreter is looked for on PATH, and if none of them can import
# the module the hook exits 2 -- the same verdict as "no branch set declared" -- because a push that
# passed while nothing was judged is the exact defect this hook exists to close.
#
# NO ARGUMENT CHANGES THE VERDICT. This script forwards nothing that could relax the check, and the
# module behind it has no switch: the way to push a new long-lived branch is to DECLARE it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=git-env-repair.sh
. "${HERE}/git-env-repair.sh"

_pick() {
  local candidate
  for candidate in "$@"; do
    [ -n "${candidate}" ] || continue
    if "${candidate}" -c 'import lab_commons.dev.branchset_push' >/dev/null 2>&1; then
      printf '%s' "${candidate}"
      return 0
    fi
  done
  return 1
}

PYTHON="${LAB_PYTHON-}"
if [ -n "${PYTHON}" ] && ! "${PYTHON}" -c 'import lab_commons.dev.branchset_push' >/dev/null 2>&1; then
  echo "[branchset-push] MISCONFIGURED -- LAB_PYTHON names ${PYTHON}, which cannot import" >&2
  echo "[branchset-push]   lab_commons.dev.branchset_push. Run this hook through its dispatcher:" >&2
  echo "[branchset-push]   python -m lab_commons.dev.githooks branchset-push" >&2
  exit 2
fi
if [ -z "${PYTHON}" ]; then
  PYTHON="$(_pick python python3 python.exe || true)"
fi
if [ -z "${PYTHON}" ]; then
  echo "[branchset-push] REFUSED -- no interpreter here can import lab_commons.dev.branchset_push," >&2
  echo "[branchset-push]   so this hook judged nothing. Wire it as" >&2
  echo "[branchset-push]   'python -m lab_commons.dev.githooks branchset-push' so it inherits the" >&2
  echo "[branchset-push]   consumer's own interpreter." >&2
  exit 2
fi

exec "${PYTHON}" -m lab_commons.dev.branchset_push "$@"
