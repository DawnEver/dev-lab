"""``python -m dev_lab.dev.forge watch <sha>...`` -- READ-ONLY: print commits' verdicts until one settles or a deadline.

It only reads commit statuses (:func:`dev_lab.dev.forgestatus.status_list`) and prints each change, one line
per ``tests/<part>`` context. SETTLED means at least one test status and none ``pending``. It ends on the FIRST
listed sha that settles (a session watching several pushed PRs wakes on each result, user ruling 2026-11-04):
exit 0 settled and every part ``success``, 1 settled with a red or an error, 3 when the deadline passed first.
It never posts, claims or cancels anything.

``--stream`` is the shape a Claude Code ``Monitor`` reads (PUSHED-HEAD-IS-WATCHED, :mod:`dev_lab.dev.pushwatch`):
ONE flushed line per status CHANGE of any context -- ``<sha12> <context> <state>`` -- and a last line
``<sha12> green|red|deadline``; a re-read status that did not change prints nothing.

``--session <id> --stream`` (SESSION-HEARS-ITS-PRS, user ruling 2026-11-11: lab-commons #158 went red and the
session heard nothing) watches every PR the session opened or pushed, in any repository, on either forge
(:mod:`dev_lab.dev.sessionprs`, its record): ONE line per change -- ``<key> <sha12> <context> failure|error
<description>``, ``<key> <sha12> green`` once every ``tests/*`` check is final and green, ``<key> merged`` /
``<key> closed`` once -- and exits 0 when none remains open, 3 at its deadline. :func:`unacknowledged_reds` is what
the ``Stop`` hook (:mod:`dev_lab.dev.pushstop`) refuses on, until a newer head is pushed or
``--ack <key> --reason <why>`` records why the red stands.

A WATCH YIELDS ITS VENV (2026-11-14): a watch runs from a venv for hours, so a queued
``dep --bootstrap --when-free`` (:mod:`dev_lab.dev._dep_pending`) of that venv makes it exit at its next poll
-- one line ``venv update pending ...: re-arm this watch`` and exit 4 -- instead of holding the update off.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.parse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import _dep_pending, sessionprs
from dev_lab.dev.forgecontexts import CONTEXT_PREFIX
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pr_by_head, pr_list
from dev_lab.dev.forgestatus import CommitStatus, status_list
from dev_lab.dev.forgework import Client, PullRequest, client_for, stored_client
from dev_lab.dev.platformparts import BASE
from dev_lab.dev.pushwatch import record_deadline

if TYPE_CHECKING:
    from dev_lab.dev.forge import Forge

__all__ = [
    'EVERY_S',
    'FLOOR_S',
    'RED',
    'TESTS',
    'YIELDED',
    'clients_at',
    'main',
    'session_main',
    'settled',
    'unacknowledged_reds',
    'watch',
    'watch_session',
]

_NOT_FOUND: Final = 404
#: The context prefix a part's verdict is posted under.
TESTS: Final = 'tests/'
_DEADLINE: Final = 3
#: The exit code of a watch that yielded its venv to a queued update; its session re-arms it.
YIELDED: Final = 4


def _update_waits() -> str:
    """The line a watch ends on when an update of the venv it runs from is queued, else ``''``."""
    if _dep_pending.pending(sys.prefix) is None:
        return ''
    return f'venv update pending for {sys.prefix}: this watch exits so it can run; re-arm this watch'


#: The default poll period, and the fastest ``--every-seconds`` honours. A verdict is claimed on a serve tick
#: (5 minutes by default) and takes minutes more, so a faster read only re-reads an unchanged list: on
#: 2026-11-04 one workstation's watches cost a 2-core Gitea host ~19 status reads a minute at 60 s.
EVERY_S: Final = 120.0
FLOOR_S: Final = 30.0


def settled(statuses: Sequence[CommitStatus]) -> bool:
    """Whether every test status is final and there is at least one."""
    tests = [s for s in statuses if s.context.startswith(TESTS)]
    return bool(tests) and all(s.state != 'pending' for s in tests)


def watch(
    client: Client,
    shas: Sequence[str],
    *,
    deadline_s: float,
    every_s: float,
    say: Callable[[str], None],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    stream: bool = False,
    yielding: Callable[[], str] = _update_waits,
) -> int:
    """Poll each of *shas*, printing each change, until one settles or *deadline_s* has passed (``--stream``: above)."""
    end, seen = clock() + deadline_s, set()
    while True:
        if why := yielding():
            say(why)
            return YIELDED
        for sha in shas:
            statuses = status_list(client, sha)
            for status in statuses:
                line = (
                    f'{sha[:12]} {status.context} {status.state}'
                    if stream or len(shas) > 1
                    else f'{status.context}: {status.state} {status.description}'
                )
                if (stream or status.context.startswith(TESTS)) and line not in seen:
                    seen.add(line)
                    say(line)
            if settled(statuses):
                green = all(s.state == 'success' for s in statuses if s.context.startswith(TESTS))
                if stream or len(shas) > 1:
                    say(f'{sha[:12]} {"green" if green else "red"}')
                return 0 if green else 1
        if clock() >= end:
            named = ' '.join(sha[:12] for sha in shas)
            say(f'{named} deadline' if stream else f'watch: {named} not settled by the deadline')
            return _DEADLINE
        sleep(every_s)


#: The states a check reads red in, on both forges.
RED: Final = frozenset({'failure', 'error'})
#: The session watch's poll period and floor: each open PR costs two reads per poll, and GitHub allows 5000 an hour.
SESSION_EVERY_S: Final = 90.0
SESSION_FLOOR_S: Final = 60.0


def clients_at(root: Path) -> Callable[[Forge], Client]:
    """One stored-credential client per repository, built once."""
    made: dict[Forge, Client] = {}

    def client(forge: Forge) -> Client:
        if forge not in made:
            made[forge] = stored_client(forge, cwd=root)
        return made[forge]

    return client


def _branch(client: Client, name: str) -> dict | None:
    """The forge's record of branch *name*; ``None`` when it is gone."""
    try:
        return client.call('GET', f'{client.repo}/branches/{urllib.parse.quote(name, safe="/")}')
    except ForgeCallFailed as failed:
        if failed.report.attempts and failed.report.attempts[-1].returncode == _NOT_FOUND:
            return None
        raise


