#!/usr/bin/env bash
# Resolve an interpreter -- THIS checkout's if it has one, MAIN's otherwise -- and exec through it.
# A WRAPPER rather than a hook: it takes the command to run as its arguments.
#
#   python -m lab_commons.dev.githooks with-venv pytest -q
#   python -m lab_commons.dev.githooks with-venv scripts/some_tool.py --flag
#
# A WORKTREE MAY HAVE ITS OWN `.venv`, and when it does that venv wins. A lane's own environment is
# the isolated case: a dependency change belongs to the lane instead of being a change to everyone's
# environment, and `PYTHONPATH` juggling stops being necessary because the lane's own editable
# install already points at the lane's own source.
#
# BORROWING MAIN'S IS THE FALLBACK, not the rule -- and the hazard it carries is why the order
# matters: `uv run` in a venv-less worktree silently builds a SEPARATE base-only venv, with none of
# the compiled extensions the checkout needs, while resolving the tools themselves from PATH. That
# tests the wrong code with the wrong tools and reports green. Preferring a REAL lane venv when one
# exists removes the motive for that mistake.
#
# NO INTERPRETER PATH IS HARD-CODED beyond the two standard layouts, and both are tried on every
# platform rather than switched on `uname`: a Windows venv is `Scripts/python.exe`, a macOS/Linux one
# is `bin/python`, and this family runs on both.
#
# A pre-push hook runs from whichever checkout is being pushed -- main or any worktree -- so MAIN's
# absolute path cannot be hardcoded either. Resolve it from git itself: `--git-common-dir` always
# points at MAIN's `.git`, one level under MAIN's root, however deep the worktree is nested.
set -euo pipefail

# BEFORE THE FIRST GIT CALL, and that ordering is the whole point: an inherited incomplete
# `GIT_CONFIG_*` set makes the very next line exit 128 with `missing config value GIT_CONFIG_VALUE_0`,
# which under `set -e` kills this script and is reported as the WRAPPED TOOL failing. MEASURED
# 2026-08-13: a type checker "failed" that way on every push, and was never invoked.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=git-env-repair.sh
. "${HERE}/git-env-repair.sh"

THIS_ROOT="$(git rev-parse --show-toplevel)"
MAIN_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"

