"""Commit statuses on the forge -- the door a result is PUBLISHED through (forge.md, layer C).

WHY A STATUS AND NOT A COMMENT OR A LABEL. A status is the forge's one record keyed by the exact
commit it is about, readable by every workstation without a clone. ONE NAME FOR A PLATFORM RESULT:
a part, posted under ``tests/<part>`` (:mod:`dev_lab.dev.platformparts`) -- by a cluster run
and by a local verify alike -- and a claim on one is a ``pending`` status in that same context
(:mod:`dev_lab.dev.forgetick`).

THE MAPPING IS THE VERDICT'S POLARITY, NOT A NEW ONE: PASS -> ``success``, FAIL -> ``failure``, and
INCONCLUSIVE -> ``error``, whose description is the verdict line and so NAMES it.

A VERDICT ABOUT A DIRTY TREE HAS NO COMMIT. :func:`verdict_commit` returns HEAD's sha only when the
tree was clean before the run, is clean after it, and HEAD did not move -- the conditions under which
the content address the verdict carries IS a reading of that commit's tree. Otherwise nothing is
posted, because a status is a claim about a commit and this run made none.

A STATUS CAN ONLY BE POSTED ON A COMMIT THE FORGE HOLDS, so a run's status is never posted from the
run directly: it is QUEUED and posted once the commit is on ``origin`` (:mod:`dev_lab.dev.forgeoutbox`,
which also raises when an attempted post fails).

PROVENANCE-FREE ON PURPOSE. CommitStatus descriptions are machine lines, length-limited by the forge, so no
``[machine · agent · branch]`` stamp is prepended; the forge records the token's login as ``creator``.
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import re
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import lab_commons.launch as _door
from lab_commons.hpc.testcells import TestCell
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion, Status

from dev_lab.dev._forge_journal import Durable, Probe
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S, Transport, forge_transport
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import GITHUB, Client, client_for

__all__ = [
    'CARRIED_FROM',
    'CITED_FROM',
    'DESCRIPTION_LIMIT',
    'DOCS_ONLY',
    'SAME_TREE',
    'STATES',
    'CommitStatus',
    'head_sha',
    'known_reds',
    'main',
    'resolve_commit',
    'state_for',
    'status_history',
    'status_list',
    'status_post',
    'status_show',
    'verdict_commit',
]

#: The states this door writes; ``error`` carries an INCONCLUSIVE verdict, ``pending`` a claim.
STATES: Final = ('success', 'failure', 'error', 'pending')

#: A carried status ends ``carried from <sha12>: docs-only`` -- DOCS-ONLY-CARRIES (dev_lab.dev.forgecarry);
#: a part posted under the retired ``every outcome carried by footprint`` still READS (OLD-SHAPE-READER).
CARRIED_FROM: Final = 'carried from'
DOCS_ONLY: Final = 'docs-only'

#: A part CITED from a stored record of the same tree ends ``cited from <sha12>: same tree`` (dev_lab.dev.verdictstore).
CITED_FROM: Final = 'cited from'
SAME_TREE: Final = 'same tree'

#: GitHub's description limit, the tighter of the two forges; a longer one is cut, never sent.
DESCRIPTION_LIMIT: Final = 140

#: A commit named in full, used as given; anything else is resolved through git.
_FULL_SHA: Final = re.compile(r'[0-9a-f]{40}')

#: How many failing node ids ``status show`` prints before it says how many it left out.
FAILING_LIMIT: Final = 20

_STATE_FOR: Final[dict[Conclusion, str]] = {
    Conclusion.PASS: 'success',
    Conclusion.FAIL: 'failure',
    Conclusion.INCONCLUSIVE: 'error',
}


@dataclass(frozen=True)
class CommitStatus:
    """One commit status, identical in shape whichever forge answered.

    ``id`` orders the posts on one commit (the forge assigns it ascending), ``creator`` is the login
    that posted it and ``created`` the FORGE's time it was posted (``None`` when the forge named none);
    none takes part in equality, which is about what the status SAYS.
    """

    context: str
    state: str
    description: str
    url: str
    id: int = field(default=0, compare=False)
    creator: str = field(default='', compare=False)
    created: datetime | None = field(default=None, compare=False)


def _status(raw: Mapping[str, Any]) -> CommitStatus:
    # Gitea answers the state as ``status``; GitHub as ``state``.
    state = raw.get('state') or raw.get('status') or ''
    return CommitStatus(
        raw.get('context') or '',
        state,
        raw.get('description') or '',
        raw.get('target_url') or '',
        int(raw.get('id') or 0),
        (raw.get('creator') or {}).get('login') or '',
        _forge_time(raw.get('created_at')),
    )


def _forge_time(stamp: object) -> datetime | None:
    """The forge's ``created_at`` as an aware UTC time; ``None`` when absent or unreadable."""
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).astimezone(UTC)
    except ValueError:
        return None


def state_for(outcome: Conclusion) -> str:
    """``success`` for PASS, ``failure`` for FAIL, ``error`` for INCONCLUSIVE."""
    return _STATE_FOR[outcome]


