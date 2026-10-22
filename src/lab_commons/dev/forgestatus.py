"""Commit statuses on the forge -- the door a result is PUBLISHED through (forge.md, layer C).

WHY A STATUS AND NOT A COMMENT OR A LABEL. A status is the forge's one record keyed by the exact
commit it is about, readable by every workstation without a clone. ONE NAME FOR A PLATFORM RESULT:
a part, posted under ``tests/<part>`` (:mod:`lab_commons.dev.platformparts`) -- by a cluster run
and by a local verify alike -- and a claim on one is a ``pending`` status in that same context
(:mod:`lab_commons.dev.forgetick`).

THE MAPPING IS THE VERDICT'S POLARITY, NOT A NEW ONE: PASS -> ``success``, FAIL -> ``failure``, and
INCONCLUSIVE -> ``error``, whose description is the verdict line and so NAMES it.

A VERDICT ABOUT A DIRTY TREE HAS NO COMMIT. :func:`verdict_commit` returns HEAD's sha only when the
tree was clean before the run, is clean after it, and HEAD did not move -- the conditions under which
the content address the verdict carries IS a reading of that commit's tree. Otherwise nothing is
posted, because a status is a claim about a commit and this run made none.

A STATUS CAN ONLY BE POSTED ON A COMMIT THE FORGE HOLDS, so a run's status is never posted from the
run directly: it is QUEUED and posted once the commit is on ``origin`` (:mod:`lab_commons.dev.forgeoutbox`,
which also raises when an attempted post fails).

PROVENANCE-FREE ON PURPOSE. CommitStatus descriptions are machine lines, length-limited by the forge, so no
``[machine · agent · branch]`` stamp is prepended; the forge records the token's login as ``creator``.
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.dev._forge_journal import Durable, Probe
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, Transport, https_transport
from lab_commons.dev.forgework import GITHUB, Client, ForgeCallFailed, client_for
from lab_commons.hpc.testcells import TestCell
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion, Status

__all__ = [
    'CARRIED_FROM',
    'DESCRIPTION_LIMIT',
    'DOCS_ONLY',
    'STATES',
    'CommitStatus',
    'head_sha',
    'main',
    'state_for',
    'status_history',
    'status_list',
    'status_post',
    'status_show',
    'verdict_commit',
]

#: The states this door writes; ``error`` carries an INCONCLUSIVE verdict, ``pending`` a claim.
STATES: Final = ('success', 'failure', 'error', 'pending')

#: A carried status ends ``carried from <sha12>: docs-only`` -- DOCS-ONLY-CARRIES (lab_commons.dev.forgecarry);
#: a part posted under the retired ``every outcome carried by footprint`` still READS (FORMATS-UPGRADE-ON-READ).
CARRIED_FROM: Final = 'carried from'
DOCS_ONLY: Final = 'docs-only'

#: GitHub's description limit, the tighter of the two forges; a longer one is cut, never sent.
DESCRIPTION_LIMIT: Final = 140

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

    ``id`` orders the posts on one commit (the forge assigns it ascending) and ``creator`` is the login
    that posted it; neither takes part in equality, which is about what the status SAYS.
    """

    context: str
    state: str
    description: str
    url: str
    id: int = field(default=0, compare=False)
    creator: str = field(default='', compare=False)


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
    )


def state_for(outcome: Conclusion) -> str:
    """``success`` for PASS, ``failure`` for FAIL, ``error`` for INCONCLUSIVE."""
    return _STATE_FOR[outcome]


