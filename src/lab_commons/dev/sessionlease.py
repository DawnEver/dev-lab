"""ONE-WRITER-PER-SESSION-BRANCH, the lease: which SESSION may advance a declared session branch, until when.

User ruling 2026-10-13: every session has one branch it leads, the integration branch included, and that
branch is protected -- by the SESSION, never by a host or a directory, because both move. A lease names:

* the HOLDER -- the session's identity (:func:`identity`): ``$LAB_COMMONS_SESSION`` (a declared session name,
  how a human or a long-lived role names itself), else ``$CLAUDE_CODE_SESSION_ID`` (the agent session);
* WHERE it last renewed -- the card name of that box (:func:`lab_commons.dev.forgehosts.this_host`). It is
  an observation the holder rewrites on every renewal, never a binding: the serve tick reads it to know
  whether the integration lease holder works here (:func:`holds_integration_here`);
* EXPIRES -- the renewal time plus ``[tool.lab_commons.branchset] lease_hours``.

WHERE IT LIVES: ``refs/leases/<branch>`` ON ORIGIN, a commit with the empty tree whose message carries the
three fields above. Origin is the one place every session, on every box, already reads and writes, and it
is the SAME remote the guarded branch lives on, so the push that the lease guards and the lease itself
cannot disagree about which server is the truth. No forge API, no token, no second service: a GitHub and a
Gitea origin behave the same.

COMPARE-AND-SWAP IS GIT'S OWN FAST-FORWARD RULE. Each new lease commit has the previous one as its parent,
and the write is a plain (never forced) push. Two sessions that read the same lease and both write: the
second push is a non-fast-forward and origin refuses it (:func:`write`). The lease's history therefore only
grows, and it is its own audit trail (``git log origin/refs/leases/<branch>``).

TAKEN, RENEWED, EXPIRED, TAKEN OVER: :func:`take` succeeds when there is no lease, the lease has expired, or
the caller already holds it (that is the renewal; the pre-push guard renews on every push to the branch, so
an active session never lapses). A lapsed lease means its holder is gone, and anyone may take it over.
:func:`release` hands it on at once. Expiry is judged on the reader's UTC clock; with leases measured in
hours, a skew of minutes moves nothing that matters.

The TRUNK has no lease of its own: it moves only by promotion, which the integration branch's holder does,
so the trunk is guarded by the integration branch's lease (:func:`lease_branch`).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from lab_commons.dev.branchset import BranchSet, BranchSetNotDeclared, declared_branchset
from lab_commons.dev.forgehosts import this_host
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.netverb import run_network_verb
from lab_commons.log import emit

__all__ = [
    'IDENTITY_ENV',
    'LEASES',
    'ORIGIN',
    'Lease',
    'LeaseRefused',
    'holds_integration_here',
    'identity',
    'lease_branch',
    'main',
    'read',
    'release',
    'take',
    'write',
]

#: The ref namespace a lease lives under, on origin: ``refs/leases/<branch>``.
LEASES: Final = 'refs/leases/'
#: The remote that is the shared truth for every lease, whatever remote a push targets.
ORIGIN: Final = 'origin'
#: Where a session's identity is read, in order: a declared session name, then the agent session id.
IDENTITY_ENV: Final = ('LAB_COMMONS_SESSION', 'CLAUDE_CODE_SESSION_ID')

_GIT: Final = shutil.which('git') or 'git'
_STAMP: Final = '%Y-%m-%dT%H:%M:%SZ'
_FIELD: Final = re.compile(r'^(Holder|Where|Expires): (\S+)$', re.MULTILINE)


class LeaseRefused(RuntimeError):
    """The lease could not be taken, renewed, released or read; the message names why and who holds it."""


@dataclass(frozen=True)
class Lease:
    """One lease commit on origin."""

    branch: str
    holder: str
    where: str
    expires: datetime
    sha: str

    def live(self, now: datetime) -> bool:
        """Whether the lease still binds at *now*."""
        return now < self.expires

    def text(self) -> str:
        """``<branch>: held by <holder> on <where> until <expires>``."""
        return f'{self.branch}: held by {self.holder} on {self.where} until {self.expires.strftime(_STAMP)}'


def identity(env: dict[str, str] | None = None) -> str | None:
    """The running session's name: the first non-empty of :data:`IDENTITY_ENV`, else ``None``."""
    source = os.environ if env is None else env
    return next((value for key in IDENTITY_ENV if (value := source.get(key, '').strip())), None)


def _git(root: Path, *args: str, data: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, '-C', str(root), *args],
        input=data,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=120,
    )


def _branchset(root: Path) -> BranchSet:
    try:
        return declared_branchset(root)
    except BranchSetNotDeclared as exc:
        raise LeaseRefused(str(exc)) from exc


def lease_branch(root: Path, branch: str) -> str:
    """The session branch whose lease guards *branch*: itself, or the integration branch for the trunk."""
    declared = _branchset(root)
    if branch == declared.trunk:
        return load_policy(root).integration
    if branch not in declared.sessions:
        msg = f'{branch} is not a declared session branch ([tool.lab_commons.branchset] sessions)'
        raise LeaseRefused(msg)
    return branch


