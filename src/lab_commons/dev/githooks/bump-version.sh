#!/usr/bin/env bash
# Auto-tag the repo patch version on push. Wired as a pre-commit `pre-push` hook via
#   entry: python -m lab_commons.dev.githooks bump-version
# Versioning is SCM/tag-driven (hatch-vcs / setuptools-scm, tag format v$version), so "bumping" is
# creating the next tag.
#
# BEST-EFFORT BY DESIGN: tagging must NEVER block the code push, so every path exits 0 and failures
# are logged rather than fatal. This is a property the wdg-lab fork did not have -- `set -e` plus a
# fatal `git tag -a` made a tagging problem fail a developer's push.
#
# EVERY REPO-SPECIFIC DECISION ARRIVES AS AN ENVIRONMENT VARIABLE, because a hook that branched on a
# repo name would be the fork this file removes, one indirection along:
#
#   $1 / LAB_BUMP_REMOTE     the remote to fetch tags from and publish to.        default: origin
#   LAB_BUMP_GIT_NET         the command that runs NETWORK git operations; a repo
#                            with a retry wrapper points this at it, and the words
#                            after `git` are appended (`push ...`, `fetch ...`).  default: git
#   LAB_BUMP_PROOF_CMD       optional. A command that must exit 0 before a tag is
#                            minted; its first stdout line is recorded IN the tag
#                            as what proved the tree. Unset means tag without a
#                            proof -- correct for a repo with no such tier.       default: unset
#   LAB_BUMP_PROOF_NAME      the word a refusal NAMES, so a reader knows which
#                            tier declined.                                       default: proof
#   LAB_BUMP_RELEASE_BRANCH  the only branch that may mint a tag.
#                                             default: the remote's HEAD, else main

REMOTE="${1:-${LAB_BUMP_REMOTE:-origin}}"
GIT_NET="${LAB_BUMP_GIT_NET:-git}"
PROOF_NAME="${LAB_BUMP_PROOF_NAME:-proof}"

# NEVER WAIT ON A CREDENTIAL PROMPT. Measured 2026-08-17 in motronics-studio: with the forge
# answering 200 but the credential displaced, the tag `git push` below sat forever on a prompt this
# hook has no stdin to answer, and the whole `git push` the developer typed never returned.
# "Best-effort" was false in the strongest possible direction -- not a wrong exit code, no exit at
# all.
#
# BOTH DOORS, because they are different mechanisms: `GIT_TERMINAL_PROMPT` is git's own terminal
# prompt, and `GCM_INTERACTIVE` is Git Credential Manager's GUI, which no terminal setting reaches
# and which is the one that actually fires on Windows.
export GIT_TERMINAL_PROMPT=0
export GCM_INTERACTIVE=never

# Push a tag without re-entering pre-push (idempotent: no-op if already remote).
publish_tag() {
  local tag="$1"
  local err
  # STDERR IS KEPT, not discarded. `>/dev/null 2>&1` made "could not publish" true, useless and
  # identical for an auth failure, a non-fast-forward and a dead network -- a guard reporting into a
  # discarded stream is indistinguishable from no guard. One line tells them apart.
  if err=$(${GIT_NET} push --no-verify "$REMOTE" "refs/tags/${tag}" 2>&1 >/dev/null); then
    echo "bump-version: published ${tag}"
  else
    echo "bump-version: could not publish ${tag} -- ${err%%$'\n'*} (will retry next push)"
  fi
}

# Highest plain-semver tag by NUMERIC (major, minor, patch) order. `git tag --sort=-version:refname`
# needs a recent git plus versionsort config and can mis-order multi-digit patches on older git-bash
# installs, so sort the numeric fields here -- portable across every git that has `git tag`.
latest_semver_tag() {
  git tag --list 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null \
    | sed 's/^v//' \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' \
    | sort -t. -k1,1n -k2,2n -k3,3n \
    | tail -1
}

# Only auto-tag when pushing the release branch: a feature/topic branch push must not mint a release
# tag and pollute the tag namespace. Read from the remote's HEAD, falling back to `main`.
DEFAULT_BRANCH="${LAB_BUMP_RELEASE_BRANCH:-}"
if [ -z "$DEFAULT_BRANCH" ]; then
  DEFAULT_BRANCH=$(git symbolic-ref --quiet --short "refs/remotes/${REMOTE}/HEAD" 2>/dev/null | sed "s@^${REMOTE}/@@")
  DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