def _pull(session: str, row: sessionprs.Row, client: Client) -> tuple[sessionprs.Row, PullRequest | None]:
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


def _reds(statuses: Sequence[CommitStatus]) -> list[CommitStatus]:
    return [status for status in statuses if status.state in RED]


#: The contexts a head is never green without: the base test part, whatever else has already ended.
REQUIRED: Final = (f'{CONTEXT_PREFIX}{BASE}',)


def _green(statuses: Sequence[CommitStatus]) -> bool:
    """Every required context and every posted test status ended in ``success``."""
    latest = {s.context: s.state for s in statuses if s.context.startswith(TESTS)}
    return all(c in latest for c in REQUIRED) and all(state == 'success' for state in latest.values())


def _poll(session: str, row: sessionprs.Row, client: Client, say: Callable[[str], None], seen: set[str]) -> bool:
    """Say each new change on *row*; whether it is still open."""
    row, pr = _pull(session, row, client)
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
    lines = [f'{row.key} {pr.head_sha[:12]} {s.context} {s.state} {s.description}'.rstrip() for s in _reds(statuses)]
    if _green(statuses):
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


def watch_session(
    session: str,
    *,
    clients: Callable[[Forge], Client],
    say: Callable[[str], None],
    every_s: float = SESSION_EVERY_S,
    deadline_s: float = 4 * 3600.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    yielding: Callable[[], str] = _update_waits,
) -> int:
    """Report each change on *session*'s open PRs until none is open (0) or *deadline_s* passed (3).

    While it runs it holds the session's liveness marker (:func:`~dev_lab.dev.sessionprs.watch`): the Stop gate
    reads it as "a watch is armed".
    """
    sessionprs.watch(session)
    try:
        return _session_loop(
            session,
            clients=clients,
            say=say,
            every_s=every_s,
            end=clock() + deadline_s,
            clock=clock,
            sleep=sleep,
            yielding=yielding,
        )
    finally:
        sessionprs.unwatch(session)


def _session_loop(
    session: str,
    *,
    clients: Callable[[Forge], Client],
    say: Callable[[str], None],
    every_s: float,
    end: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    yielding: Callable[[], str],
) -> int:
    seen = sessionprs.heard(session)
    while True:
        if why := yielding():
            say(why)
            return YIELDED
        live = 0
        for row in (*sessionprs.open_rows(session), *sessionprs.pending_rows(session)):
            try:
                live += _poll(session, row, clients(row.forge), say, seen)
            except (ForgeCallFailed, ValueError) as failed:
                live += 1  # an unreadable PR is still open: read again next poll
                _say_once(session, f'{row.key} unreadable: {failed}'.splitlines()[0], say, seen)
        if not live:
            say(f'session {session}: no open PR left')
            return 0
        if clock() >= end:
            say(f'session {session}: deadline, {live} PR(s) still open')
            return _DEADLINE
        sleep(every_s)