def status_post(
    client: Client, sha: str, *, context: str, state: str, description: str, target_url: str = ''
) -> CommitStatus:
    """Post one status on *sha*. The description is cut to :data:`DESCRIPTION_LIMIT`, never sent long."""
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

    GitHub's combined endpoint already answers latest-per-context; Gitea's list carries every post,
    so the newest (highest ``id``) per context is kept.
    """
    if client.backend is GITHUB:
        raw = client.call('GET', f'{client.repo}/commits/{sha}/status')['statuses']
    else:
        listed = client.call('GET', f'{client.repo}/statuses/{sha}')
        newest: dict[str, Mapping[str, Any]] = {}
        for item in sorted(listed, key=lambda item: item.get('id') or 0):
            newest[item.get('context') or ''] = item
        raw = list(newest.values())
    return tuple(sorted((_status(item) for item in raw), key=lambda status: status.context))


def status_history(client: Client, sha: str) -> tuple[CommitStatus, ...]:
    """EVERY status posted on *sha*, oldest first -- what a claim race is decided on (``id`` order)."""
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

    *start*/*end* are :func:`lab_commons.dev.treedirt.status_paths` before and after the run. Only a
    tree clean at both readings, with HEAD unmoved, was HEAD's tree throughout -- anything else is a
    verdict about a working copy no commit holds.
    """
    if head_before is None or head_before != head_after or start != () or end != ():
        return None
    return head_before


def _red_lines(status: CommitStatus, client: Client) -> tuple[str, ...]:
    """Every test the record behind *status* does not call ``ok``, with its own word, or why it cannot say."""
    if not status.url:
        return ('  no record is attached to this part',)
    try:
        record = json.loads(gzip.decompress(client.download(status.url)).decode('utf-8'))
    except (ForgeCallFailed, OSError, ValueError) as failed:
        return (f'  the record at {status.url} could not be read ({failed}); open it by hand',)
    cells = record.get('cells') or {}
    not_ok = sorted(
        (node, TestCell.from_plain(plain))
        for node, plain in cells.items()
        if isinstance(plain, Mapping) and TestCell.from_plain(plain).status is not Status.OK
    )
    shown = [f'  - {node}  {cell.word()}' for node, cell in not_ok[:FAILING_LIMIT]]
    more = [f'  ... and {len(not_ok) - FAILING_LIMIT} more'] if len(not_ok) > FAILING_LIMIT else []
    return (f'  not ok: {len(not_ok)} of {len(cells)} test(s)', *shown, *more, f'  record: {status.url}')


def status_show(client: Client, sha: str, *, part: str = '') -> tuple[str, ...]:
    """``forge status show``: each part's verdict, and WHICH tests failed in it.

    A verdict line answers "is it green"; the reason it is red is in the record the status carries as its
    target URL (:mod:`lab_commons.dev.forgerecords`), one cell per test. *part* narrows the answer to one.
    """
    lines: list[str] = []
    for status in status_list(client, sha):
        if part and status.context != part:
            continue
        lines.append(f'{status.context}  {status.state}  {status.description}')
        if status.state != 'success':
            lines += list(_red_lines(status, client))
    return tuple(lines or (f'{sha[:12]} carries no {part or "tests/<part>"} status',))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge status', description='commit statuses')
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
    for sub in (post, listing, showing):
        sub.add_argument('--json', action='store_true', help='print the normalized result as JSON')
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``python -m lab_commons.dev.forge status post|list <sha> ...``; exit 1 with netverb's remedy on failure."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    client = client_for(Path.cwd() if cwd is None else cwd, env=env, transport=transport)
    try:
        if args.verb == 'post':
            found: tuple[CommitStatus, ...] = (
                status_post(client, args.sha, context=args.context, state=args.state, description=args.description),
            )
        elif args.verb == 'show':
            lines = status_show(client, args.sha, part=args.part)
            for line in lines if not args.json else ():
                emit(line)
            if args.json:
                emit(json.dumps({'sha': args.sha, 'part': args.part, 'lines': list(lines)}, indent=2))
            return 0
        else:
            found = status_list(client, args.sha)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    if args.json:
        data = [dataclasses.asdict(status) for status in found]
        emit(json.dumps(data[0] if args.verb == 'post' else data, indent=2))
    else:
        for status in found:
            emit(f'{status.context}  {status.state}  {status.description}')
    return 0
