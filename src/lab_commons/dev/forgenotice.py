"""FORGE NOTICES: when a PR head goes wrong, the session whose commits it carries is told -- once per (head, kind).

User ruling 2026-10-21. The serve tick's integration step (:func:`lab_commons.dev.forgeintegration.tick`, given
its host) asks :func:`kinds` of each open PR into integration, and records a :class:`Notice` per kind found:

* ``red`` -- a ``tests/<part>`` part is ``failure``/``error``, or auto-sync refused the head for a reason other
  than a conflict, a stack or a non-ephemeral branch;
* ``conflict`` -- the head conflicts with integration (the trial merge, or auto-sync's own refusal);
* ``stall`` -- the head's parts are still unsettled ``notice_stall`` (default ``"6 h"``) after it was committed.

A notice is ADDRESSED to every ``Lab-Session`` the PR's commits carry (:func:`lab_commons.dev.labsession.sessions`).
All of a PR's notices close when a later head is green (standing PASS) or the PR is merged.

WHERE IT LIVES. In the PR's ONE integration comment, as a hidden ``<!-- forge-notices {...} -->`` block beside the
visible lines: on the forge, so it survives the loss of any host, and in the one comment the tick already keeps,
so it is a single source with no new server and no second comment. :func:`read` and :func:`write` are its only
reader and writer; a tick without a host carries the block through unchanged.

ESCALATION. A notice no session is addressed by, or one whose head is still the PR's head ``notice_escalate``
(default ``"2 h"``) after it opened, is the integrator's (:func:`escalated`).
``python -m lab_commons.dev.forge notices [--session ID | --integrator] [--ack ID]`` prints the open ones.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit
from lab_commons.units import Q_

if TYPE_CHECKING:
    from lab_commons.dev.forgestatus import CommitStatus
    from lab_commons.dev.forgework import Client
    from lab_commons.dev.lanepolicy import Policy

__all__ = [
    'CONFLICT', 'RED', 'STALL', 'Block', 'Notice', 'duration', 'escalated', 'kinds', 'main', 'read', 'render',
    'update', 'write',
]  # fmt: skip

RED: Final = 'red'
CONFLICT: Final = 'conflict'
STALL: Final = 'stall'
#: The failing test ids a notice names, at most.
FIRST: Final = 5
_SHORT: Final = 12
_BLOCK: Final = re.compile(r'<!-- forge-notices (?P<json>\{.*?\}) -->', re.DOTALL)
_SYNC: Final = 'integration/sync'
#: Auto-sync refusals that are a wait, not a fault (forgeautosync's STACKED, NOT_EPHEMERAL), and a conflict.
_SYNC_NOT_RED: Final = ('waits behind', 'is not an ephemeral head', 'conflicts with')


def duration(key: str, text: str) -> timedelta:
    """*text* (the value of policy *key*) as a :class:`timedelta`; a bare number or a non-duration is refused."""
    try:
        quantity = Q_(text)
    except Exception as bad:
        msg = f'{key} {text!r} is not a duration; write one such as "2 h"'
        raise ValueError(msg) from bad
    if not isinstance(quantity, Q_) or not quantity.check('[time]'):
        msg = f'{key} {text!r} is not a duration (it needs a unit); write one such as "2 h"'
        raise ValueError(msg)
    return timedelta(seconds=float(quantity.m_as('s')))


@dataclass(frozen=True)
class Notice:
    """One notice: a PR head gone wrong in one way, addressed to the sessions its commits carry."""

    pr: int
    branch: str
    head: str
    kind: str
    sessions: tuple[str, ...]
    reason: str
    opened: str
    tests: tuple[str, ...] = ()
    link: str = ''
    acked: bool = False

    @property
    def id(self) -> str:
        """``<pr>-<head12>-<kind>``: one per (head, kind)."""
        return f'{self.pr}-{self.head[:_SHORT]}-{self.kind}'

    def line(self) -> str:
        """The notice in one line."""
        to = ', '.join(self.sessions) or 'unaddressed'
        tests = f'; failing: {", ".join(self.tests)}' if self.tests else ''
        link = f' ({self.link})' if self.link else ''
        where = f'#{self.pr} {self.branch} at {self.head[:_SHORT]}'
        return f'{self.id}: {where} {self.kind} -- {self.reason}{tests}{link} [{to}]'


@dataclass(frozen=True)
class Block:
    """A PR's notices, and the head the tick last saw (a notice on an older head has had a new push)."""

    head: str = ''
    notices: tuple[Notice, ...] = ()


def read(body: str) -> Block:
    """The notices block in comment *body*; empty when it has none."""
    found = _BLOCK.search(body)
    if found is None:
        return Block()
    raw = json.loads(found['json'])
    notices = tuple(
        Notice(**(item | {'sessions': tuple(item['sessions']), 'tests': tuple(item.get('tests', ()))}))
        for item in raw.get('notices', ())
    )
    return Block(raw.get('head', ''), notices)


def render(block: Block) -> str:
    """The visible lines and the hidden block for *block*; ``''`` when it holds no notice."""
    if not block.notices:
        return ''
    data = json.dumps({'head': block.head, 'notices': [dataclasses.asdict(n) for n in block.notices]})
    hidden = '<!-- forge-notices ' + data.replace('-->', '--\\u003e') + ' -->'
    return '\n'.join(['- forge notices:', *(f'  - {n.line()}' for n in block.notices), hidden])


