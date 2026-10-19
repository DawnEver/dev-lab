"""A SESSION BRANCH IS PROTECTED AT PUSH: three local invariants, judged on git's own pre-push lines.

User ruling 2026-10-13: every session has ONE branch it leads (``[tool.lab_commons.branchset] sessions``,
the integration branch among them), and that branch is protected for what it IS, never for where it is
checked out or which box pushes it -- both move.

``ONE-WRITER-PER-SESSION-BRANCH`` (P1) is git's own, and nothing is built for it (user ruling 2026-10-14:
no lease refs -- every push would read and write origin). LOCALLY a branch is checked out in at most one
worktree, so the sessions of one host and repo, one per worktree, never share a branch. REMOTELY a plain
push is compare-and-swap: origin refuses a non-fast-forward, so a writer working on a stale tip loses and
must merge first -- and P3 below refuses the force that would bypass it.

The invariants refused here by name, with NO network call beyond the push itself:

* ``PUBLISH-IS-THE-LOCAL-REF`` (P2) -- a push to ``refs/heads/X`` carries the local branch ``X``: its local
  ref, with ``HEAD`` resolved, IS ``refs/heads/X``. ``HEAD:X`` from another branch, ``Y:X`` and a bare sha
  are refused. Any checkout may publish ``X`` -- none needs it checked out.
* ``SESSION-HISTORY-ONLY-GROWS`` (P3) -- the old remote tip git hands the hook is an ancestor of the new
  one; a forced non-fast-forward and a deletion are refused. ONE place: no other hook judges this.
* ``INTEGRATION-IS-MERGES-ONLY`` (P4) -- every new first-parent commit of the integration branch is a
  two-parent merge naming its branch in a ``Merged-Branch:`` trailer, and the merge audit
  (:func:`lab_commons.dev.mergeaudit.judge`, the SAME judgement the commit-msg hook makes) passes on it.
  Judged from ``[tool.lab_commons.integrator] merges_only_since`` forward: no retroactive check.
* ``INTEGRATION-TAKES-ONLY-FORGE-MERGES`` (P5) -- once ``[tool.lab_commons.integrator] pr_merges_since`` is
  declared, the integration branch moves ONLY by the forge's server-side merge of a green pull request
  (:mod:`lab_commons.dev.forgemerge`). Such a merge is on origin before any client holds it, so a client push
  that adds ANY first-parent commit past origin's tip (and past the declared start) is not one, and is refused.
  It replaces P4 for that branch. The ONE bypass is in the history: a push whose every new first-parent
  commit carries a non-empty ``Break-Glass: <reason>`` trailer is admitted (:mod:`lab_commons.dev.breakglass`).

Every ref is judged by the declaration its pushed tip carries, never the working tree's; a deletion carries
no content, so it is judged by the integration branch's declaration (``origin/<integration>``, else the
trunk's, else ``HEAD``'s) -- never the deleted tip's, nor a stale checkout's. There is no bypass:
a guard that cannot judge (no branch set at that tip) refuses.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.dev.branchset import BranchSetNotDeclared, branchset_at
from lab_commons.dev.breakglass import BREAK_GLASS, reason
from lab_commons.dev.lanepolicy import Policy, policy_at
from lab_commons.dev.mergeaudit import MergeAuditError, judge
from lab_commons.log import emit

__all__ = [
    'MERGED_BRANCH',
    'P2',
    'P3',
    'P4',
    'P5',
    'main',
    'merged_branch',
    'refusals',
]

P2: Final = 'PUBLISH-IS-THE-LOCAL-REF'
P3: Final = 'SESSION-HISTORY-ONLY-GROWS'
P4: Final = 'INTEGRATION-IS-MERGES-ONLY'
P5: Final = 'INTEGRATION-TAKES-ONLY-FORGE-MERGES'
#: The trailer an integration merge names its merged branch under.
MERGED_BRANCH: Final = 'Merged-Branch'

_GIT: Final = shutil.which('git') or 'git'
_HEADS: Final = 'refs/heads/'
_FIELDS: Final = 4
_PARENTS: Final = 2
_TRAILER: Final = re.compile(rf'^{MERGED_BRANCH}:\s*(\S+)\s*$', re.MULTILINE)
_MERGE: Final = 'python -m lab_commons.dev.integrate merge <branch>'


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=120
    )


def _zero(sha: str) -> bool:
    return set(sha) == {'0'}


def merged_branch(message: str) -> str | None:
    """The branch a merge commit's ``Merged-Branch:`` trailer names, or ``None``."""
    found = _TRAILER.findall(message)
    return found[-1] if found else None


def _merges_only(root: Path, policy: Policy, old: str, new: str) -> list[str]:
    """P4 over the first-parent commits *new* adds to the integration branch past *old* and the declared start."""
    since = policy.merges_only_since
    if _zero(old) and not since:
        return [
            (
                f'{P4}: this push CREATES {policy.integration}, so its whole history would be judged; declare '
                f'[tool.lab_commons.integrator] merges_only_since = "<sha>" to start the rule there'
            )
        ]
    excluded = [f'^{sha}' for sha in (old, since) if sha and not _zero(sha)]
    listed = _git(root, 'rev-list', '--first-parent', '--reverse', new, *excluded)
    if listed.returncode != 0:
        return [f'{P4}: cannot list the new commits of {policy.integration}: {listed.stderr.strip()}']
    found = []
    for sha in listed.stdout.split():
        parents = _git(root, 'rev-list', '--parents', '-n', '1', sha).stdout.split()[1:]
        message = _git(root, 'log', '-1', '--format=%B', sha).stdout
        if len(parents) != _PARENTS:
            found.append(f'{P4}: {sha[:12]} is not a merge ({len(parents)} parent(s)); merge with {_MERGE}')
            continue
        name = merged_branch(message)
        if name is None or name == policy.integration:
            found.append(f'{P4}: {sha[:12]} names no {MERGED_BRANCH}: <branch> trailer; merge with {_MERGE}')
            continue
        try:
            problems = judge(root, parents, sha, message, roots=policy.test_roots, label=sha[:12])
        except MergeAuditError as error:
            problems = (str(error),)
        found += [f'{P4}: {sha[:12]} merge-audit: {problem}' for problem in problems]
    return found