fi
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ "$CURRENT_BRANCH" != "$DEFAULT_BRANCH" ]; then
  echo "bump-version: on '${CURRENT_BRANCH}', not release branch '${DEFAULT_BRANCH}'; skipping tag bump"
  exit 0
fi

# Best-effort: refresh remote tags so both the collision check below and the "highest tag"
# computation see tags another push already created remotely but that are absent locally. Never
# fatal -- offline pushes still tag.
${GIT_NET} fetch --quiet --tags "$REMOTE" >/dev/null 2>&1 || true

# If HEAD already carries a version tag, don't bump again -- just make sure it is on the remote
# (recovers a tag orphaned by an earlier rejected push).
EXISTING=$(git tag --points-at HEAD --list 'v[0-9]*' 2>/dev/null | head -1)
if [ -n "$EXISTING" ]; then
  echo "bump-version: HEAD already tagged ${EXISTING}"
  publish_tag "$EXISTING"
  exit 0
fi

# Bump from the globally-highest plain-semver tag so the new tag stays monotonic and never collides
# with an existing (or dangling) tag.
LATEST_TAG="$(latest_semver_tag)"
LATEST_TAG="v${LATEST_TAG:-0.0.0}"
VERSION="${LATEST_TAG#v}"
if [[ ! "$VERSION" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
  echo "bump-version: latest tag '${LATEST_TAG}' is not plain vMAJOR.MINOR.PATCH, skipping"
  exit 0
fi
MAJOR="${BASH_REMATCH[1]}"; MINOR="${BASH_REMATCH[2]}"; PATCH="${BASH_REMATCH[3]}"

# Increment PATCH ONCE and recompute NEW_TAG from it each iteration, so the collision scan walks
# CONSECUTIVE candidates and cannot skip a version. The wdg-lab fork incremented twice per round --
# once in the loop body and once in the expression -- so one taken tag cost two version numbers.
PATCH=$((PATCH + 1))
NEW_TAG="v${MAJOR}.${MINOR}.${PATCH}"
while git rev-parse -q --verify "refs/tags/${NEW_TAG}" >/dev/null 2>&1; do
  PATCH=$((PATCH + 1))
  NEW_TAG="v${MAJOR}.${MINOR}.${PATCH}"
done

# A TAG MAY BE MADE TO MEAN "A TIER JUDGED THIS TREE". Without a proof command it means only "this
# is the next number", which is the honest reading for a repo with no such tier -- and the reason
# this is a variable rather than a hard-coded call into one repo's gate.
#
# WHY THE TAG AND NOT THE PUSH is the design. Withholding the PUSH until the tier passes would lock
# the trunk whenever that tier cannot complete. Withholding the TAG does not: this hook exits 0 on
# every path, so an unproven tree still lands on the branch -- it simply does not get a version.
PROOF=''
if [ -n "${LAB_BUMP_PROOF_CMD:-}" ]; then
  if ! PROOF=$(eval "${LAB_BUMP_PROOF_CMD}" 2>&1); then
    echo "bump-version: NOT tagging ${NEW_TAG} -- no ${PROOF_NAME} verdict for this tree."
    echo "bump-version:   ${PROOF%%$'\n'*}"
    echo "bump-version:   The push itself is unaffected; this tree simply carries no version."
    exit 0
  fi
fi

# THE TAG CARRIES THE LINE IT RESTS ON. A version whose provenance lives in a file somewhere else is
# the same defect one indirection along -- `git show <tag>` must answer "what proved this?".
MESSAGE="Release ${NEW_TAG}"
if [ -n "$PROOF" ]; then
  MESSAGE="${MESSAGE}

Proved by: ${PROOF}"
fi
if git tag -a "$NEW_TAG" -m "$MESSAGE"; then
  echo "bump-version: tagged ${NEW_TAG}"
  if [ -n "$PROOF" ]; then
    echo "bump-version:   resting on ${PROOF}"
  fi
  publish_tag "$NEW_TAG"
fi
exit 0