def read(root: Path, branch: str) -> Lease | None:
    """The lease on *branch* as origin holds it now, or ``None`` when it has never been taken."""
    ref = LEASES + branch
    listed = _git(root, 'ls-remote', ORIGIN, ref)
    if listed.returncode != 0:
        msg = f'cannot read {ref} on {ORIGIN}: {listed.stderr.strip()}'
        raise LeaseRefused(msg)
    if not listed.stdout.strip():
        return None
    sha = listed.stdout.split()[0]
    if _git(root, 'cat-file', '-e', f'{sha}^{{commit}}').returncode != 0:
        fetched = _git(root, 'fetch', '-q', '--no-write-fetch-head', ORIGIN, ref)
        if fetched.returncode != 0:
            msg = f'cannot fetch {ref} from {ORIGIN}: {fetched.stderr.strip()}'
            raise LeaseRefused(msg)
    fields = dict(_FIELD.findall(_git(root, 'log', '-1', '--format=%B', sha).stdout))
    if set(fields) != {'Holder', 'Where', 'Expires'}:
        msg = f'{ref} at {sha[:12]} is not a lease commit (Holder/Where/Expires): {fields}'
        raise LeaseRefused(msg)
    expires = datetime.strptime(fields['Expires'], _STAMP).replace(tzinfo=UTC)
    return Lease(branch, fields['Holder'], fields['Where'], expires, sha)


def write(root: Path, branch: str, *, who: str, where: str, expires: datetime, parent: str | None) -> Lease:
    """Write a lease commit on top of *parent* and push it: compare-and-swap through fast-forward."""
    empty = _git(root, 'mktree', data='').stdout.strip()
    message = f'lease {branch}\n\nHolder: {who}\nWhere: {where or "-"}\nExpires: {expires.strftime(_STAMP)}\n'
    args = ['-c', 'user.name=lab-commons lease', '-c', 'user.email=lease@lab-commons', 'commit-tree', empty]
    made = _git(root, *args, *(['-p', parent] if parent else []), '-m', message)
    if made.returncode != 0:
        msg = f'cannot write the lease commit for {branch}: {made.stderr.strip()}'
        raise LeaseRefused(msg)
    sha = made.stdout.strip()
    pushed = run_network_verb([_GIT, 'push', '-q', ORIGIN, f'{sha}:{LEASES}{branch}'], cwd=root, timeout=120)
    if not pushed.ok:
        msg = f'the lease on {branch} moved while it was being written (or origin refused it): {pushed.remedy}'
        raise LeaseRefused(msg)
    return Lease(branch, who, where or '-', expires, sha)


def take(root: Path, branch: str, *, who: str, where: str, now: datetime | None = None) -> Lease:
    """Take, renew or take over the lease on *branch* for *who*; refused while another holds it live."""
    when = datetime.now(UTC) if now is None else now
    guarded = lease_branch(root, branch)
    if guarded != branch:
        msg = f'{branch} has no lease of its own: it is guarded by the lease on {guarded}'
        raise LeaseRefused(msg)
    current = read(root, branch)
    if current is not None and current.live(when) and current.holder != who:
        msg = f'{current.text()}; wait for it to expire, or ask {current.holder} to release it'
        raise LeaseRefused(msg)
    hours = _branchset(root).lease_hours
    parent = None if current is None else current.sha
    return write(root, branch, who=who, where=where, expires=when + timedelta(hours=hours), parent=parent)


def release(root: Path, branch: str, *, who: str, now: datetime | None = None) -> Lease:
    """End *who*'s lease on *branch* now, so another session may take it at once."""
    when = datetime.now(UTC) if now is None else now
    current = read(root, branch)
    if current is None or current.holder != who:
        held = 'nobody' if current is None else current.holder
        msg = f'{branch} is held by {held}, not {who}: only the holder releases a lease'
        raise LeaseRefused(msg)
    return write(root, branch, who=who, where=current.where, expires=when, parent=current.sha)


def holds_integration_here(root: Path, names: set[str], now: datetime | None = None) -> bool:
    """Whether the live holder of the integration branch's lease last renewed on one of *names*."""
    try:
        found = read(root, load_policy(root).integration)
    except LeaseRefused:
        return False
    return found is not None and found.live(datetime.now(UTC) if now is None else now) and found.where in names


def main(argv: list[str] | None = None) -> int:
    """``take|release <branch>`` as this session; ``show`` every declared session branch's lease."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.sessionlease', description=main.__doc__)
    parser.add_argument('verb', choices=('take', 'release', 'show'))
    parser.add_argument('branch', nargs='?')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.verb == 'show':
            now = datetime.now(UTC)
            for branch in sorted(_branchset(args.root).sessions):
                found = read(args.root, branch)
                state = 'no lease' if found is None else found.text() + ('' if found.live(now) else ' (EXPIRED)')
                emit(state if found else f'{branch}: {state}')
            return 0
        who = identity()
        if who is None:
            emit(f'[lease] no session identity: set {IDENTITY_ENV[0]} (or run inside an agent session)', err=True)
            return 1
        if args.branch is None:
            parser.error('take and release name a branch')
        done = (
            take(args.root, args.branch, who=who, where=this_host())
            if args.verb == 'take'
            else release(args.root, args.branch, who=who)
        )
    except LeaseRefused as refused:
        emit(f'[lease] REFUSED: {refused}', err=True)
        return 1
    emit(f'[lease] {done.text()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
