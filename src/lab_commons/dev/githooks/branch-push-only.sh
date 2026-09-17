#!/usr/bin/env bash
# Run the wrapped command only when the push UPDATES A BRANCH. A WRAPPER, wired as a pre-commit
# `pre-push` hook around whatever that repo actually wants to run:
#
#   python -m lab_commons.dev.githooks branch-push-only <label> <command> [args...]
#
# THE QUESTION A PRE-PUSH HOOK IS ACTUALLY ASKED. `git push` runs pre-push for every ref in the
# refspec, and a ref is not necessarily code. A fleet that pushed MACHINE REFS
# (`refs/ci/heartbeat/<runner>/<epoch>`) exposed the durable fact: judging "is there code arriving on
# a branch" must not happen on the LOCAL branch (`HEAD` reads the same for a branch push and a ref
# push) but on the REMOTE REF. The local branch is the wrong axis -- a heartbeat push is made FROM
# `main`, so any hook asking "am I on the release branch" says yes and proceeds.
#
# THE FACTS ARRIVE AS ENVIRONMENT VARIABLES, not on stdin -- pre-commit consumes stdin to compute the
# diff range, so `while read local_ref local_sha remote_ref remote_sha` reads EOF here. MEASURED
# 2026-08-13 with pre-commit 4.x, by installing a probe hook and pushing for real; these are
# populated, and `PRE_COMMIT_REMOTE_BRANCH` carries the FULL remote ref:
#
#   branch push       PRE_COMMIT_REMOTE_BRANCH=refs/heads/main
#   machine-ref push  PRE_COMMIT_REMOTE_BRANCH=refs/ci/heartbeat/box/1
#   both              PRE_COMMIT_LOCAL_BRANCH=HEAD  PRE_COMMIT_REMOTE_NAME=origin
#
# ==== THE SEAM, AND WHY THIS SCRIPT IS A SPLIT RATHER THAN A MOVE ====
#
# The AXIS, the three outcomes and the decline text are family: every repo in this family pushes
# through pre-commit and every one of them is asked about tags it should not judge. What is NOT
# family is that one branch may take only a tree some TIER has already judged -- which branch, and
# which tier, are facts about one repo's verdict structure and cannot be derived from here. They
# arrive as ENVIRONMENT VARIABLES WITH NO DEFAULT, because a default would silently hand every other
# repo one repo's answer, and the shape of that answer -- "main takes only a heavy-judged tree" --
# is exactly the kind of claim a repo must make out loud or not at all:
#
#   LAB_PUSH_PROTECTED_REF   the ONE remote ref that needs more than a branch push, spelled in full
#                            (`refs/heads/main`), or the literal `none` to DECLARE that this repo
#                            has no such ref. REQUIRED -- there is no default.
#   LAB_PUSH_PROTECTED_CMD   the shell command that must exit 0 before that ref may be pushed. Its
#                            output is shown as-is; it is REQUIRED unless the ref is `none`.
#   LAB_PUSH_PROTECTED_NAME  the word a refusal NAMES, so a reader knows which tier declined.
#                            default: the command's first word -- derived, not a repo fact.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=git-env-repair.sh
. "${HERE}/git-env-repair.sh"

LABEL="${1:?branch-push-only.sh: first argument is the hook label}"
shift
[ "$#" -gt 0 ] || {
  echo "branch-push-only.sh: no command to run after the label" >&2
  exit 1
}

PROTECTED_REF="${LAB_PUSH_PROTECTED_REF-}"
if [ -z "${PROTECTED_REF}" ]; then
  echo "[${LABEL}] MISCONFIGURED -- LAB_PUSH_PROTECTED_REF is unset." >&2
  echo "[${LABEL}]   Name the one remote ref that needs more than a branch push (e.g." >&2
  echo "[${LABEL}]   refs/heads/main), or set it to 'none' to declare this repo has no such ref." >&2
  echo "[${LABEL}]   There is no default: a default would give this repo another repo's answer." >&2
  exit 1
fi
PROTECTED_CMD="${LAB_PUSH_PROTECTED_CMD-}"
if [ "${PROTECTED_REF}" != 'none' ] && [ -z "${PROTECTED_CMD}" ]; then
  echo "[${LABEL}] MISCONFIGURED -- LAB_PUSH_PROTECTED_REF names ${PROTECTED_REF} and" >&2
  echo "[${LABEL}]   LAB_PUSH_PROTECTED_CMD is unset, so the protection is a declaration that" >&2
  echo "[${LABEL}]   nothing enforces. Give the command, or declare the ref as 'none'." >&2
  exit 1
fi
PROTECTED_NAME="${LAB_PUSH_PROTECTED_NAME:-${PROTECTED_CMD%% *}}"

REMOTE_REF="${PRE_COMMIT_REMOTE_BRANCH-}"

decline() {
  echo "[${LABEL}] DECLINED -- this push updates no branch."
  echo "[${LABEL}]   remote ref: ${REMOTE_REF}"
  echo "[${LABEL}]   $1"
  echo "[${LABEL}]   Nothing was checked and nothing needed to be. A branch push runs this in full;"
  echo "[${LABEL}]   see lab_commons/dev/githooks/branch-push-only.sh for why the remote ref is the axis."
  exit 0
}

case "${REMOTE_REF}" in
  '')
    echo "[${LABEL}] no PRE_COMMIT_REMOTE_BRANCH in the environment -- running, on purpose."
    ;;
  "${PROTECTED_REF}")
    # Reached only when PROTECTED_REF is a real ref: `none` is not a ref name, so it can never match
    # a populated PRE_COMMIT_REMOTE_BRANCH, and the empty case is handled above.
    echo "[${LABEL}] push to ${REMOTE_REF} -- it takes only a tree ${PROTECTED_NAME} has judged."
    if ! eval "${PROTECTED_CMD}"; then
      echo "[${LABEL}] REFUSED -- see the line above for what ${PROTECTED_REF} is missing a verdict for."
      exit 1
    fi
    ;;
  refs/heads/*)
    echo "[${LABEL}] branch push (${REMOTE_REF}) -- running."
    ;;
  refs/tags/*)
    decline "A tag names a commit that was judged when it was pushed to its branch."
    ;;
  refs/*)
    decline "Only refs/heads/** carries code onto a branch."
    ;;
  *)
    echo "[${LABEL}] remote ref '${REMOTE_REF}' is not a full ref name -- running, on purpose."
    ;;
esac

exec "$@"
