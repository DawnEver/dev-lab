"""``forge breakglass open|close|ack|status`` and ``forge pr breakglass <N> --reason "..."``: the client of the waves.

The client half of :mod:`dev_lab.ops.breakglass`. A WAVE opens on a ``breakglass.wave`` consent credential the USER
granted. ``open --code <code> --hours H --max-merges N`` grants it AND opens in ONE call (the code lives one 30-second
TOTP step, so a second command would spend its window) -- and ONLY after ``open --preflight --hours H --max-merges N``
was green: it proves, with no code, that the consent issuer and this server answer (a host key never enrolled is named
with its ``devhost enrol`` door) and writes the receipt the ``--code`` call needs
(:func:`dev_lab.ops.consent.client.preflight`). ``open --credential <id>`` opens on one already granted
(``python -m dev_lab.ops.consent grant <request.json>``) from the consent state directory. Inside the wave
``pr breakglass`` merges with no code -- the server sends ONE summary of what actually merged when the wave ends.
``close`` ends the wave early;
``ack [ID]`` records who acknowledged an audit report (no code; it never blocks a wave).

The endpoint is the machine file's ``[breakglass]`` table (``endpoint = "<account>@<host>"``, optional
``identity = "<ssh key path>"``); every request is one JSON line over ``ssh -T``
(:func:`dev_lab.ops.consent.door.endpoint_send`, the consent client's one transport). The client holds no secret and
cannot authorize itself. A PR's head is pinned: one that moved after it was shown is refused server side.
"""

from __future__ import annotations

import argparse
import getpass
import json
import socket
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev import sessionprs
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.forge import forge_from_remote
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgework import Client
from dev_lab.ops.consent.client import grant, preflight
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import RECEIPT_FRESH_S, Send, endpoint_send, reached
from dev_lab.ops.totp import STEP

__all__ = ['TABLE', 'merge_main', 'promote_trunk', 'wave_main']

#: The machine-file table naming the endpoint.
TABLE: Final = 'breakglass'


def _endpoint(table: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    found = section(TABLE) if table is None else table
    if not found.get('endpoint'):
        emit(f'[breakglass] the machine file has no [{TABLE}] endpoint = "<account>@<host>"', err=True)
        return None
    return found


#: The consent action a wave opens on.
WAVE: Final = 'breakglass.wave'

#: Grants a request file into a credential file (:func:`dev_lab.ops.consent.client.grant`).
Grant = Callable[..., Path]
#: Proves a request can be granted and writes its receipt (:func:`dev_lab.ops.consent.client.preflight`).
Preflight = Callable[..., Path]


def _wave_request(hours: float | str, max_merges: int | str) -> dict[str, Any]:
    """The grant request of one wave; its subject is a free label (the wave redeems with ``subject=None``)."""
    subject = f'break-glass wave by {getpass.getuser()}@{socket.gethostname()}'
    return {'action': WAVE, 'subject': subject, 'params': {'max_merges': max_merges, 'hours': hours}}


def _refuse_open(held: Path) -> int:
    ready = json.dumps(_wave_request('<H>', '<N>'))
    emit(
        f"[breakglass] open needs the user's code or a granted {WAVE} credential ({held} is not one). The code lives "
        f'about {STEP} s, so spend it in ONE call after a green preflight: python -m dev_lab.dev.forge breakglass '
        'open --preflight --hours <H> --max-merges <N>, then ask, then open --code <code> '
        f'--hours <H> --max-merges <N> (preferred). Or grant first -- write {ready} to <request.json>, run python -m '
        'dev_lab.ops.consent grant <request.json> --code <code>, then open --credential <id>',
        err=True,
    )
    return 2


def _preflight(args: argparse.Namespace, config: Mapping[str, Any], send: Send, home: Path | None,
               preflight_: Preflight) -> int:  # fmt: skip
    """``open --preflight``: the consent issuer and this server answer, with no code; the receipt ``--code`` needs."""
    if args.hours is None or args.max_merges is None:
        emit(
            '[breakglass] open --preflight needs --hours <H> and --max-merges <N>, the bounds --code will name',
            err=True,
        )
        return 2

    def server_answers() -> None:
        status, said = reached(send, 'the break-glass server')(config, {'action': 'status'})
        if status != 0:
            msg = f'no code asked: the break-glass server answered {status}: {said}'
            raise ConsentRefused(msg)

    try:
        preflight_(_wave_request(args.hours, args.max_merges), checks=[server_answers], home=home)
    except (ConsentRefused, OSError, ValueError) as refused:
        emit(f'[breakglass] preflight refused, ask the user for no code: {refused}', err=True)
        return 2
    emit(f'[breakglass] preflight green: ask the user for the code now, then run '
         f'python -m dev_lab.dev.forge breakglass open --code <code> --hours {args.hours:g} '
         f'--max-merges {args.max_merges} (it re-runs the issuer preflight itself and uses the code only if green '
         f'then; this receipt admits the ask for {RECEIPT_FRESH_S:.0f} s)')  # fmt: skip
    return 0


def _granted(args: argparse.Namespace, home: Path | None, grant_: Grant) -> dict[str, Any] | None:
    """Grant the wave on the user's code; the credential, or ``None`` (refused, said) before anything opens."""
    if args.hours is None or args.max_merges is None:
        emit(
            '[breakglass] open --code needs --hours <H> and --max-merges <N>: the wave has no default bounds', err=True
        )
        return None
    request = state_dir(home) / 'breakglass-wave-request.json'
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps(_wave_request(args.hours, args.max_merges)), encoding='utf-8')
    try:
        written = grant_(request, code=args.code, home=home)
    except (ConsentRefused, OSError, ValueError) as refused:
        emit(f'[breakglass] the {WAVE} grant was refused, nothing opened: {refused}', err=True)
        return None
    return json.loads(Path(written).read_text(encoding='utf-8'))


