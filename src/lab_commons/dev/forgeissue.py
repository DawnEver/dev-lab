"""An issue is INTENT; its state is DERIVED from git and the forge, never hand-kept (docs-src/dev/issues.md).

WHY NO STATUS LABELS. A label is a second copy of a fact the refs already hold, written by hand and
read as if it were measured -- the "in progress" label on an issue whose branch was deleted a week
ago. The family's readiness signal is ref movement on ``origin`` (the-three-participants.md), so the
state of an issue is computed from exactly that, every time it is asked:

    done         the issue is closed, or ``Closes #N`` is on the default branch
    ready        a lane referencing it has a tip whose ``lab/gate`` status is ``success``
    in-progress  an origin branch carries a commit ``Refs #N`` (or ``Closes``/``Fixes``), or is
                 named ``fix/<N>-...``
    todo         open, and nothing on origin references it

FETCH-FREE, AND THAT IS THE CALLER'S HALF. The branches read are the local REMOTE-TRACKING refs
(``refs/remotes/origin/*``); a network verb belongs to the caller, who runs ``git fetch --prune``
first when freshness matters. A read that silently fetched would be a network call hidden in a
query, and a stale answer here is visible (the tips are printed) where a hung fetch is not.

A CLAIM IS A COMMENT, ``claim <branch>``, with the provenance line the door already stamps. Every
agent on a box shares one forge account, so an assignee cannot say WHICH agent; the provenance line
can. Two claims naming different branches are a CONFLICT this module reports and never resolves --
that is the human's call.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, Transport, https_transport
from lab_commons.dev.forgestatus import GATE_CONTEXT, Status, status_list
from lab_commons.dev.forgework import Client, Comment, ForgeCallFailed, client_for
from lab_commons.dev.integrator import gate_ready
from lab_commons.dev.issueref import CLOSING_VERBS, REF_VERBS
from lab_commons.log import emit

__all__ = [
    'DONE',
    'IN_PROGRESS',
    'READY',
    'TODO',
    'Claim',
    'IssueComment',
    'IssueState',
    'Lane',
    'claim',
    'claims_of',
    'comments_since',
    'derive',
    'issue_comments',
    'issue_status',
    'lanes_for',
    'main',
]

TODO: Final = 'todo'
IN_PROGRESS: Final = 'in-progress'
READY: Final = 'ready'
DONE: Final = 'done'

_REMOTE: Final = 'origin'
_TRACKING: Final = f'refs/remotes/{_REMOTE}/'
_CLAIM: Final = re.compile(r'^claim\s+(\S+)\s*$', re.MULTILINE)
_COMMENT_PAGE: Final = 50
_COMMENT_PAGES: Final = 20
_ISSUE_OF: Final = re.compile(r'/issues/(\d+)/?$')


@dataclass(frozen=True)
class Lane:
    """An origin branch that references the issue, its tip, and that tip's ``lab/gate`` state."""

    branch: str
    tip: str
    gate: str


@dataclass(frozen=True)
class Claim:
    """A ``claim <branch>`` comment: the branch, who (the provenance line, empty for a human), where."""

    branch: str
    by: str
    url: str


@dataclass(frozen=True)
class IssueComment:
    """One comment, normalized across forges: which issue, its id, who, what, and when (ISO 8601)."""

    issue: int
    id: int
    author: str
    body: str
    created: str


@dataclass(frozen=True)
class IssueState:
    """The derived state of one issue, with the evidence it was derived from."""

    number: int
    title: str
    state: str
    lanes: tuple[Lane, ...]
    claims: tuple[Claim, ...]
    conflict: bool


def _mentions(number: int, *, closing: bool) -> re.Pattern[str]:
    verbs = '|'.join(CLOSING_VERBS if closing else REF_VERBS)
    return re.compile(rf'\b(?:{verbs})\s+#{number}\b', re.IGNORECASE)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    return done.stdout if done.returncode == 0 else ''


def _branches(root: Path) -> dict[str, str]:
    listed = _git(root, 'for-each-ref', '--format=%(refname) %(objectname)', _TRACKING)
    pairs = (line.split(' ', 1) for line in listed.splitlines() if line.strip())
    return {ref.removeprefix(_TRACKING): sha for ref, sha in pairs if ref != f'{_TRACKING}HEAD'}