def _commit(sha: str) -> None:
    """Refuse an empty *sha*: formatted into a URL it reads ``statuses/``, which the forge refuses."""
    if not sha:
        msg = 'no commit sha: a status is read or posted on a commit'
        raise ValueError(msg)


def status_post(
    client: Client, sha: str, *, context: str, state: str, description: str, target_url: str = ''
) -> CommitStatus:
    """Post one status on *sha*. The description is cut to :data:`DESCRIPTION_LIMIT`, never sent long."""
    _commit(sha)
    if state not in STATES:
        msg = f'a status state is one of {STATES}, not {state!r}'
        raise ValueError(msg)
    body = {'state': state, 'context': context, 'description': description[:DESCRIPTION_LIMIT]}
    if target_url:
        body['target_url'] = target_url
    listed = f'{client.repo}/commits/{sha}/statuses' if client.backend is GITHUB else f'{client.repo}/statuses/{sha}'
    durable = Durable(
        key=f'status {sha} {context}',  # the newer status of one commit and context supersedes a queued older one
        probe=Probe(listed, {name: value for name, value in body.items() if name != 'state'}),
        until=time.time() if state == 'pending' else 0.0,  # a pending status is a lease: worth only its answer
    )
    return _status(client.call('POST', f'{client.repo}/statuses/{sha}', body, durable=durable))


def status_list(client: Client, sha: str) -> tuple[CommitStatus, ...]:
    """The LATEST status per context on *sha*, sorted by context.

    Both forges' LIST endpoint, never GitHub's combined one: only the list records each status's ``creator``,
    which the review gate verifies (D11). The newest (highest ``id``) per context is kept.
    """
    _commit(sha)
    path = f'{client.repo}/commits/{sha}/statuses' if client.backend is GITHUB else f'{client.repo}/statuses/{sha}'
    newest: dict[str, Mapping[str, Any]] = {}
    for item in sorted(client.call('GET', path), key=lambda item: item.get('id') or 0):
        newest[item.get('context') or ''] = item
    raw = list(newest.values())
    return tuple(sorted((_status(item) for item in raw), key=lambda status: status.context))


def status_history(client: Client, sha: str) -> tuple[CommitStatus, ...]:
    """EVERY status posted on *sha*, oldest first -- what a claim race is decided on (``id`` order)."""
    _commit(sha)
    path = f'{client.repo}/commits/{sha}/statuses' if client.backend is GITHUB else f'{client.repo}/statuses/{sha}'
    return tuple(sorted((_status(item) for item in client.call('GET', path)), key=lambda status: status.id))


