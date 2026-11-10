"""HOW FAR A LOCK'S FLOATED SIBLINGS LAG THEIR LINES -- a :func:`~dev_lab.dev.relock.floated` pin, counted.

:func:`floating_lag` counts how far a pin is behind its line (a treeless fetch of the line); :func:`within_window`
is that count at :data:`LAG_LIMIT`, THE one "current enough" (DECISION 14): the forge's ``lock/lag`` status and
PR-HEAD-IS-CURRENT (:mod:`dev_lab.dev.prcurrent`) both read it, so a sibling landing one commit does not make every
dependent open PR stale. It reads lock TEXT and never writes; :mod:`dev_lab.dev.relock` is the party
that moves a pin, these only judge one. A line that cannot be read is an :data:`~dev_lab.dev.lockcheck.UNRESOLVED`
sentence: it refuses, never admits.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.lockcheck import LOCK, UNRESOLVED
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.relock import SHORT, RelockFailed, floated

__all__ = ['LAG_LIMIT', 'floating_lag', 'within_window']

#: Commits a lock may pin a floated sibling behind that sibling's line and still be current enough. The relock pull
#: request follows every sibling push within a serve tick or two, so a carried lock lags a handful of commits at
#: most; twenty is about a working day of sibling merges -- past it, the relock is not carrying.
LAG_LIMIT: Final = 20


def _commits_behind(url: str, branch: str, sha: str) -> int:
    """How many commits *url*'s ``refs/heads/<branch>`` holds past *sha*; RAISES :class:`RelockFailed` when unread.

    A treeless fetch into a throwaway bare repository: the commit graph alone, never a checkout. A *sha* the line
    does not contain (a rewritten line) cannot be counted, and raises.
    """
    with tempfile.TemporaryDirectory(prefix='lock-lag-') as bare:

        def git(*argv: str) -> subprocess.CompletedProcess[str]:
            return _door.run(
                [_GIT, '-C', bare, *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
                check=False, timeout=_GIT_TIMEOUT_S, env=unlocated(),
            )  # fmt: skip

        git('init', '--quiet', '--bare')
        fetched = run_network_verb(
            [_GIT, '-C', bare, 'fetch', '--quiet', '--no-tags', '--filter=tree:0', url, f'refs/heads/{branch}'],
            timeout=300, env=unlocated(),
        )
        if not fetched.ok:
            msg = f'{url} {branch} could not be fetched: {fetched.remedy}'
            raise RelockFailed(msg)
        if git('merge-base', '--is-ancestor', sha, 'FETCH_HEAD').returncode != 0:
            msg = f'{sha[:SHORT]} is not on {url} {branch}'
            raise RelockFailed(msg)
        return int(git('rev-list', '--count', f'{sha}..FETCH_HEAD').stdout.strip() or 0)


def floating_lag(lock: str, limit: int, *, behind: Callable[[str, str, str], int] = _commits_behind) -> tuple[str, ...]:
    """Why lock text *lock* pins a :func:`floated` sibling more than *limit* commits behind its line; one each.

    A line that cannot be counted is an :data:`UNRESOLVED` sentence: it refuses, never admits.
    """
    found = []
    for one in floated(lock):
        try:
            lag = behind(one.url, one.branch, one.sha)
        except OSError as why:
            found.append(f'{UNRESOLVED}: {one.name}: {why}')
            continue
        if lag > limit:
            found.append(f'{LOCK} pins {one.name} {lag} commits behind its {one.branch} (limit {limit})')
    return tuple(found)


def within_window(lock: str, *, behind: Callable[[str, str, str], int] = _commits_behind) -> tuple[str, ...]:
    """:func:`floating_lag` at :data:`LAG_LIMIT`: why lock text *lock* is not current enough, one sentence each."""
    return floating_lag(lock, LAG_LIMIT, behind=behind)