# AN INTERPRETER THAT EXISTS IS NOT AN ENVIRONMENT THAT WORKS, and the difference is invisible
# exactly where it hurts. MEASURED 2026-08-15: a worktree carried a `.venv` holding three files --
# `_virtualenv.pth`, `_virtualenv.py`, `__pycache__` -- and no distributions at all. A stub like that
# is what `virtualenv` leaves when a creation is interrupted, or what a tool makes to hold a path.
# `-x` on its `python.exe` says yes, so it won the preference over MAIN's populated venv and every
# hook that ran through it died with `No module named ...`.
#
# That reads as the WRAPPED TOOL being broken -- the same misattribution `git-env-repair.sh` was
# written about, arriving by a second route. So the probe asks what the caller actually needs: a venv
# with something INSTALLED in it. One `*.dist-info` is enough to tell a real environment from a
# placeholder, and it costs a glob.
#
# AND "HAS SOMETHING INSTALLED" IS NOT "HAS WHAT THE CALLER ASKED FOR" -- the same gap one layer up,
# measured 2026-09-14 in another worktree. That lane holds a REAL venv, dist-info files and all, with
# no linter in it: the distribution probe says yes, the lane venv wins the preference, and every
# commit there dies with `No module named ruff` while MAIN's populated venv sits one fallback away.
# The message names the tool, so it reads as the tool being broken -- the third arrival of the
# misattribution this file's own comments were written about.
#
# So the probe asks the caller's OWN question. `_can_run` imports the module that is about to be
# executed; a venv that cannot provide it is not a candidate FOR THIS CALL, whatever else it holds.
# A lane venv that CAN still wins, so the isolation stays intact -- the preference only yields where
# it would otherwise fail outright.
_has_distributions() {
  for _sp in "$1"/lib/python*/site-packages "$1"/Lib/site-packages; do
    for _dist in "${_sp}"/*.dist-info; do
      if [ -e "${_dist}" ]; then return 0; fi
    done
  done
  return 1
}

# The module this call needs, or empty when the call runs a SCRIPT PATH (which needs no module).
_NEEDED_MODULE="${1:-}"
case "${_NEEDED_MODULE}" in
  *.py) _NEEDED_MODULE='' ;;
esac

_can_run() {
  if [ -z "${_NEEDED_MODULE}" ]; then return 0; fi
  "$1" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('${_NEEDED_MODULE}') else 1)" \
    >/dev/null 2>&1
}

PYTHON=''
_SAW_VENV=''
for root in "${THIS_ROOT}" "${MAIN_ROOT}"; do
  for candidate in "${root}/.venv/Scripts/python.exe" "${root}/.venv/bin/python"; do
    if [ -x "${candidate}" ] && _has_distributions "${root}/.venv"; then
      _SAW_VENV="yes"
      if [ -z "${PYTHON}" ] && _can_run "${candidate}"; then
        PYTHON="${candidate}"
      fi
    fi
  done
done

if [ -z "${PYTHON}" ]; then
  if [ -n "${_SAW_VENV}" ]; then
    echo "with-venv: no .venv under ${THIS_ROOT} or ${MAIN_ROOT} provides '${_NEEDED_MODULE}'." >&2
    echo "  A venv EXISTS in at least one of them, so this is a missing TOOL rather than a" >&2
    echo "  missing environment -- install ${_NEEDED_MODULE} into one of those venvs." >&2
  else
    echo "with-venv: no .venv under ${THIS_ROOT} or ${MAIN_ROOT}." >&2
    echo "  Create one in either: this lane's own (preferred -- isolates dependency changes)," >&2
    echo "  or MAIN's (shared by every lane that has none of its own)." >&2
  fi
  exit 1
fi

# Resolving the INTERPRETER is only half of it, and the half that does not bite until you push from
# a lane. A type checker picks the environment it ANALYSES against from the project root it runs in
# -- it looks for a `.venv` there -- so a lane WITHOUT one silently falls back to the system Python
# and every third-party import goes unresolved. MEASURED 2026-07-28 pushing from a worktree: 41
# errors, all of them "could not be resolved", against files that are clean on MAIN. Passing
# `--pythonpath` takes the same file from 2 errors to 0.
#
# So the SOURCE analysed stays the caller's (a lane must check its own tree, that is the point);
# only the environment is pinned to the one resolved above. The hook's own comment already CLAIMED
# this trap was handled, which is why it survived: the declaration was there and nothing consulted it.
if [ "${1:-}" = 'pyright' ]; then
  shift
  exec "${PYTHON}" -m pyright --pythonpath "${PYTHON}" "$@"
fi

# A SCRIPT PATH is not a module name, and `-m` cannot run one.
#
# MEASURED 2026-08-06. A pre-push smoke had been routed through
# `... with-venv.sh python scripts/gate/covering_tests.py --run ...`, and the line below expanded it
# to `<venv>/python -m python scripts/gate/covering_tests.py`. That fails instantly with
# `No module named python` -- so from the commit that made the smoke diff-selected until the repair,
# the pre-push smoke never executed a single test. It reported "the run did not finish", which the
# guard read as truncation, and it blocked every push it fired on. Two subsequent fixes were both
# real defects and neither was THIS one; they were repairs to a selector that was never reached.
#
# The lesson is a wrapper that accepts anything and MEANS one thing. `-m "$@"` reads as "run this
# through the resolved interpreter" and is really "import this as a module". Nothing consulted the
# difference, so a caller could pass a path, be wrong, and get a message about modules.
#
# Dispatching on the `.py` suffix rather than adding a flag: the suffix is already unambiguous, and a
# flag would need every call site updated to say something the argument already says.
case "${1:-}" in
  *.py) exec "${PYTHON}" "$@" ;;
esac

exec "${PYTHON}" -m "$@"
