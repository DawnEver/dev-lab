#!/usr/bin/env bash
# Check commit messages over the PUSH INCREMENT, not over the whole branch history. A HOOK, declared
# as a `pre-push` row of [tool.dev_lab.hooks] (dev_lab.dev.githooks.table):
#
#   run = ["python", "-m", "dev_lab.dev.githooks", "script", "cz-push-range"]
#   env = { LAB_CZ_BASE_REF = "origin/main" }
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
# well-formed", and git states exactly that on the hook`s stdin, one line per pushed ref:
# `<local ref> <local sha> <remote ref> <remote sha>` -- the remote sha is what the remote has, the
# local sha what is being sent.
#
# WHAT THIS DOES NOT FIX, stated because it is the neighbouring mechanism rather than this one.
# Narrowing to the increment does not widen the hole where a commit reaches the trunk with a
# non-conventional message: a commit already on the REMOTE BRANCH was, at the moment it was pushed,
# inside its own increment and was judged then. The hole is about commits that arrive on the trunk by
# a route with no pre-push at all.
#
# THE FALLBACK RANGE IS `<base>..HEAD`, AND THE BASE IS A REPO FACT WITH NO DEFAULT:
#
#   LAB_CZ_BASE_REF   the ref a lane is measured against when there is no increment to read, e.g.
#                     `origin/main`. REQUIRED. It is deliberately not derived from `origin/HEAD`,
#                     which can point at a stale branch and drag in legacy non-conventional
#                     messages, and deliberately not defaulted, because a repo whose trunk is not
#                     called `main` would silently judge its lane against a ref that does not exist.
#
# The fallback fires when there is no increment to read -- a run with no ref lines on stdin, or a
# brand-new branch whose remote side is the all-zero sha -- and in both of those a
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

ZERO='0000000000000000000000000000000000000000'
RANGES=()
WHYS=()
# git's pre-push protocol on stdin; a deleted ref (local sha all-zero) publishes no commit.
if [ ! -t 0 ]; then
  while read -r _local_ref local_sha _remote_ref remote_sha; do
    remote_sha="${remote_sha%$'\r'}"
    [ -n "${remote_sha:-}" ] || continue
    [ "${local_sha}" = "${ZERO}" ] && continue
    if [ "${remote_sha}" = "${ZERO}" ]; then
      RANGES+=("${BASE_REF}..${local_sha}")
      WHYS+=("the remote side is the all-zero sha (a new branch) -- judging the whole lane against ${BASE_REF}")
    elif git rev-parse --verify --quiet "${remote_sha}^{commit}" >/dev/null; then
      RANGES+=("${remote_sha}..${local_sha}")
      WHYS+=('the push increment, as git stated it')
    else
      RANGES+=("${BASE_REF}..${local_sha}")
      WHYS+=("the remote names a sha this checkout does not have -- judging the whole lane against ${BASE_REF}")
    fi
  done
fi
if [ "${#RANGES[@]}" -eq 0 ]; then
  RANGES=("${BASE_REF}..HEAD")
  WHYS=("no push increment on stdin -- judging the whole lane against ${BASE_REF}, on purpose")
fi

# AN EMPTY RANGE IS NOTHING TO JUDGE, NOT A REFUSAL, measured 2026-09-03. `commitizen check` exits 3
# with "No commit found with range" when the range holds no commit (an up-to-date branch re-pushed).
# The check is `rev-list`, not a parse of commitizen's message, so it cannot drift with its wording.
status=0
for i in "${!RANGES[@]}"; do
  RANGE="${RANGES[$i]}"
  # PRINTED, NOT SILENT: a range chosen by fallback must say so.
  echo "[cz-push-range] rev-range ${RANGE} -- ${WHYS[$i]}"
  if [ "$(git rev-list --count "${RANGE}")" -eq 0 ]; then
    echo "[cz-push-range] the range holds no commit -- nothing to check"
    continue
  fi
  bash "${HERE}/with-venv.sh" commitizen check --rev-range "${RANGE}" || status=1
done
exit "${status}"