def _default(root: Path, branches: Mapping[str, str]) -> str | None:
    named = _git(root, 'symbolic-ref', '-q', f'{_TRACKING}HEAD').strip().removeprefix(_TRACKING)
    return named or next((name for name in ('main', 'master') if name in branches), None)


def lanes_for(root: Path, number: int) -> tuple[tuple[tuple[str, str], ...], bool]:
    """``((branch, tip), ...)`` of origin lanes referencing *number*, and whether the default branch closes it.

    A lane is a non-default origin branch named ``fix/<number>-...`` or holding a commit, not on the
    default branch, whose message references the issue.
    """
    branches = _branches(root)
    default = _default(root, branches)
    mentions = _mentions(number, closing=False)
    lanes = []
    for name, tip in sorted(branches.items()):
        if name == default:
            continue
        span = f'{_TRACKING}{name}' if default is None else f'{_TRACKING}{default}..{_TRACKING}{name}'
        if name.startswith(f'fix/{number}-') or mentions.search(_git(root, 'log', '--format=%B', span)):
            lanes.append((name, tip))
    closed = default is not None and bool(
        _mentions(number, closing=True).search(_git(root, 'log', '--format=%B', f'{_TRACKING}{default}'))
    )
    return tuple(lanes), closed


def claims_of(comments: Sequence[Comment]) -> tuple[Claim, ...]:
    """The LATEST claim per claimant, oldest first.

    A claimant is the ``machine · agent`` of the provenance line -- NOT the whole line, whose third
    part is the branch it was written from and so changes when the agent moves lanes. An unstamped
    (human) claim is its own claimant.
    """
    latest: dict[str, Claim] = {}
    for comment in comments:
        found = _CLAIM.findall(comment.body)
        if not found:
            continue
        first = comment.body.splitlines()[0] if comment.body else ''
        by = first if first.startswith('[') and first.endswith(']') else ''
        who = ' · '.join(by.strip('[]').split(' · ')[:2]) if by else comment.url
        latest.pop(who, None)
        latest[who] = Claim(found[-1], by, comment.url)
    return tuple(latest.values())


def derive(*, is_open: bool, closed_on_default: bool, lanes: Sequence[Lane]) -> str:
    """The table in the module docstring, as a function of its evidence."""
    if not is_open or closed_on_default:
        return DONE
    if any(gate_ready(lane.gate) for lane in lanes):
        return READY
    return IN_PROGRESS if lanes else TODO


def _comments(client: Client, number: int) -> tuple[Comment, ...]:
    path = f'{client.repo}/issues/{number}/comments?{client.backend.page_param}={_COMMENT_PAGE}'
    listed = client.call('GET', path)
    return tuple(Comment(raw['id'], raw.get('body') or '', raw['html_url']) for raw in listed)


def _listed(client: Client, collection: str, since: str | None) -> tuple[IssueComment, ...]:
    query = {client.backend.page_param: str(_COMMENT_PAGE)} | ({'since': since} if since else {})
    found: list[IssueComment] = []
    for page in range(1, _COMMENT_PAGES + 1):
        listed = client.call('GET', f'{client.repo}/{collection}?{urllib.parse.urlencode(query | {"page": page})}')
        for raw in listed:
            matched = _ISSUE_OF.search(raw.get('issue_url') or '')
            author = (raw.get('user') or {}).get('login') or ''
            issue = int(matched.group(1)) if matched else 0
            found.append(IssueComment(issue, raw['id'], author, raw.get('body') or '', raw.get('created_at') or ''))
        if len(listed) < _COMMENT_PAGE:
            break
    return tuple(found)


def issue_comments(client: Client, number: int, *, since: str | None = None) -> tuple[IssueComment, ...]:
    """Issue *number*'s comments, oldest first, optionally only those updated at or after *since*."""
    return tuple(dataclasses.replace(one, issue=number) for one in _listed(client, f'issues/{number}/comments', since))