def unacknowledged_reds(session: str, *, clients: Callable[[Forge], Client]) -> list[str]:
    """``<pr url> <sha12> <context> <state>`` per red check on a session PR head no reason was recorded for.

    Raises :class:`ForgeCallFailed`/``ValueError`` when a forge cannot answer.
    """
    said = []
    for recorded in sessionprs.open_rows(session):
        client = clients(recorded.forge)
        row, pr = _pull(session, recorded, client)
        if pr is None or pr.merged or pr.state == 'closed' or not pr.head_sha or pr.head_sha in row.acks:
            continue
        said += [f'{pr.url} {pr.head_sha[:12]} {s.context} {s.state}' for s in _reds(status_list(client, pr.head_sha))]
    return said


#: A PR's web URL: ``https://<host>/<owner>/<repo>/pull[s]/<number>`` (GitHub, Gitea).
_PR_URL: Final = re.compile(r'^https?://([^/]+)/([^/]+)/([^/]+)/pulls?/(\d+)/?$')


def pr_key(named: str) -> str:
    """*named* as a session PR key: a PR URL becomes ``<host>/<owner>/<repo>#<number>``; anything else is kept."""
    found = _PR_URL.match(named.strip())
    return f'{found[1]}/{found[2]}/{found[3]}#{found[4]}' if found else named.strip()


def _ack(session: str, key: str, reason: str, clients: Callable[[Forge], Client]) -> int:
    key = pr_key(key)
    found = [row for row in sessionprs.rows(session).values() if key in {row.key, f'#{row.number}', str(row.number)}]
    if len(found) != 1:
        emit(f'watch: {key!r} names {len(found)} PR(s) of session {session}; give the key it prints', err=True)
        return 2
    row, pr = _pull(session, found[0], clients(found[0].forge))
    if pr is None or not pr.head_sha or row.done:
        emit(f'watch: {row.key} has no open PR head to acknowledge', err=True)
        return 2
    sessionprs.ack(session, row, pr.head_sha, reason)
    emit(f'{row.key} {pr.head_sha[:12]} acknowledged: {reason}')
    return 0


def session_main(argv: Sequence[str] | None = None, *, clients: Callable[[Forge], Client] | None = None) -> int:
    """``forge watch --session <id> --stream [--every-seconds S]``, or ``--ack <key> --reason <why>``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge watch --session', description=session_main.__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--stream', action='store_true', help='one flushed line per change, for a Monitor')
    parser.add_argument(
        '--every-seconds', type=float, default=SESSION_EVERY_S, help=f'poll period (floor {SESSION_FLOOR_S:g})'
    )
    parser.add_argument('--deadline-minutes', type=float, default=240.0)
    parser.add_argument(
        '--ack', default='', help="a PR's key (host/owner/repo#N), URL or number: let the red on its current head stand"
    )
    parser.add_argument('--reason', default='', help='why the red stands (required with --ack)')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not sessionprs.valid(args.session):
        parser.error(f'--session {args.session!r} is not a session id')
    if args.ack and not args.reason.strip():
        parser.error('--ack: --reason must say why the red stands')
    made = clients or clients_at(Path.cwd())
    if args.ack:
        try:
            return _ack(args.session, args.ack, args.reason.strip(), made)
        except (ForgeCallFailed, ValueError) as failed:
            emit(f'watch: {failed}', err=True)
            return 2
    return watch_session(
        args.session,
        clients=made,
        say=lambda line: emit(line, flush=True),
        every_s=max(args.every_seconds, SESSION_FLOOR_S),
        deadline_s=args.deadline_minutes * 60,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """``forge watch <sha>... [--deadline-minutes M] [--every-seconds S] [--stream]``; ``--session``: the PRs'."""
    if any(word.startswith('--session') for word in (sys.argv[1:] if argv is None else argv)):
        return session_main(argv)
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge watch', description=main.__doc__)
    parser.add_argument('sha', nargs='+')
    parser.add_argument('--deadline-minutes', type=float, default=120.0)
    parser.add_argument('--every-seconds', type=float, default=EVERY_S, help=f'poll period (floor {FLOOR_S:g})')
    parser.add_argument('--stream', action='store_true', help='one flushed line per status change, for a Monitor')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        done = watch(
            client_for(Path.cwd()),
            args.sha,
            deadline_s=args.deadline_minutes * 60,
            every_s=max(args.every_seconds, FLOOR_S),
            say=lambda line: emit(line, flush=True),
            stream=args.stream,
        )
    except (ForgeCallFailed, ValueError) as failed:
        emit(f'watch: {failed}', err=True)
        return 2
    if done == _DEADLINE:  # the Stop gate releases a head whose watch ran out (pushstop)
        for sha in args.sha:
            record_deadline(Path.cwd(), sha)
    return done
