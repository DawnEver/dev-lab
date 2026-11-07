"""HOW FAR A LOCK'S FLOATED SIBLINGS LAG THEIR LINES -- the two readings of a :func:`~dev_lab.dev.relock.floated` pin.

:func:`floating_stale` says a pin moved at all (an ``ls-remote`` per sibling, seconds); :func:`floating_lag` counts
how far (a treeless fetch of the line). Both read lock TEXT and never write; :mod:`dev_lab.dev.relock` is the party
that moves a pin, these only judge one. A line that cannot be read is an :data:`~dev_lab.dev.lockcheck.UNRESOLVED`
sentence: it refuses, never admits.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.lockcheck import LOCK, UNRESOLVED
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.relock import SHORT, RelockFailed, floated

__all__ = ['floating_lag', 'floating_stale']


def _line_head(url: str, branch: str) -> str:
    """The commit *url*'s ``refs/heads/<branch>`` holds now; RAISES :class:`RelockFailed` when it cannot be read."""
    report = run_network_verb([_GIT, 'ls-remote', url, f'refs/heads/{branch}'], timeout=120)
    sha = (report.attempts[-1].output.split() or [''])[0] if report.ok and report.attempts else ''
    if not sha:
        msg = f'{url} {branch} could not be read: {report.remedy or "no such branch"}'
        raise RelockFailed(msg)
    return sha


def floating_stale(lock: str, *, head: Callable[[str, str], str] = _line_head) -> tuple[str, ...]:
    """Why lock text *lock* lags a floated sibling's line, one sentence each; empty when every sibling is current.

    THE floating-head freshness reading (user ruling 2026-11-07): each :func:`floated` sibling's locked commit
    against *head* -- ``git ls-remote <url> refs/heads/<line>`` -- seconds, never a resolution. A line that cannot
    be read is a sentence too: it refuses, never admits.
    """
    found = []
    for one in floated(lock):
        try:
            now = head(one.url, one.branch)
        except OSError as why:
            found.append(f'{UNRESOLVED}: {one.name}: {why}')
            continue
        if now != one.sha:
            found.append(f'{LOCK} pins {one.name} at {one.sha[:SHORT]}, its {one.branch} is at {now[:SHORT]}')
    return tuple(found)


def _commits_behind(url: str, branch: str, sha: str) -> int:
    """How many commits *url*'s ``refs/heads/<branch>`` holds past *sha*; RAISES :class:`RelockFailed` when unread.

    A treeless fetch into a throwaway bare repository: the commit graph alone, never a checkout. A *sha* the line
    does not contain (a rewritten line) cannot be counted, and raises.
    """
    with tempfile.TemporaryDirectory(prefix='lock-lag-') as bare:

        def git(*argv: str) -> subprocess.CompletedProcess[str]:
            return _door.run(
                [_GIT, '-C', bare, *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
                check=False, timeout=_GIT_TIMEOUT_S,
            )  # fmt: skip

        git('init', '--quiet', '--bare')
        fetched = run_network_verb(
            [_GIT, '-C', bare, 'fetch', '--quiet', '--no-tags', '--filter=tree:0', url, f'refs/heads/{branch}'],
            timeout=300,
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

    The COUNTED companion of :func:`floating_stale`, over the same :func:`floated` reading: that one says a pin
    moved at all, this one says how far. A line that cannot be counted is an :data:`UNRESOLVED` sentence.
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