def _forge_merges_only(root: Path, policy: Policy, old: str, new: str) -> list[str]:
    """P5: the first-parent commits *new* adds past origin's *old* and the declared start -- every one refused."""
    excluded = [f'^{sha}' for sha in (old, policy.pr_merges_since) if not _zero(sha)]
    listed = _git(root, 'rev-list', '--first-parent', new, *excluded)
    if listed.returncode != 0:
        return [f'{P5}: cannot list the new commits of {policy.integration}: {listed.stderr.strip()}']
    added = listed.stdout.split()
    unglassed = [sha for sha in added if not reason(_git(root, 'log', '-1', '--format=%B', sha).stdout)]
    if not unglassed:
        return []
    return [
        (
            f'{P5}: this push adds {len(added)} commit(s) to {policy.integration}, {len(unglassed)} with no '
            f'{BREAK_GLASS}: <reason> trailer (newest {unglassed[0][:12]}); it moves only by the forge merging a '
            f'green pull request. Push a pr/<topic> branch and open a PR into {policy.integration} instead -- or, '
            f'only when the forge itself is down or its auto-merge broken, give EVERY new commit a '
            f'{BREAK_GLASS}: <reason> trailer'
        )
    ]


def _local(root: Path, local: str) -> str:
    if local != 'HEAD':
        return local
    done = _git(root, 'symbolic-ref', '-q', 'HEAD')
    return done.stdout.strip() if done.returncode == 0 else 'a detached HEAD'


def _judge_ref(root: Path, policy: Policy, fields: Sequence[str]) -> list[str]:
    """P2, P3 and P4 for one pre-push line whose remote ref is a guarded branch."""
    local, sha, remote, old = fields
    branch = remote[len(_HEADS) :]
    if _zero(sha):
        return [f'{P3}: deleting {branch} is refused; a session branch only grows']
    found = []
    if (named := _local(root, local)) != remote:
        found.append(
            f'{P2}: {branch} is published only from the local branch {branch}, not {named}; '
            f'merge into {branch} and push `{branch}`'
        )
    if not _zero(old) and _git(root, 'merge-base', '--is-ancestor', old, sha).returncode != 0:
        found.append(
            f'{P3}: {branch} at {old[:12]} on origin is not an ancestor of {sha[:12]}; history only grows: '
            f'fetch, merge origin/{branch} into {branch}, push again (never force)'
        )
    if branch == policy.integration and policy.pr_merges_since:
        found += _forge_merges_only(root, policy, old, sha)
    elif branch == policy.integration:
        found += _merges_only(root, policy, old, sha)
    return found


def _deletion_rev(root: Path) -> str:
    """The rev a deletion is judged by: ``origin/<integration>``, else ``origin/<trunk>``, else ``HEAD``.

    The names come from ``HEAD``'s ``[tool.lab_commons.integrator]``, defaults when it cannot be read: a stale
    checkout must not decide what deleting a ref means, and a deletion carries nothing of its own to read.
    """
    try:
        policy = policy_at(root, 'HEAD')
    except (ValueError, OSError, subprocess.CalledProcessError):
        policy = Policy()
    for name in (policy.integration, policy.trunk):
        rev = f'refs/remotes/origin/{name}'
        if _git(root, 'rev-parse', '-q', '--verify', f'{rev}^{{commit}}').returncode == 0:
            return rev
    return 'HEAD'


def refusals(root: Path, lines: str) -> list[str]:
    """Every refusal for the push *lines* describe; local reads only.

    Each ref is judged by the declaration its PUSHED tip carries -- never the working tree's. A deletion
    pushes no content, so it is judged by the integration branch's (:func:`_deletion_rev`), never the deleted
    ref's old tip, which may predate or outlive the table.
    """
    found: list[str] = []
    for fields in (line.split() for line in lines.splitlines()):
        if len(fields) != _FIELDS or not fields[2].startswith(_HEADS):
            continue
        at = _deletion_rev(root) if _zero(fields[1]) else fields[1]
        label = at if _zero(fields[1]) else at[:12]
        try:
            declared = branchset_at(root, at)
            policy = policy_at(root, at)
        except (BranchSetNotDeclared, ValueError, subprocess.CalledProcessError) as exc:
            found.append(f'{P2}: {label} declares no readable branch set, so {fields[2]} cannot be judged: {exc}')
            continue
        if fields[2] in {f'{_HEADS}{name}' for name in declared.sessions | {declared.trunk}}:
            found += _judge_ref(root, policy, fields)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push hook: git's ref lines on stdin; exit 1 refuses, 0 publishes."""
    del argv  # git passes the remote name and url; nothing here reads the remote
    top = _git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.strip()
    found = refusals(Path(top or Path.cwd()), '' if sys.stdin.isatty() else sys.stdin.read())
    if found:
        emit('\n'.join(['', *(f'  REFUSED: {line}' for line in found), '']), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