def _answer(send: Send, table: Mapping[str, Any], request: dict[str, Any]) -> int:
    status, said = send(table, request)
    emit(said, err=status != 0)
    return {0: 0, 2: 2}.get(status, 1)


def wave_main(
    argv: Sequence[str] | None = None,
    *,
    table: Mapping[str, Any] | None = None,
    send: Send = endpoint_send,
    home: Path | None = None,
    grant_: Grant = grant,
    preflight_: Preflight = preflight,
) -> int:
    """``breakglass open|close|ack|status``: exit 0 done, 2 refused, 1 the endpoint could not be reached."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forge breakglass', description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('open', 'close', 'ack', 'status'))
    parser.add_argument('id', nargs='?', default='', help='ack: the wave (default: the oldest unacknowledged)')
    parser.add_argument('--credential', default='', help='open: the id of the breakglass.wave credential granted')
    parser.add_argument('--preflight', action='store_true', help='open: prove, with no code, that --code can succeed')
    parser.add_argument(
        '--code', default='', help="open: the USER's code (after --preflight); grants and opens at once"
    )
    parser.add_argument('--hours', type=float, default=None, help='open --code: the wave window in hours')
    parser.add_argument('--max-merges', type=int, default=None, help='open --code: the merge cap of the wave')
    args = parser.parse_args(argv)
    if (config := _endpoint(table)) is None:
        return 2
    if args.action == 'open' and args.preflight:
        return _preflight(args, config, send, home, preflight_)
    request: dict[str, Any] = {'action': args.action}
    if args.action == 'open':
        if args.code:
            if (credential := _granted(args, home, grant_)) is None:
                return 2
            request['credential'] = credential
        else:
            held = state_dir(home) / f'{args.credential}.json'
            if not args.credential or not held.is_file():
                return _refuse_open(held)
            request['credential'] = json.loads(held.read_text(encoding='utf-8'))
    if args.action == 'ack':
        request |= {'id': args.id, 'by': f'{getpass.getuser()}@{socket.gethostname()}'}
    return _answer(send, config, request)


def promote_trunk(
    root: Path, sha: str, reason: str, *, table: Mapping[str, Any] | None = None, send: Send = endpoint_send
) -> int:
    """``integrate promote <sha> --breakglass --reason R``: the wave's server fast-forwards the trunk; exit 0/2/1.

    The server decides everything (open wave, served repo, *sha* on integration, a fast-forward) and pushes as the
    break-glass identity; this client holds no credential that could move the trunk itself.
    """
    if (config := _endpoint(table)) is None:
        return 2
    repo = forge_from_remote(root).identity
    emit(f'BREAK-GLASS PROMOTE {repo} trunk -> {sha}')
    return _answer(send, config, {'action': 'promote', 'repo': repo, 'sha': sha, 'reason': reason})


def merge_main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    table: Mapping[str, Any] | None = None,
    send: Send = endpoint_send,
) -> int:
    """``pr breakglass <N> --reason R``: merge inside the open wave; exit 0 merged or was, 2 refused, 1 unreachable."""
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.forge pr breakglass', description='merge PR N inside the open break-glass wave'
    )
    parser.add_argument('number', type=int)
    parser.add_argument('--reason', required=True, help='why the forge merge flow cannot be used; kept in the history')
    args = parser.parse_args(argv)
    if (config := _endpoint(table)) is None:
        return 2
    root = Path.cwd() if cwd is None else cwd
    pull = (client or client_for(root)).pr_view(args.number)
    repo = forge_from_remote(root).identity  # host/owner/name: never typed, never ambiguous across forges
    if pull.merged:  # the wave sweep (or anyone) landed it: done, nothing to merge, never a refusal
        emit(f'[breakglass] {repo}#{pull.number} is already merged as {pull.merge_sha or "(no merge sha reported)"}')
        return 0
    if pull.state != 'open':  # closed unmerged: its owner's "do not land", which nothing reopens
        emit(
            f'[breakglass] {repo}#{pull.number} was closed unmerged; a refused PR is not reopened -- open a new one '
            f'from its branch: python -m dev_lab.dev.forge pr create --head {pull.head} --base {pull.base} '
            f'--title "{pull.title}", then pr breakglass <new N>',
            err=True,
        )
        return 2
    emit(f'BREAK-GLASS {repo}#{pull.number} [{pull.state}] {pull.title}: {pull.head} -> {pull.base} at {pull.head_sha}')
    request = {'action': 'merge', 'repo': repo, 'pr': pull.number, 'head': pull.head_sha, 'reason': args.reason}
    code = _answer(send, config, request)
    if code == 0:
        sessionprs.ended(forge_from_remote(root), pull.number)  # TASK-HEARS-ITS-FORGE-EVENTS: the merging door records
    return code
