#!/usr/bin/env bash
# Check commit messages over the PUSH INCREMENT, not over the whole branch history. A HOOK, wired as
# a pre-commit `pre-push` entry:
#
#   python -m lab_commons.dev.githooks cz-push-range
#
# WHAT WENT WRONG WITH A WHOLE-LANE RANGE, measured 2026-09-02. `commitizen-branch` was pinned to
# `<base>..HEAD`, and on a long-lived lane that re-judges everything the lane ever did: 1090 commits
# on one branch, two of them carrying types outside the conventional set. Both were pushed BEFORE
# pre-commit was installed on that box, so both were already on `origin` -- immutable published
# history on a SHARED branch. From the moment the hook was installed, the lane could not be pushed at
# all: every future push was refused for two commits nobody can legally rewrite (no force-push on a
# shared branch) and nobody can un-publish.
#
# A hook that makes a lane unpushable is not a strict hook, it is a broken one, so the range is the
# defect. The right question for a PRE-PUSH hook is "are the commits I am about to publish
# well-formed", and pre-commit already computes exactly that: `PRE_COMMIT_FROM_REF` is what the
# remote has and `PRE_COMMIT_TO_REF` is what is being sent (both measured present 2026-08-13 -- see
# `branch-push-only.sh`, which documents the whole environment block).
#
# WHAT THIS DOES NOT FIX, stated because it is the neighbouring mechanism rather than this one.
# Narrowing to the increment does not widen the hole where a commit reaches the trunk with a
# non-conventional message: a commit already on the REMOTE BRANCH was, at the moment it was pushed,
# inside its own increment and was judged then. The hole is about commits that arrive on the trunk by
# a route with no pre-push at all, which is `branch-push-only.sh`'s protected-ref case.
#
# THE FALLBACK RANGE IS `<base>..HEAD`, AND THE BASE IS A REPO FACT WITH NO DEFAULT:
#
#   LAB_CZ_BASE_REF   the ref a lane is measured against when there is no increment to read, e.g.
#                     `origin/main`. REQUIRED. It is deliberately not derived from `origin/HEAD`,
#                     which can point at a stale branch and drag in legacy non-conventional
#                     messages, and deliberately not defaulted, because a repo whose trunk is not
#                     called `main` would silently judge its lane against a ref that does not exist.
#
# The fallback fires when there is no increment to read -- a manual `pre-commit run --hook-stage
# pre-push`, or a brand-new branch whose remote side is the all-zero sha -- and in both of those a
# lane's full history against the base IS the right question, because none of it has been published.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=git-env-repair.sh
. "${HERE}/git-env-repair.sh"

BASE_REF="${LAB_CZ_BASE_REF-}"
if [ -z "${BASE_REF}" ]; then
  echo "[cz-push-range] MISCONFIGURED -- LAB_CZ_BASE_REF is unset." >&2
  echo "[cz-push-range]   Name the ref an unpublished lane is judged against (e.g. origin/main)." >&2
  echo "[cz-push-range]   There is no default: a repo whose trunk is named otherwise would be" >&2
  echo "[cz-push-range]   judged against a ref that does not exist, and read as a clean lane." >&2
  exit 1
fi

FROM_REF="${PRE_COMMIT_FROM_REF-}"
TO_REF="${PRE_COMMIT_TO_REF-}"

RANGE="${BASE_REF}..HEAD"
WHY="no push increment in the environment -- judging the whole lane against ${BASE_REF}, on purpose"

# A NEW BRANCH REPORTS AN ALL-ZERO REMOTE SHA, which is not an object and cannot start a range.
if [ -n "${FROM_REF}" ] && [ -n "${TO_REF}" ] && [ -z "${FROM_REF//0/}" ]; then
  WHY="the remote side is the all-zero sha (a new branch) -- judging the whole lane against ${BASE_REF}"
elif [ -n "${FROM_REF}" ] && [ -n "${TO_REF}" ]; then
  if git rev-parse --verify --quiet "${FROM_REF}^{commit}" >/dev/null &&
    git rev-parse --verify --quiet "${TO_REF}^{commit}" >/dev/null; then
    RANGE="${FROM_REF}..${TO_REF}"
    WHY='the push increment, as pre-commit computed it'
  else
    WHY="pre-commit named a sha this checkout does not have -- judging the whole lane against ${BASE_REF}"
  fi
fi

# PRINTED, NOT SILENT: the hooks that use this carry `verbose: true`, and a range chosen by fallback
# must say so -- otherwise a push refused for a legacy message looks like a push refused for the
# commit you just wrote.
echo "[cz-push-range] rev-range ${RANGE} -- ${WHY}"

# AN EMPTY RANGE IS NOTHING TO JUDGE, NOT A REFUSAL, measured 2026-09-03. `commitizen check` exits 3
# with "No commit found with range" when the range holds no commit, and a pre-push whose increment is
# empty is exactly that case: an up-to-date branch being re-pushed, or a push of only
# already-published commits. Letting the 3 through makes such a push impossible -- the same class of
# unpushable-lane defect the range narrowing above exists to remove. The check is `rev-list`, not a
# parse of commitizen's message, so it cannot drift with that tool's wording.
if [ "$(git rev-list --count "${RANGE}")" -eq 0 ]; then
  echo "[cz-push-range] the range holds no commit -- nothing to check"
  exit 0
fi

exec bash "${HERE}/with-venv.sh" commitizen check --rev-range "${RANGE}"
