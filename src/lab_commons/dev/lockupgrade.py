"""THE SCHEDULED LOCK UPGRADE -- ``uv lock --upgrade`` as a request job, committed on the declared update branch.

Decision D20: the lock RECORDS, a schedule UPGRADES. Nothing here is a scheduler. Two halves:

* :func:`schedule`, called by every ``forge serve`` tick (any host; idempotent), opens a REQUEST for the producer
  :data:`PRODUCER` at the head of ``origin/<integration>`` when one is :func:`due` -- the last upgrade is a day
  old, or a git source the lock pins has moved on its remote (a family repo's main moved). It runs only for a
  repo that DECLARES the producer, as data, beside its other requests::

      [tool.lab_commons.requests.lock_upgrade]
      argv = ["-m", "lab_commons.dev.lockupgrade"]
      needs = []
      cpu = 1
      mem_gb = 2
      wall_h = 1

  and names its update branch once, ``[tool.lab_commons.branchset] update = "update/lock"``.
* :func:`main` IS that producer. The request path runs it in a tree at the sha (:mod:`lab_commons.dev.shatree`);
  it continues the update branch (merging the sha into it, the sha's lock winning a conflict), runs
  ``uv lock --upgrade``, commits with the :data:`~lab_commons.dev.lockcheck.TRAILER` trailer -- an empty commit
  when nothing moved, because "upgraded and unchanged" is a fact the push check reads -- and pushes. The forge
  then tests the branch like any child, and the integrator merges it when green.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.dev.branchset import BranchSetNotDeclared, branchset_at, declared_branchset
from lab_commons.dev.forge import _GIT
from lab_commons.dev.forgepublish import publish
from lab_commons.dev.forgerequest import UndeclaredRequest, declared_request
from lab_commons.dev.forgeschedule import load_schedule
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.lockcheck import LOCK, TRAILER, upgraded_on
from lab_commons.dev.netverb import run_network_verb
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from lab_commons.dev.forgework import Client

__all__ = ['CADENCE_DAYS', 'PRODUCER', 'due', 'main', 'moved_sources', 'schedule', 'serve_tick']

#: The request producer name a repo declares to be upgraded.
PRODUCER: Final = 'lock_upgrade'
#: How many days pass between two upgrades when no pinned source moved: daily.
CADENCE_DAYS: Final = 1
#: How long one ``git ls-remote`` may take, in seconds.
_REACH_S: Final = 60.0


def _git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', check=False)


def _rev(root: Path, ref: str) -> str:
    done = _git(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}')
    return done.stdout.strip() if done.returncode == 0 else ''


def moved_sources(lock: str, *, tip: Callable[[str], str]) -> tuple[str, ...]:
    """The git source urls in *lock* whose remote tip (*tip* of the url, ``''`` unknown) is not the pinned commit."""
    moved = []
    for package in tomllib.loads(lock).get('package', []):
        source = package.get('source') if isinstance(package, dict) else None
        if not isinstance(source, dict) or 'git' not in source:
            continue
        body, _, commit = str(source['git']).partition('#')
        url = body.partition('?')[0]
        now = tip(url)
        if now and now != commit:
            moved.append(url)
    return tuple(dict.fromkeys(moved))


def _remote_tip(url: str) -> str:
    quiet = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}
    try:
        done = subprocess.run(
            [_GIT, 'ls-remote', '-q', url, 'HEAD'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=_REACH_S, env=quiet,
            check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return ''
    return done.stdout.split()[0] if done.returncode == 0 and done.stdout.strip() else ''


def due(root: Path, head: str, update: str, *, today: date, tip: Callable[[str], str] = _remote_tip) -> str:
    """Why an upgrade is due for integration head *head*, ``''`` when it is not.

    The last upgrade is the newest :data:`~lab_commons.dev.lockcheck.TRAILER` commit on *head* or on
    ``origin/<update>`` (a run not yet merged still counts: it is waiting for its tests, not missing).
    """
    days = [
        day for rev in (head, _rev(root, f'refs/remotes/origin/{update}')) if rev and (day := upgraded_on(root, rev))
    ]
    if not days:
        return f'{LOCK} was never upgraded'
    last = max(days)
    if (today - last).days >= CADENCE_DAYS:
        return f'{LOCK} was last upgraded {last.isoformat()}'
    shown = _git(root, 'show', f'{head}:{LOCK}')
    moved = moved_sources(shown.stdout, tip=tip) if shown.returncode == 0 else ()
    return f'{", ".join(moved)} moved past the lock' if moved else ''


def schedule(root: Path, client: Client, *, label: str, today: date, tip: Callable[[str], str] = _remote_tip) -> str:
    """Open the :data:`PRODUCER` request at ``origin/<integration>``'s head when :func:`due`; one line saying what.

    Nothing is opened for a repo that does not declare the producer or an update branch, nor while an open
    request for this producer at this head already exists.
    """
    integration = load_policy(root).integration
    head = _rev(root, f'refs/remotes/origin/{integration}')
    if not head:
        return f'no origin/{integration} to upgrade'
    try:
        declared_request(root, head, PRODUCER)
        update = branchset_at(root, head).update
    except (UndeclaredRequest, BranchSetNotDeclared):
        return ''
    if not update:
        return f'{PRODUCER} is declared and [tool.lab_commons.branchset] names no update branch'
    if not (why := due(root, head, update, today=today, tip=tip)):
        return ''
    title = f'request {PRODUCER} at {head[:12]}'
    if any(issue.title == title for issue in client.issue_list(state='open', limit=50)):
        return ''
    issue = publish(root, client, PRODUCER, head, label=label)
    return f'#{issue.number} {title}: {why}'


def serve_tick(root: Path, client: Client, *, today: date, say: Callable[[str], None]) -> None:
    """A serve tick's call: :func:`schedule` under the repo's request label; a forge or git failure is said."""
    try:
        if line := schedule(root, client, label=load_schedule(root).request_label, today=today):
            say(f'[serve] lock upgrade: {line}')
    except (ForgeCallFailed, OSError, ValueError) as failed:
        say(f'[serve] the lock upgrade was not scheduled: {failed}')


def _must(root: Path, *argv: str) -> str:
    done = _git(root, *argv)
    if done.returncode:
        msg = f'git {" ".join(argv)} exited {done.returncode}: {done.stderr.strip()}'
        raise OSError(msg)
    return done.stdout


def _network(root: Path, *argv: str) -> None:
    """``git <argv>`` against origin, retried then reported (:mod:`lab_commons.dev.netverb`); raises when it fails."""
    report = run_network_verb([_GIT, *argv], cwd=root, timeout=300)
    if not report.ok:
        raise OSError(report.remedy)


def _continue(root: Path, branch: str, sha: str) -> None:
    """Check out *branch* holding *sha*: from origin's branch with *sha* merged in, else at *sha*."""
    remote = _rev(root, f'refs/remotes/origin/{branch}')
    ahead = remote and _git(root, 'merge-base', '--is-ancestor', remote, sha).returncode != 0
    _must(root, 'checkout', '-q', '-B', branch, remote if ahead else sha)
    if not ahead:
        return
    if _git(root, 'merge', '--no-edit', '-q', sha).returncode == 0:
        return
    _must(root, 'checkout', sha, '--', LOCK)  # the branch only ever changes the lock: the sha's wins, re-upgraded
    _must(root, 'add', LOCK)
    _must(root, 'commit', '-q', '--no-edit')


