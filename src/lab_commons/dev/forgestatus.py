"""Commit statuses on the forge -- the door a verdict is PUBLISHED through (forge.md, layer C).

WHY A STATUS AND NOT A COMMENT OR A LABEL. The forge can refuse a ``main`` update whose commit lacks
a green status in a NAMED context; nothing else it stores can refuse anything. So the verdict that a
gate or heavy run earned is posted against the exact commit it judged, under :data:`GATE_CONTEXT` or
:data:`HEAVY_CONTEXT`, with the verdict line as its description -- which makes the status citable
(the line names the tree, the env and the log digest) rather than a bare colour.

THE MAPPING IS THE VERDICT'S POLARITY, NOT A NEW ONE: PASS -> ``success``, FAIL -> ``failure``, and
INCONCLUSIVE POSTS NOTHING. A ``pending`` or ``error`` for "nobody knows" would be a state somebody
reads as a judgement; an absent status is exactly what an unjudged commit has.

A VERDICT ABOUT A DIRTY TREE HAS NO COMMIT. :func:`verdict_commit` returns HEAD's sha only when the
tree was clean before the run, is clean after it, and HEAD did not move -- the conditions under which
the content address the verdict carries IS a reading of that commit's tree. Otherwise nothing is
posted, because a status is a claim about a commit and this run made none.

PUBLISHING NEVER CHANGES THE VERDICT. :func:`publish` returns one line for the caller to print and
raises nothing: no credential, no ``origin``, or a forge that refused -- each is reported in that
line and the run's exit code is the verdict's alone.

PROVENANCE-FREE ON PURPOSE. Status descriptions are machine verdict lines, length-limited by the
forge, so no ``[machine · agent · branch]`` stamp is prepended; the forge records the token's login.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, NoCredential, Transport, UnreadableRemote, https_transport
from lab_commons.dev.forgework import GITHUB, Client, ForgeCallFailed, client_for
from lab_commons.dev.verdict import Outcome, Verdict
from lab_commons.log import emit

__all__ = [
    'DESCRIPTION_LIMIT',
    'GATE_CONTEXT',
    'HEAVY_CONTEXT',
    'STATES',
    'Status',
    'head_sha',
    'main',
    'publish',
    'state_for',
    'status_list',
    'status_post',
    'verdict_commit',
]

#: The lane-gate context: a dev agent's gate verdict on its own lane tip.
GATE_CONTEXT: Final = 'lab/gate'

#: The integrator's heavy verdict -- the context ``main`` protection requires once it is enabled.
HEAVY_CONTEXT: Final = 'lab/heavy'

#: The states this door writes. ``error`` is the forge's and never this family's: see the docstring.
STATES: Final = ('success', 'failure', 'pending')

#: GitHub's description limit, the tighter of the two forges; a longer one is refused, not truncated.
DESCRIPTION_LIMIT: Final = 140

_STATE_FOR: Final[dict[Outcome, str]] = {Outcome.PASS: 'success', Outcome.FAIL: 'failure'}


@dataclass(frozen=True)
class Status:
    """One commit status, identical in shape whichever forge answered."""

    context: str
    state: str
    description: str
    url: str


def _status(raw: Mapping[str, Any]) -> Status:
    # Gitea answers the state as ``status``; GitHub as ``state``.
    state = raw.get('state') or raw.get('status') or ''
    return Status(raw.get('context') or '', state, raw.get('description') or '', raw.get('target_url') or '')


def state_for(outcome: Outcome) -> str | None:
    """``success`` for PASS, ``failure`` for FAIL, ``None`` -- post nothing -- for INCONCLUSIVE."""
    return _STATE_FOR.get(outcome)


def status_post(client: Client, sha: str, *, context: str, state: str, description: str) -> Status:
    """Post one status on *sha*. The description is cut to :data:`DESCRIPTION_LIMIT`, never sent long."""
    if state not in STATES:
        msg = f'a status state is one of {STATES}, not {state!r}'
        raise ValueError(msg)
    body = {'state': state, 'context': context, 'description': description[:DESCRIPTION_LIMIT]}
    return _status(client.call('POST', f'{client.repo}/statuses/{sha}', body))


def status_list(client: Client, sha: str) -> tuple[Status, ...]:
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


def _git(root: Path, *args: str) -> str | None:
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


#: A publish runs at the end of an unattended verify, so the credential lookup must never PROMPT: a
#: helper that opens a sign-in window would hang a finished run on a dialog nobody is watching.
_NO_PROMPT: Final = {'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}


def _unprompted_client(root: Path) -> Client:
    # Set in THIS process rather than passed as ``env=``: an explicit env is the test seam, which
    # also blanks PATH for ``git credential`` -- and that hides the real helper from a real run.
    for name, value in _NO_PROMPT.items():
        os.environ.setdefault(name, value)
    return client_for(root)


def publish(
    root: Path,
    verdict: Verdict,
    *,
    context: str,
    commit: str | None,
    client: Callable[[Path], Client] = _unprompted_client,
) -> str:
    """Post *verdict* on *commit* under *context*; return the one line saying what happened. Never raises.

    The line is for the run's own output. Every skip and every failure is NAMED, because "no status
    appeared" otherwise reads the same whether it was a dirty tree, a missing token or a 403.
    """
    state = state_for(verdict.result.outcome)
    if state is None:
        return f'status: not posted -- an INCONCLUSIVE verdict publishes no {context} status'
    if commit is None:
        return 'status: not posted -- the tree was dirty or moved, so this verdict is about no commit'
    try:
        posted = status_post(client(root), commit, context=context, state=state, description=verdict.line())
    except (NoCredential, UnreadableRemote) as exc:
        return f'status: skipped -- no forge credential or remote here ({exc})'
    except (ForgeCallFailed, OSError, ValueError, KeyError) as exc:
        return f'status: post FAILED, the verdict stands -- {exc}'
    return f'status: {posted.context}={posted.state} on {commit[:12]}'


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
    for sub in (post, listing):
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
            found: tuple[Status, ...] = (
                status_post(client, args.sha, context=args.context, state=args.state, description=args.description),
            )
        else:
            found = status_list(client, args.sha)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed.report.remedy}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    if args.json:
        data = [dataclasses.asdict(status) for status in found]
        emit(json.dumps(data[0] if args.verb == 'post' else data, indent=2))
    else:
        for status in found:
            emit(f'{status.context}  {status.state}  {status.description}')
    return 0
