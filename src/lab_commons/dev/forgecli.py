"""``python -m lab_commons.dev.forge <noun> <verb>`` -- the one noun dispatch over the ``forge*`` doors.

``status`` for commit statuses, ``issue claim|status|comments|comments-since`` for derived issue
state and comment reads, ``auth`` for the token, ``publish`` for the status outbox, ``records`` for
run records, ``tick`` for requests and claims, ``queue`` for the read-only status view, ``route <record>``
for failure routing and ``serve`` for the whole harness sequence, ``sync`` / ``integration``
for the branch flow, ``tidy`` for declared issue hygiene, ``hosts retire HOST`` to drop a host card,
``request <producer> --sha <sha>`` to publish a request,
``pr close-landed [N...]`` to close landed PRs, ``notices`` for a session's PR notices; anything
else is the issue/PR door. The verbs
live in the sibling modules, which import :mod:`forge`, so :mod:`forge` reaches this module only from its
entry point.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.dev import (
    branchnotices,
    forgeauth,
    forgehosts,
    forgeintegration,
    forgeissue,
    forgenotice,
    forgeoutbox,
    forgepublish,
    forgequeue,
    forgerecords,
    forgeroute,
    forgeserve,
    forgestatus,
    forgesync,
    forgetick,
    forgetidy,
    pradmit,
    prlanded,
    servelock,
)
from lab_commons.dev.forge import Transport, https_transport
from lab_commons.dev.forgework import Client, Comment, ForgeCallFailed, Issue, PullRequest, client_for
from lab_commons.dev.labsession import ENV
from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['ISSUE_VERBS', 'NOUNS', 'issue_and_pr', 'main']

NOUNS: dict[str, Callable[[list[str]], int]] = {
    'auth': forgeauth.main,
    'status': forgestatus.main,
    'publish': forgeoutbox.main,
    'records': forgerecords.main,
    'route': forgeroute.main,
    'serve': lambda argv: servelock.locked(argv, forgeserve.main),
    'tick': forgetick.main,
    'queue': forgequeue.main,
    'sync': forgesync.main,
    'integration': forgeintegration.main,
    'notices': forgenotice.main,
    'tidy': forgetidy.main,
    'hosts': forgehosts.main,
    'request': forgepublish.main,
}

#: The ``issue`` verbs :mod:`forgeissue` owns; every other ``issue`` verb is the issue/PR door's.
ISSUE_VERBS = frozenset({'claim', 'status', 'comments', 'comments-since'})


def main(argv: Sequence[str]) -> int:
    """Route *argv* to the door owning its noun; returns that door's exit code."""
    args = list(argv)
    if args[:1] and (retired := refusal('forge', args[0])):
        emit(retired, err=True)
        return 2
    if args[:1] and args[0] in NOUNS:
        if refused := next(filter(None, (refusal(f'forge {args[0]}', w.split('=', 1)[0]) for w in args[1:])), None):
            emit(refused, err=True)
            return 2
        return NOUNS[args[0]](args[1:])
    if args[:2] == ['pr', 'close-landed']:
        return prlanded.main(args[2:])
    if args[:1] == ['issue'] and args[1:2] and args[1] in ISSUE_VERBS:
        return forgeissue.main(args[1:])
    return issue_and_pr(args)


def _verb(group: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    sub = group.add_parser(name)
    sub.add_argument('--json', action='store_true', help='print the normalized result as JSON')
    return sub


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='lab_commons.dev.forge',
        description='issue and PR verbs on the forge',
        epilog='also: pr close-landed [N...], issue claim|status N, status post|list SHA; token: auth login|status',
    )
    nouns = parser.add_subparsers(dest='noun', required=True)
    issue = nouns.add_parser('issue').add_subparsers(dest='verb', required=True)
    listing = _verb(issue, 'list')
    listing.add_argument('--state', choices=('open', 'closed', 'all'), default='open')
    listing.add_argument('--limit', type=int, default=30)
    for name in ('view', 'close'):
        _verb(issue, name).add_argument('number', type=int)
    create = _verb(issue, 'create')
    create.add_argument('--title', required=True)
    create.add_argument('--body', default='')
    comment = _verb(issue, 'comment')
    comment.add_argument('number', type=int)
    comment.add_argument('--body', required=True)
    pr = nouns.add_parser('pr').add_subparsers(dest='verb', required=True)
    _verb(pr, 'view').add_argument('number', type=int)
    opened = _verb(pr, 'create')
    opened.add_argument('--title', required=True)
    opened.add_argument('--body', default='')
    opened.add_argument('--head', required=True)
    opened.add_argument('--base', required=True)
    return parser


def _dispatch(client: Client, args: argparse.Namespace) -> Issue | PullRequest | Comment | tuple[Issue, ...]:
    verbs: dict[tuple[str, str], Callable[[], Issue | PullRequest | Comment | tuple[Issue, ...]]] = {
        ('issue', 'list'): lambda: client.issue_list(state=args.state, limit=args.limit),
        ('issue', 'view'): lambda: client.issue_view(args.number),
        ('issue', 'create'): lambda: client.issue_create(args.title, args.body),
        ('issue', 'comment'): lambda: client.issue_comment(args.number, args.body),
        ('issue', 'close'): lambda: client.issue_close(args.number),
        ('pr', 'create'): lambda: client.pr_create(args.title, args.body, head=args.head, base=args.base),
        ('pr', 'view'): lambda: client.pr_view(args.number),
    }
    return verbs[args.noun, args.verb]()


def _render(item: Issue | PullRequest | Comment) -> str:
    if isinstance(item, Comment):
        return item.url
    return f'#{item.number} [{item.state}] {item.title}  {item.url}'


def issue_and_pr(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``python -m lab_commons.dev.forge issue|pr <verb> ...`` (:mod:`forgework`); exit 1 with netverb's remedy."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    client = client_for(root, env=env, transport=transport)
    try:
        if (args.noun, args.verb) == ('pr', 'create') and (
            why := pradmit.create_refusal(root, client, head=args.head, base=args.base)
        ):
            emit(f'[forge] pr create REFUSED -- {why}', err=True)
            return 1
        result = _dispatch(client, args)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    items = result if isinstance(result, tuple) else (result,)
    if args.json:
        data = [dataclasses.asdict(item) for item in items]
        emit(json.dumps(data if isinstance(result, tuple) else data[0], indent=2))
    else:
        for item in items:
            emit(_render(item))
    if (args.noun, args.verb) == ('pr', 'create') and (
        said := branchnotices.report(
            root, [args.head], (os.environ if env is None else env).get(ENV, ''), client=client
        )
    ):
        emit(said, err=True)
    return 0