def _uv_upgrade(root: Path) -> int:
    argv = [shutil.which('uv') or 'uv', 'lock', '--upgrade', '--project', str(root)]
    return subprocess.run(argv, check=False).returncode


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    today: date | None = None,
    relock: Callable[[Path], int] = _uv_upgrade,
) -> int:
    """The producer: upgrade the lock of the tree in *cwd* (*relock*) and push it on the declared update branch."""
    del argv
    root = Path.cwd() if cwd is None else cwd
    day = today or datetime.now(UTC).date()
    try:
        update = declared_branchset(root).update
        if not update:
            emit('[lock-upgrade] [tool.lab_commons.branchset] names no update branch', err=True)
            return 2
        sha = _must(root, 'rev-parse', 'HEAD').strip()
        _network(root, 'fetch', '-q', 'origin')
        _continue(root, update, sha)
        if relock(root):
            emit(f'[lock-upgrade] uv lock --upgrade failed in {root}', err=True)
            return 1
        _must(root, 'add', LOCK)
        _must(root, 'commit', '-q', '--allow-empty', '-m', 'chore(deps): uv lock --upgrade', '-m', f'{TRAILER}: {day}')
        _network(root, 'push', 'origin', f'refs/heads/{update}')
    except (OSError, BranchSetNotDeclared) as failed:
        emit(f'[lock-upgrade] {failed}', err=True)
        return 1
    emit(f'[lock-upgrade] {update} upgraded at {_rev(root, "HEAD")[:12]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
