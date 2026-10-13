"""A SESSION BRANCH IS PROTECTED AT PUSH: four invariants, judged on git's own pre-push lines.

User ruling 2026-10-13: every session has ONE branch it leads (``[tool.lab_commons.branchset] sessions``,
the integration branch among them), and that branch is protected for what it IS, never for where it is
checked out or which box pushes it -- both move. The invariants, each refused here by name:

* ``ONE-WRITER-PER-SESSION-BRANCH`` (P1) -- only the session holding the branch's lease advances it
  (:mod:`lab_commons.dev.sessionlease`; the trunk is guarded by the integration branch's lease). A push by
  the holder RENEWS the lease, so an active session never lapses.
* ``PUBLISH-IS-THE-LOCAL-REF`` (P2) -- a push to ``refs/heads/X`` carries the local branch ``X``: its local
  ref, with ``HEAD`` resolved, IS ``refs/heads/X``. ``HEAD:X`` from another branch, ``Y:X`` and a bare sha
  are refused. Any checkout may publish ``X`` -- none needs it checked out.
* ``SESSION-HISTORY-ONLY-GROWS`` (P3) -- the old remote tip is an ancestor of the new one; a forced
  non-fast-forward and a deletion are refused. ONE place: no other hook judges ancestry of a session branch.
* ``INTEGRATION-IS-MERGES-ONLY`` (P4) -- every new first-parent commit of the integration branch is a
  two-parent merge naming its branch in a ``Merged-Branch:`` trailer, and the merge audit
  (:func:`lab_commons.dev.mergeaudit.judge`, the SAME judgement the commit-msg hook makes) passes on it.
  Judged from ``[tool.lab_commons.integrator] merges_only_since`` forward: no retroactive check.

Local refusals (P2-P4) are judged first and need no network; the lease is read from origin last.
There is no bypass: a guard that cannot judge (no branch set, no identity, origin unreadable) refuses.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from lab_commons.dev.branchset import BranchSetNotDeclared, declared_branchset
from lab_commons.dev.forgehosts import this_host
from lab_commons.dev.lanepolicy import Policy, load_policy
from lab_commons.dev.mergeaudit import MergeAuditError, judge
from lab_commons.dev.sessionlease import IDENTITY_ENV, LeaseRefused, identity, lease_branch, read, take
from lab_commons.log import emit

__all__ = [
    'MERGED_BRANCH',
    'P1',
    'P2',
    'P3',
    'P4',
    'main',
    'merged_branch',
    'refusals',
]

P1: Final = 'ONE-WRITER-PER-SESSION-BRANCH'
P2: Final = 'PUBLISH-IS-THE-LOCAL-REF'
P3: Final = 'SESSION-HISTORY-ONLY-GROWS'
P4: Final = 'INTEGRATION-IS-MERGES-ONLY'
#: The trailer an integration merge names its merged branch under.
MERGED_BRANCH: Final = 'Merged-Branch'

_GIT: Final = shutil.which('git') or 'git'
_HEADS: Final = 'refs/heads/'
_FIELDS: Final = 4
_PARENTS: Final = 2
_TRAILER: Final = re.compile(rf'^{MERGED_BRANCH}:\s*(\S+)\s*$', re.MULTILINE)
_MERGE: Final = 'python -m lab_commons.dev.integrate merge <branch>'


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
    if branch == policy.integration:
        found += _merges_only(root, policy, old, sha)
    return found


def _lease_refusals(root: Path, branches: set[str], who: str | None, now: datetime) -> list[str]:
    if who is None:
        return [f'{P1}: no session identity; set {IDENTITY_ENV[0]} (or push from inside an agent session)']
    found = []
    for branch in sorted(branches):
        take_it = f'python -m lab_commons.dev.sessionlease take {branch}'
        try:
            lease = read(root, branch)
        except LeaseRefused as refused:
            found.append(f'{P1}: {refused}')
            continue
        if lease is None:
            found.append(f'{P1}: {branch} has no lease on origin; take it first: {take_it}')
        elif not lease.live(now):
            found.append(f'{P1}: {lease.text()} -- EXPIRED; take it over: {take_it}')
        elif lease.holder != who:
            found.append(f'{P1}: {lease.text()}; you are {who}. Ask {lease.holder} to release it, or wait')
    return found


def refusals(root: Path, lines: str, *, who: str | None, now: datetime) -> tuple[list[str], set[str]]:
    """Every refusal for the push *lines* describe, and the lease branches it needs (renewed when it passes)."""
    try:
        declared = declared_branchset(root)
    except BranchSetNotDeclared as exc:
        return [
            f'{P1}: this checkout declares no readable branch set, so no session branch can be judged: {exc}'
        ], set()
    policy = load_policy(root)
    guarded = {f'{_HEADS}{name}' for name in declared.sessions | {declared.trunk}}
    found: list[str] = []
    leased: set[str] = set()
    for fields in (line.split() for line in lines.splitlines()):
        if len(fields) != _FIELDS or fields[2] not in guarded:
            continue
        found += _judge_ref(root, policy, fields)
        leased.add(lease_branch(root, fields[2][len(_HEADS) :]))
    if found or not leased:
        return found, leased
    return _lease_refusals(root, leased, who, now), leased


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push hook: git's ref lines on stdin; exit 1 refuses, 0 publishes (and renews the lease)."""
    del argv  # git passes the remote name and url; the lease is always judged on origin
    top = _git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.strip()
    root = Path(top or Path.cwd())
    who = identity()
    lines = '' if sys.stdin.isatty() else sys.stdin.read()
    found, leased = refusals(root, lines, who=who, now=datetime.now(UTC))
    if found:
        emit('\n'.join(['', *(f'  REFUSED: {line}' for line in found), '']), err=True)
        return 1
    for branch in sorted(leased):
        try:
            emit(f'[lease] renewed: {take(root, branch, who=str(who), where=this_host()).text()}')
        except LeaseRefused as refused:
            emit(f'[lease] not renewed (the push proceeds on the live lease): {refused}', err=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