def write(body: str, block: Block) -> str:
    """*body* with its notices replaced by *block* (visible lines and hidden block)."""
    kept = _BLOCK.sub('', body.split('\n- forge notices:', maxsplit=1)[0]).rstrip()
    rendered = render(block)
    return f'{kept}\n{rendered}' if rendered else kept


def kinds(
    statuses: Sequence[CommitStatus], *, conflicts: Sequence[str], settled: bool, age: timedelta, stall: timedelta
) -> dict[str, tuple[str, tuple[str, ...], str]]:
    """``{kind: (reason, failing test ids, record link)}`` for a head with *statuses*; empty when it is fine."""
    found: dict[str, tuple[str, tuple[str, ...], str]] = {}
    red = [s for s in statuses if s.context.startswith('tests/') and s.state in {'failure', 'error'}]
    sync = next((s for s in statuses if s.context == _SYNC and s.state in {'failure', 'error'}), None)
    if red:
        reason = '; '.join(f'{s.context} {s.state}: {s.description}' for s in red)
        found[RED] = (reason, tuple(s.context for s in red[:FIRST]), next((s.url for s in red if s.url), ''))
    elif sync is not None and not any(word in sync.description for word in _SYNC_NOT_RED):
        found[RED] = (f'auto-sync refused: {sync.description}', (), sync.url)
    if conflicts or (sync is not None and 'conflicts with' in sync.description):
        found[CONFLICT] = (f'conflicts with integration in {", ".join(conflicts) or "the head"}', (), '')
    if not settled and not red and age > stall:
        found[STALL] = (f'parts unsettled {int(age.total_seconds() // 60)} min after the commit', (), '')
    return found


def update(
    block: Block,
    *,
    pr: int,
    branch: str,
    head: str,
    found: Mapping[str, tuple[str, tuple[str, ...], str]],
    sessions: Sequence[str],
    green: bool,
    now: datetime,
) -> Block:
    """*block* after one tick: all closed when *green*, else one new notice per (head, kind) not yet recorded."""
    if green:
        return Block(head)
    have = {(n.head, n.kind) for n in block.notices}
    stamp = now.isoformat(timespec='seconds')
    new = tuple(
        Notice(pr, branch, head, kind, tuple(sorted(sessions)), reason, stamp, tests, link)
        for kind, (reason, tests, link) in found.items()
        if (head, kind) not in have
    )
    return Block(head, block.notices + new)


def escalated(notice: Notice, block: Block, now: datetime, escalate: timedelta) -> bool:
    """Whether *notice* is the integrator's: unaddressed, or no new push ``notice_escalate`` after it opened."""
    if not notice.sessions:
        return True
    return notice.head == block.head and now - datetime.fromisoformat(notice.opened) > escalate


def _blocks(client: Client, policy: Policy) -> list[tuple[int, Block, Any]]:
    from lab_commons.dev.forgepulls import Marker, comment_list, marker, pr_list  # noqa: PLC0415 (a leaf at import)

    line = marker(Marker.INTEGRATION)
    found = []
    for pr in pr_list(client):
        if pr.base != policy.integration:
            continue
        comment = next((c for c in comment_list(client, pr.number) if line in c.body), None)
        if comment is not None and (block := read(comment.body)).notices:
            found.append((pr.number, block, comment))
    return found


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge notices', description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group()
    who.add_argument('--session', default='', help='only the notices addressed to this Lab-Session (unacked)')
    who.add_argument('--integrator', action='store_true', help='only the unaddressed and escalated notices')
    parser.add_argument('--ack', default='', help='acknowledge the notice with this id')
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """``forge notices``: print the open notices; exit 0 when none, 1 when some, 2 when the forge fails."""
    from lab_commons.dev.forgework import ForgeCallFailed, client_for  # noqa: PLC0415
    from lab_commons.dev.lanepolicy import load_policy  # noqa: PLC0415

    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        origin, policy = client or client_for(root), load_policy(root)
        escalate = duration('notice_escalate', policy.notice_escalate)
        blocks = _blocks(origin, policy)
        if args.ack:
            return _ack(origin, blocks, args.ack)
    except (ForgeCallFailed, OSError, ValueError) as failed:
        emit(f'[notices] {failed}', err=True)
        return 2
    now = clock()
    shown = [
        notice
        for _, block, _ in blocks
        for notice in block.notices
        if (args.integrator and escalated(notice, block, now, escalate))
        or (args.session and args.session in notice.sessions and not notice.acked)
        or (not args.integrator and not args.session)
    ]
    for notice in shown:
        emit(notice.line())
    return 1 if shown else 0


def _ack(client: Client, blocks: Sequence[tuple[int, Block, Any]], wanted: str) -> int:
    for _, block, comment in blocks:
        if any(n.id == wanted for n in block.notices):
            acked = tuple(dataclasses.replace(n, acked=True) if n.id == wanted else n for n in block.notices)
            body = write(comment.body, Block(block.head, acked))
            client.call('PATCH', f'{client.repo}/issues/comments/{comment.id}', {'body': body})
            emit(f'acked {wanted}')
            return 0
    emit(f'[notices] no open notice {wanted}', err=True)
    return 2
