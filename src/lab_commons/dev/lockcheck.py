"""LOCKS RECORD, A SCHEDULE UPGRADES -- the pre-push check that a pushed commit's environment is pinned and fresh.

Decisions D8 and D20 of the distributed compute system: every family repo COMMITS ``uv.lock``, and the lock
does not freeze the environment, it RECORDS it. A host builds a commit's environment with ``uv sync --frozen``
from that lock (:mod:`lab_commons.dev.dep`), so two hosts on two days build the same revisions; "always the
latest" is the scheduled ``uv lock --upgrade`` (:mod:`lab_commons.dev.lockupgrade`), an explicit, tested event
instead of silent drift.

A PUSHED COMMIT IS REFUSED (:func:`lock_problems`, read at the pushed sha, never the working tree) when:

* it commits no ``uv.lock`` -- its environment is whatever its floating requirements resolve to on the day;
* a git requirement its manifest declares is not resolved in that lock to a commit -- it floats;
* its newest lock upgrade is older than ``[tool.lab_commons.integrator] lock_max_age_days`` (declared once,
  :class:`~lab_commons.dev.lanepolicy.Policy`). An upgrade is a commit carrying the :data:`TRAILER` trailer,
  which the upgrade job writes even when nothing moved: an unchanged lock that WAS upgraded is fresh, and a
  lock rewritten by ``uv lock`` after adding one dependency was not upgraded.

Exit codes: ``0`` allowed, ``1`` refused. Only ``refs/heads/**`` lines are judged; a deletion is allowed.
"""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.dev.forge import _GIT
from lab_commons.dev.installdoor import floating_in_manifest
from lab_commons.dev.lanepolicy import policy_from
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ['LOCK', 'REMEDY', 'TRAILER', 'lock_problems', 'locked_git', 'main', 'pushed_shas', 'upgraded_on']

#: The lockfile every family repo commits.
LOCK: Final = 'uv.lock'
#: The trailer an upgrade commit carries, valued with the day it ran: ``Lock-Upgraded: 2026-10-16``.
TRAILER: Final = 'Lock-Upgraded'
#: The one remedy for a missing, floating or stale lock.
REMEDY: Final = (
    f'`forge sync` to take the scheduled upgrade, or run `uv lock --upgrade` and commit {LOCK} with the trailer '
    f'`{TRAILER}: <yyyy-mm-dd>`'
)

_SHA40: Final = re.compile(r'^[0-9a-f]{40}$')
_DELETED: Final = '0' * 40
_BRANCHES: Final = 'refs/heads/'
_REFSPEC_FIELDS: Final = 4


def _show(root: Path, spec: str) -> str | None:
    done = _door.run(
        [_GIT, '-C', str(root), 'show', spec], capture_output=True, text=True, encoding='utf-8', check=False
    )
    return done.stdout if done.returncode == 0 else None


def _normal(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def locked_git(lock: str) -> dict[str, str]:
    """``{normalised name: commit}`` of every git source *lock* resolves; ``''`` for one carrying no commit."""
    found = {}
    for package in tomllib.loads(lock).get('package', []):
        source = package.get('source') if isinstance(package, dict) else None
        if isinstance(source, dict) and 'git' in source:
            commit = str(source['git']).partition('#')[2]
            found[_normal(str(package.get('name', '')))] = commit if _SHA40.match(commit) else ''
    return found


def upgraded_on(root: Path, rev: str) -> date | None:
    """The day of the newest commit reachable from *rev* carrying :data:`TRAILER`, ``None`` when none does."""
    done = _door.run(
        [_GIT, '-C', str(root), 'log', '-1', '--format=%cs', f'--grep=^{TRAILER}:', rev],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    day = done.stdout.strip()
    return date.fromisoformat(day) if done.returncode == 0 and day else None


def lock_problems(root: Path, sha: str, *, today: date) -> tuple[str, ...]:
    """Why commit *sha* of *root* may not be pushed, one sentence each; empty when its lock pins and is fresh."""
    lock = _show(root, f'{sha}:{LOCK}')
    if lock is None:
        return (f'{sha[:12]} commits no {LOCK}: its environment is whatever floats on the day',)
    manifest = _show(root, f'{sha}:pyproject.toml') or ''
    locked = locked_git(lock)
    out = [
        f'{name} is a git requirement {LOCK} does not resolve to a commit: it floats'
        for name in floating_in_manifest(manifest)
        if not locked.get(_normal(name))
    ]
    limit = policy_from(manifest, f'{sha[:12]}:pyproject.toml').lock_max_age_days
    upgraded = upgraded_on(root, sha)
    if upgraded is None:
        out.append(f'no commit reachable from {sha[:12]} carries `{TRAILER}:`: {LOCK} was never upgraded')
    elif (age := (today - upgraded).days) > limit:
        out.append(f'{LOCK} was last upgraded {upgraded.isoformat()}, {age} days ago, past lock_max_age_days={limit}')
    return tuple(out)


def pushed_shas(lines: Iterable[str]) -> tuple[str, ...]:
    """The local shas git's pre-push lines would put on a branch; deletions and non-branch refs are skipped."""
    found = []
    for line in lines:
        fields = line.split()
        if len(fields) == _REFSPEC_FIELDS and fields[1] != _DELETED and fields[2].startswith(_BRANCHES):
            found.append(fields[1])
    return tuple(dict.fromkeys(found))


def main(argv: Sequence[str] | None = None, *, lines: Iterable[str] | None = None, today: date | None = None) -> int:
    """``python -m lab_commons.dev.lockcheck [ROOT]`` -- the pre-push entry: refspec lines on stdin."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    if lines is None:
        lines = () if sys.stdin.isatty() else sys.stdin.read().splitlines()
    day = today or datetime.now(UTC).date()
    refused = [f'{sha[:12]}: {why}' for sha in pushed_shas(lines) for why in lock_problems(root, sha, today=day)]
    if not refused:
        return 0
    emit('[lock] REFUSED -- ' + '\n[lock]   '.join(refused) + f'\n[lock]   REMEDY: {REMEDY}.', err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