def comments_since(client: Client, since: str) -> tuple[IssueComment, ...]:
    """Every comment on every issue updated at or after *since* (ISO 8601): the repo-wide listing."""
    return _listed(client, 'issues/comments', since)


def _gate(statuses: Sequence[Status]) -> str:
    return next((status.state for status in statuses if status.context == GATE_CONTEXT), '')


def issue_status(
    client: Client,
    root: Path,
    number: int,
    *,
    statuses: Callable[[Client, str], Sequence[Status]] = status_list,
) -> IssueState:
    """Derive issue *number*'s state from *root*'s remote-tracking refs and the forge. Fetches nothing."""
    issue = client.issue_view(number)
    found, closed = lanes_for(root, number)
    lanes = tuple(Lane(branch, tip, _gate(statuses(client, tip))) for branch, tip in found)
    claims = claims_of(_comments(client, number))
    state = derive(is_open=issue.state == 'open', closed_on_default=closed, lanes=lanes)
    conflict = len({one.branch for one in claims}) > 1
    return IssueState(number, issue.title, state, lanes, claims, conflict)


def _current_branch(root: Path) -> str | None:
    return _git(root, 'symbolic-ref', '--short', '-q', 'HEAD').strip() or None


def claim(client: Client, root: Path, number: int, *, branch: str | None = None) -> Comment:
    """Comment ``claim <branch>`` on *number*; the door prepends the provenance line.

    Raises:
        ValueError: no *branch* was given and HEAD is detached, so there is nothing to claim WITH.

    """
    named = branch or _current_branch(root)
    if not named:
        msg = 'a claim names a branch: pass --branch, or run it on the lane branch (HEAD is detached)'
        raise ValueError(msg)
    return client.issue_comment(number, f'claim {named}')


def _render(state: IssueState) -> str:
    lines = [f'#{state.number} [{state.state}] {state.title}']
    lines += [f'  lane  {lane.branch}  {lane.tip[:12]}  {GATE_CONTEXT}={lane.gate or "-"}' for lane in state.lanes]
    lines += [f'  claim {one.branch}  by {one.by or "(unstamped)"}  {one.url}' for one in state.claims]
    if state.conflict:
        named = sorted({one.branch for one in state.claims})
        lines.append(f'  CONFLICT: claims name {len(named)} branches ({", ".join(named)}) -- the human resolves it')
    return '\n'.join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge issue', description='derived issue state')
    verbs = parser.add_subparsers(dest='verb', required=True)
    claiming = verbs.add_parser('claim')
    claiming.add_argument('--branch', default=None)
    status = verbs.add_parser('status')
    listing = verbs.add_parser('comments')
    listing.add_argument('--since', default=None)
    for sub in (claiming, status, listing):
        sub.add_argument('number', type=int)
    wide = verbs.add_parser('comments-since')
    wide.add_argument('since')
    for sub in (claiming, status, listing, wide):
        sub.add_argument('--json', action='store_true', help='print the normalized result as JSON')
    return parser


def _run(client: Client, root: Path, args: argparse.Namespace) -> Comment | IssueState | tuple[IssueComment, ...]:
    if args.verb == 'comments':
        return issue_comments(client, args.number, since=args.since)
    if args.verb == 'comments-since':
        return comments_since(client, args.since)
    if args.verb == 'claim':
        return claim(client, root, args.number, branch=args.branch)
    return issue_status(client, root, args.number)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``python -m lab_commons.dev.forge issue claim|status|comments <N>`` | ``comments-since <ISO>``.

    Exit 1 on a forge failure, 2 on a refusal.
    """
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    client = client_for(root, env=env, transport=transport)
    try:
        result = _run(client, root, args)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed.report.remedy}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    except ValueError as exc:
        emit(f'[forge] {exc}', err=True)
        return 2
    if isinstance(result, tuple):
        rows = [dataclasses.asdict(one) for one in result]
        lines = [f'#{row["issue"]} {row["author"]}: {row["body"]}' for row in rows]
        emit(json.dumps(rows, indent=2) if args.json else '\n'.join(lines))
    elif args.json:
        emit(json.dumps(dataclasses.asdict(result), indent=2))
    else:
        emit(result.url if isinstance(result, Comment) else _render(result))
    return 0
