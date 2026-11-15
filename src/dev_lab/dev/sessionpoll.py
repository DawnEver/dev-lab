"""SESSION-HEARS-ITS-PRS, one read: a session PR as the forge holds it, its reds, its one green, and one poll.

The session watch (:mod:`dev_lab.dev.forgewatch`) and the machine watcher (:mod:`dev_lab.dev.prwatcher`) both
read a session's PRs through :func:`poll_session`; the ``Stop`` gate's red check reads :func:`pull_of` and
:func:`reds`. Each line said is recorded as heard (:func:`dev_lab.dev.sessionprs.hear`), so no reader repeats it.
"""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Final

from dev_lab.dev import sessionprs
from dev_lab.dev.forgecontexts import CONTEXT_PREFIX
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pr_by_head, pr_list
from dev_lab.dev.forgestatus import CommitStatus, status_list
from dev_lab.dev.platformparts import BASE

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from dev_lab.dev.forge import Forge
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['RED', 'REQUIRED', 'TESTS', 'green', 'poll_session', 'pull_of', 'reds']

_NOT_FOUND: Final = 404
#: The context prefix a part's verdict is posted under.
TESTS: Final = 'tests/'
#: The states a check reads red in, on both forges.
RED: Final = frozenset({'failure', 'error'})


def _branch(client: Client, name: str) -> dict | None:
    """The forge's record of branch *name*; ``None`` when it is gone."""
    try:
        return client.call('GET', f'{client.repo}/branches/{urllib.parse.quote(name, safe="/")}')
    except ForgeCallFailed as failed:
        if failed.report.attempts and failed.report.attempts[-1].returncode == _NOT_FOUND:
            return None
        raise


def pull_of(session: str, row: sessionprs.Row, client: Client) -> tuple[sessionprs.Row, PullRequest | None]:
    """*row*'s PR as the forge holds it, ``None`` when it has none.

    A branch row is resolved to its open PR, else to its newest PR into the default branch in any state (a
    merge no watch saw); with none, a protected or gone branch can never have one and the row is closed with
    the reason, while a live lane branch stays pending (:func:`~dev_lab.dev.sessionprs.pending_rows`).
    """
    if row.number:
        return row, client.pr_view(row.number)
    found = [pr for pr in pr_list(client) if pr.head == row.branch]
    pr = max(found, key=lambda one: one.number) if found else None
    if pr is None:
        pr = pr_by_head(client, row.branch, str(client.call('GET', client.repo)['default_branch']))
    if pr is not None:
        return sessionprs.resolve(session, row, pr.number), pr
    branch = _branch(client, row.branch)
    if branch is None:
        return sessionprs.close(session, row, 'closed', reason='the branch is gone and no PR had it as head'), None
    if branch.get('protected'):
        return sessionprs.close(session, row, 'closed', reason='a protected branch, never a PR head'), None
    return row, None


def reds(statuses: Sequence[CommitStatus]) -> list[CommitStatus]:
    """The red checks among *statuses*."""
    return [status for status in statuses if status.state in RED]


#: The contexts a head is never green without: the base test part, whatever else has already ended.
REQUIRED: Final = (f'{CONTEXT_PREFIX}{BASE}',)


def green(statuses: Sequence[CommitStatus]) -> bool | None:
    """THE ONE GREEN of both watches: every :data:`REQUIRED` context and every posted test status ended ``success``.

    ``False`` once a posted test status is red; ``None`` while a required context is absent or a test status pends
    (2026-11-14: the sha watch said ``green`` on ``tests/security`` alone while ``tests/base`` was unclaimed).
    """
    latest = {s.context: s.state for s in statuses if s.context.startswith(TESTS)}
    if any(state in RED for state in latest.values()):
        return False
    if all(c in latest for c in REQUIRED) and all(state == 'success' for state in latest.values()):
        return True
    return None


def _poll(session: str, row: sessionprs.Row, client: Client, say: Callable[[str], None], seen: set[str]) -> bool:
    """Say each new change on *row*; whether it is still open."""
    row, pr = pull_of(session, row, client)
    if pr is None:
        if row.done:
            _say_once(session, f'{row.key} {row.done}: {row.reason}', say, seen)
        return False
    if pr.merged or pr.state == 'closed':
        done = 'merged' if pr.merged else 'closed'
        sessionprs.close(session, row, done)
        _say_once(session, f'{row.key} {done}', say, seen)
        return False
    statuses = status_list(client, pr.head_sha) if pr.head_sha else ()
    lines = [f'{row.key} {pr.head_sha[:12]} {s.context} {s.state} {s.description}'.rstrip() for s in reds(statuses)]
    if green(statuses) is True:
        lines.append(f'{row.key} {pr.head_sha[:12]} green')
    for line in lines:
        _say_once(session, line, say, seen)
    return True


def _say_once(session: str, line: str, say: Callable[[str], None], seen: set[str]) -> None:
    """Say *line* unless this session already heard it (persisted: a re-armed watch repeats nothing)."""
    if line not in seen:
        seen.add(line)
        sessionprs.hear(session, line)
        say(line)


def poll_session(
    session: str, *, clients: Callable[[Forge], Client], say: Callable[[str], None], seen: set[str]
) -> int:
    """ONE read of every open or pending PR of *session*, saying each change not in *seen*; how many are still open.

    The session watch and the machine watcher (:mod:`dev_lab.dev.prwatcher`) both poll through it.
    """
    live = 0
    for row in (*sessionprs.open_rows(session), *sessionprs.pending_rows(session)):
        try:
            live += _poll(session, row, clients(row.forge), say, seen)
        except (ForgeCallFailed, ValueError) as failed:
            live += 1  # an unreadable PR is still open: read again next poll
            _say_once(session, f'{row.key} unreadable: {failed}'.splitlines()[0], say, seen)
    return live