def _git(root: Path, *args: str) -> str | None:
    done = _door.run(
        [_GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else None


def head_sha(root: Path) -> str | None:
    """HEAD's commit sha, or ``None`` when git cannot answer (no commit yet, not a checkout)."""
    return _git(root, 'rev-parse', '--verify', '-q', 'HEAD')


def verdict_commit(
    head_before: str | None,
    head_after: str | None,
    start: tuple[str, ...] | None,
    end: tuple[str, ...] | None,
) -> str | None:
    """The commit a verdict is ABOUT, or ``None`` when it is about no commit.

    *start*/*end* are :func:`dev_lab.dev.treedirt.status_paths` before and after the run. Only a
    tree clean at both readings, with HEAD unmoved, was HEAD's tree throughout -- anything else is a
    verdict about a working copy no commit holds.
    """
    if head_before is None or head_before != head_after or start != () or end != ():
        return None
    return head_before


#: A run record's file suffix (``lab_commons.hpc.records``: ``run-<sha>-<part>-<req>.json.gz``); any other target
#: -- an outage's Actions run page -- is no record, and fetching it as one reads the HTML page's 406.
RECORD_SUFFIX: Final = '.json.gz'


def _not_ok(status: CommitStatus, client: Client) -> tuple[dict[str, TestCell], int] | str:
    """``({node: cell} of every test not ``ok``, how many cells)`` in the record behind *status*, or why not read."""
    if not status.url:
        return '  no record is attached to this part'
    if not urlsplit(status.url).path.endswith(RECORD_SUFFIX):  # an outage's target is its run page, not a record
        return f'  no record is attached to this part; its target is {status.url}'
    try:
        record = json.loads(gzip.decompress(client.download(status.url)).decode('utf-8'))
    except (ForgeCallFailed, OSError, ValueError) as failed:
        return f'  the record at {status.url} could not be read ({failed}); open it by hand'
    cells = record.get('cells') or {}
    found = {node: TestCell.from_plain(plain) for node, plain in cells.items() if isinstance(plain, Mapping)}
    return {node: cell for node, cell in sorted(found.items()) if cell.status is not Status.OK}, len(cells)


def _red_lines(status: CommitStatus, client: Client, known: Mapping[str, frozenset[str]] | None) -> tuple[str, ...]:
    """Every test the record behind *status* does not call ``ok``, with its own word, or why it cannot say.

    With *known* (the base's not-ok nodes per part), each is labelled ``inherited`` (red on the base too) or ``NEW``.
    """
    read = _not_ok(status, client)
    if isinstance(read, str):
        return (read,)
    not_ok, total = read
    base = known.get(status.context) if known is not None else None

    def label(node: str) -> str:
        if known is None:
            return ''
        return '  inherited' if base is not None and node in base else '  NEW'

    nodes = list(not_ok)
    shown = [f'  - {node}  {not_ok[node].word()}{label(node)}' for node in nodes[:FAILING_LIMIT]]
    more = [f'  ... and {len(nodes) - FAILING_LIMIT} more'] if len(nodes) > FAILING_LIMIT else []
    tally = []
    if known is not None:
        new = sum(1 for node in nodes if label(node) == '  NEW')
        tally = [f'  against the base: {len(nodes) - new} inherited, {new} new']
    return (f'  not ok: {len(nodes)} of {total} test(s)', *tally, *shown, *more, f'  record: {status.url}')


def known_reds(client: Client, sha: str) -> dict[str, frozenset[str]]:
    """THE KNOWN REDS of *sha* (e.g. the integration tip): every part's not-ok node ids, read from its records.

    The one record an agent compares its own run against, so an inherited red is told from a new one; a part whose
    record cannot be read contributes nothing (every red against it then reads ``NEW`` -- never a false
    ``inherited``).
    """
    reds: dict[str, frozenset[str]] = {}
    for status in status_list(client, sha):
        read = _not_ok(status, client) if status.state != 'success' else ({}, 0)
        reds[status.context] = frozenset(read[0]) if not isinstance(read, str) else frozenset()
    return reds


def status_show(client: Client, sha: str, *, part: str = '', against: str = '') -> tuple[str, ...]:
    """``forge status show``: each part's verdict, and WHICH tests failed in it.

    A verdict line answers "is it green"; the reason it is red is in the record the status carries as its
    target URL (:mod:`dev_lab.dev.forgerecords`), one cell per test. *part* narrows the answer to one.
    *against* (a base sha, e.g. the integration tip) labels each red ``inherited`` or ``NEW``
    (:func:`known_reds`); ``show <integration tip>`` alone IS the list of the known reds.
    """
    known = known_reds(client, against) if against else None
    lines: list[str] = [f'against {against[:12]}: reds it carries too are inherited'] if against else []
    for status in status_list(client, sha):
        if part and status.context != part:
            continue
        lines.append(f'{status.context}  {status.state}  {status.description}')
        if status.state != 'success':
            lines += list(_red_lines(status, client, known))
    return tuple(lines if len(lines) > bool(against) else (f'{sha[:12]} carries no {part or "tests/<part>"} status',))


def resolve_commit(root: Path, name: str) -> str:
    """*name* as a commit sha: a full sha as given, else ``origin/<name>`` (a branch, e.g. ``integrate/main``)."""
    if _FULL_SHA.fullmatch(name):
        return name
    found = _git(root, 'rev-parse', '--verify', '-q', f'refs/remotes/origin/{name}^{{commit}}')
    found = found or _git(root, 'rev-parse', '--verify', '-q', f'{name}^{{commit}}')
    if not found:
        msg = f'{name!r} names no commit here (a sha, or a branch fetched from origin)'
        raise ValueError(msg)
    return found


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge status', description='commit statuses')
    verbs = parser.add_subparsers(dest='verb', required=True)
    post = verbs.add_parser('post')
    post.add_argument('sha')
    post.add_argument('--context', required=True)
    post.add_argument('--state', required=True, choices=STATES)
    post.add_argument('--description', default='')
    listing = verbs.add_parser('list')
    listing.add_argument('sha')
    showing = verbs.add_parser('show')
    showing.add_argument('sha')
    showing.add_argument('--part', default='', help='one context, e.g. tests/base; every part by default')
    showing.add_argument(
        '--against', default='', help='a base (sha or branch, e.g. integrate/main): label each red inherited or NEW'
    )
    for sub in (post, listing, showing):
        sub.add_argument('--json', action='store_true', help='print the normalized result as JSON')
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
) -> int:
    """``python -m dev_lab.dev.forge status post|list <sha> ...``; exit 1 with netverb's remedy on failure."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    client = client_for(Path.cwd() if cwd is None else cwd, env=env, transport=transport)
    try:
        if args.verb == 'post':
            found: tuple[CommitStatus, ...] = (
                status_post(client, args.sha, context=args.context, state=args.state, description=args.description),
            )
        elif args.verb == 'show':
            root = Path.cwd() if cwd is None else cwd
            sha = resolve_commit(root, args.sha)
            against = resolve_commit(root, args.against) if args.against else ''
            lines = status_show(client, sha, part=args.part, against=against)
            for line in lines if not args.json else ():
                emit(line)
            if args.json:
                emit(json.dumps({'sha': sha, 'part': args.part, 'against': against, 'lines': list(lines)}, indent=2))
            return 0
        else:
            found = status_list(client, args.sha)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    except ValueError as unnamed:
        emit(f'[forge] {unnamed}', err=True)
        return 2
    if args.json:
        data = [dataclasses.asdict(status) for status in found]
        emit(json.dumps(data[0] if args.verb == 'post' else data, indent=2))
    else:
        for status in found:
            emit(f'{status.context}  {status.state}  {status.description}')
    return 0
