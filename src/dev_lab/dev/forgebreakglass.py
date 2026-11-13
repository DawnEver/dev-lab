"""``forge breakglass open|close|ack|status`` and ``forge pr breakglass <N> --reason "..."``: the client of the waves.

The client half of :mod:`dev_lab.ops.breakglass`. A WAVE opens on a ``breakglass.wave`` consent credential the USER
granted (``python -m dev_lab.ops.consent grant <request.json>``, params ``hours`` and ``max_merges``):
``open --credential <id>`` reads it from the consent state directory. Inside the wave ``pr breakglass`` merges with
no code -- the server sends ONE summary of what actually merged when the wave ends. ``close`` ends the wave early;
``ack [ID]`` records who acknowledged an audit report (no code; it never blocks a wave).

The endpoint is the machine file's ``[breakglass]`` table (``endpoint = "<account>@<host>"``, optional
``identity = "<ssh key path>"``); every request is one JSON line over ``ssh -T`` (:func:`ssh_send`, which the
consent client shares, through :func:`dev_lab.dev.remote.piped`). The client holds no secret and
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

from dev_lab.dev import remote, sessionprs
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.forge import forge_from_remote
from dev_lab.dev.forgework import Client, client_for

__all__ = ['TABLE', 'Send', 'merge_main', 'ssh_send', 'wave_main']

#: The machine-file table naming the endpoint.
TABLE: Final = 'breakglass'

Send = Callable[[Mapping[str, Any], dict[str, Any]], tuple[int, str]]


def ssh_send(table: Mapping[str, Any], request: dict[str, Any]) -> tuple[int, str]:
    """Send *request* as one JSON line to *table*'s ``endpoint`` over ``ssh -T``; ``(exit status, its output)``."""
    identity = str(table['identity']) if table.get('identity') else None
    known_hosts = str(table['known_hosts']) if table.get('known_hosts') else None
    line = json.dumps(request) + '\n'
    return remote.piped(str(table['endpoint']), line, identity=identity, known_hosts=known_hosts, timeout_s=180)


def _endpoint(table: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    found = section(TABLE) if table is None else table
    if not found.get('endpoint'):
        emit(f'[breakglass] the machine file has no [{TABLE}] endpoint = "<account>@<host>"', err=True)
        return None
    return found


def _answer(send: Send, table: Mapping[str, Any], request: dict[str, Any]) -> int:
    status, said = send(table, request)
    emit(said, err=status != 0)
    return {0: 0, 2: 2}.get(status, 1)


def wave_main(
    argv: Sequence[str] | None = None,
    *,
    table: Mapping[str, Any] | None = None,
    send: Send = ssh_send,
    home: Path | None = None,
) -> int:
    """``breakglass open|close|ack|status``: exit 0 done, 2 refused, 1 the endpoint could not be reached."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forge breakglass', description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('open', 'close', 'ack', 'status'))
    parser.add_argument('id', nargs='?', default='', help='ack: the wave (default: the oldest unacknowledged)')
    parser.add_argument('--credential', default='', help='open: the id of the breakglass.wave credential granted')
    args = parser.parse_args(argv)
    if (config := _endpoint(table)) is None:
        return 2
    request: dict[str, Any] = {'action': args.action}
    if args.action == 'open':
        held = state_dir(home) / f'{args.credential}.json'
        if not args.credential or not held.is_file():
            emit(f'[breakglass] open needs --credential <id> of a granted breakglass.wave ({held})', err=True)
            return 2
        request['credential'] = json.loads(held.read_text(encoding='utf-8'))
    if args.action == 'ack':
        request |= {'id': args.id, 'by': f'{getpass.getuser()}@{socket.gethostname()}'}
    return _answer(send, config, request)


def merge_main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    table: Mapping[str, Any] | None = None,
    send: Send = ssh_send,
) -> int:
    """``pr breakglass <N> --reason R``: merge inside the open wave; exit 0 merged, 2 refused, 1 unreachable."""
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
    emit(f'BREAK-GLASS {repo}#{pull.number} [{pull.state}] {pull.title}: {pull.head} -> {pull.base} at {pull.head_sha}')
    request = {'action': 'merge', 'repo': repo, 'pr': pull.number, 'head': pull.head_sha, 'reason': args.reason}
    code = _answer(send, config, request)
    if code == 0:
        sessionprs.ended(forge_from_remote(root), pull.number)  # SESSION-HEARS-ITS-PRS: the merging door records
    return code
