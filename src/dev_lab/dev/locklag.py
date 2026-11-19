"""HOW FAR A COMMIT LAGS A LINE -- measured in TIME; a lock's :func:`~dev_lab.dev.relock.floated` pins, judged by it.

:func:`lag_of` is THE one measure of "behind": the first-parent landings a line holds that a commit lacks, aged from
the OLDEST of them (now minus its committer time). A line quiet for days does not make an old pin stale; a pin
passed over hours ago is, however few commits passed it. :data:`LAG_WINDOW` is THE one "current enough"
(DECISION 14), declared here once: the forge's ``lock/lag`` status (:func:`within_window` on a sibling's line) and
PR-HEAD-IS-CURRENT (:mod:`dev_lab.dev.prcurrent`: the forge's ``pr-current`` status, ``forge pr ready`` and the
pre-push row, on the repo's own integration AND the floated siblings) all read it. User ruling 2026-11-15: a
20-commit window expired within hours on a sibling landing 70+ commits a day, so it is a time window now. It reads
lock TEXT and never writes; :mod:`dev_lab.dev.relock` is the party that moves a pin, these only judge one. A line
that cannot be read is an :data:`~dev_lab.dev.lockcheck.UNRESOLVED` sentence naming the fetch: it refuses, never
admits.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

import lab_commons.launch as _door
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.lockcheck import LOCK, UNRESOLVED
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.relock import SHORT, RelockFailed, floated

__all__ = ['LAG_WINDOW', 'LOCAL_ONLY', 'Lag', 'floating_lag', 'hours', 'lag_of', 'within_window']

#: How long a line may hold a landing a commit lacks and the commit still be current enough -- THE one window. The
#: relock pull request follows every sibling push within a serve tick or two, so a carried lock lags minutes; past
#: this the relock is not carrying, or a head was not synced.
LAG_WINDOW: Final = timedelta(hours=8)

#: The graph reads after the one fetch stay LOCAL: a pin the treeless fetch does not hold must fail here, never start
#: git's lazy promisor fetch. That fetch is a grandchild network process: a timeout kills the local git, the
#: grandchild keeps the pipe open, and a pre-push hook waited hours for it (2026-11-13). ``GIT_NO_LAZY_FETCH``
#: needs git 2.45.
LOCAL_ONLY: Final = {'GIT_NO_LAZY_FETCH': '1'}

#: Runs one local git verb in a repository holding both commits.
Git = Callable[..., subprocess.CompletedProcess[str]]
#: Seconds since the epoch: the instant a lag is measured at.
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class Lag:
    """How far a commit is behind a line: the first-parent landings it lacks, and how long the oldest has stood."""

    landings: int
    age: timedelta

    def past(self, window: timedelta) -> bool:
        """Whether this lag is outside *window*."""
        return self.age > window

    def __str__(self) -> str:
        """The lag as a refusal names it: landings and hours."""
        return f'{self.landings} landings ({hours(self.age)})'


def hours(span: timedelta) -> str:
    """*span* as the hours a sentence names."""
    return f'{span.total_seconds() / 3600:.1f} h'


def lag_of(git: Git, sha: str, tip: str, *, now: Clock = time.time) -> Lag:
    """*tip*'s first-parent landings *sha* lacks, aged from the oldest; RAISES :class:`RelockFailed` when unread."""
    read = git('log', '--first-parent', '--format=%ct', f'{sha}..{tip}')
    if read.returncode != 0:
        msg = f'{sha[:SHORT]} cannot be measured against {tip}: {read.stderr.strip()}'
        raise RelockFailed(msg)
    stamps = [int(one) for one in read.stdout.split()]
    if not stamps:
        return Lag(0, timedelta(0))
    return Lag(len(stamps), timedelta(seconds=max(0.0, now() - min(stamps))))


def _behind(url: str, branch: str, sha: str, *, now: Clock = time.time) -> Lag:
    """:func:`lag_of` *sha* against *url*'s ``refs/heads/<branch>``; RAISES :class:`RelockFailed` when unread.

    A treeless fetch into a throwaway bare repository: the commit graph alone, never a checkout. A *sha* the line
    does not contain (a rewritten line) cannot be measured, and raises.
    """
    with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}lock-lag-') as bare:

        def git(*argv: str) -> subprocess.CompletedProcess[str]:
            return _door.run(
                [_GIT, '-C', bare, *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
                check=False, timeout=_GIT_TIMEOUT_S, env={**unlocated(), **LOCAL_ONLY},
            )  # fmt: skip

        git('init', '--quiet', '--bare')
        fetch = ['fetch', '--quiet', '--no-tags', '--filter=tree:0', url, f'refs/heads/{branch}']
        fetched = run_network_verb([_GIT, '-C', bare, *fetch], timeout=300, env=unlocated())
        if not fetched.ok:
            msg = f'{url} {branch} could not be fetched (`git {" ".join(fetch)}`): {fetched.remedy}'
            raise RelockFailed(msg)
        if git('merge-base', '--is-ancestor', sha, 'FETCH_HEAD').returncode != 0:
            msg = f'{sha[:SHORT]} is not on {url} {branch}'
            raise RelockFailed(msg)
        return lag_of(git, sha, 'FETCH_HEAD', now=now)


def floating_lag(lock: str, window: timedelta, *, behind: Callable[[str, str, str], Lag] = _behind) -> tuple[str, ...]:
    """Why lock text *lock* pins a :func:`floated` sibling past *window* behind its line; one sentence each.

    Each names the sibling and how far it is behind. A line that cannot be measured is an :data:`UNRESOLVED`
    sentence: it refuses, never admits.
    """
    found = []
    for one in floated(lock):
        try:
            lag = behind(one.url, one.branch, one.sha)
        except OSError as why:
            found.append(f'{UNRESOLVED}: {one.name}: {why}')
            continue
        if lag.past(window):
            found.append(f'{LOCK} pins {one.name} {lag} behind its {one.branch} (window {hours(window)})')
    return tuple(found)


def within_window(lock: str, *, behind: Callable[[str, str, str], Lag] = _behind) -> tuple[str, ...]:
    """:func:`floating_lag` at :data:`LAG_WINDOW`: why lock text *lock* is not current enough, one sentence each."""
    return floating_lag(lock, LAG_WINDOW, behind=behind)
