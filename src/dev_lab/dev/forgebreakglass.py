"""``forge breakglass open|close|ack|status`` and ``forge pr breakglass <N> --reason "..."``: the client of the waves.

The client half of :mod:`dev_lab.ops.breakglass`. The user opens a WAVE with the current code of their
Authenticator (``open [--hours H] [--max-merges M]``, typed by the HUMAN at the prompt); inside it ``pr breakglass``
merges with no code -- the server announces each merge itself, so the human sees what actually merged. ``close``
ends the wave early; ``ack [ID]`` records who acknowledged an audit report (no code; it never blocks a wave).

The endpoint is the machine file's ``[breakglass]`` table (``endpoint = "<account>@<host>"``, optional
``identity = "<ssh key path>"``); every request is one JSON line over ``ssh -T``. The client holds no secret and
cannot authorize itself. A PR's head is pinned: one that moved after it was shown is refused server side.
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import socket
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev.forgework import Client, client_for
from dev_lab.dev.metrics import repo_of

__all__ = ['TABLE', 'merge_main', 'wave_main']

#: The machine-file table naming the endpoint.
TABLE: Final = 'breakglass'
_SSH: Final = shutil.which('ssh') or 'ssh'
_PROMPT: Final = 'Authenticator code (the USER types it): '

Send = Callable[[Mapping[str, Any], dict[str, Any]], tuple[int, str]]


def _send(table: Mapping[str, Any], request: dict[str, Any]) -> tuple[int, str]:
    identity = ['-i', str(table['identity'])] if table.get('identity') else []
    done = _door.run(
        [_SSH, '-T', '-o', 'BatchMode=yes', *identity, str(table['endpoint'])],
        input=json.dumps(request) + '\n', capture_output=True, text=True, encoding='utf-8', check=False, timeout=180,
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).strip()


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
    ask: Callable[[str], str] = input,
    send: Send = _send,
) -> int:
    """``breakglass open|close|ack|status``: exit 0 done, 2 refused, 1 the endpoint could not be reached."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forge breakglass', description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('open', 'close', 'ack', 'status'))
    parser.add_argument('id', nargs='?', default='', help='ack: the wave (default: the oldest unacknowledged)')
    parser.add_argument('--hours', type=float, default=None, help='open: shorter than the server-declared maximum')
    parser.add_argument('--max-merges', type=int, default=None, help='open: a tighter cap than the server declares')
    args = parser.parse_args(argv)
    if (config := _endpoint(table)) is None:
        return 2
    request: dict[str, Any] = {'action': args.action}
    if args.action == 'open':
        request |= {
            name: value for name, value in (('hours', args.hours), ('max_merges', args.max_merges)) if value is not None
        }
    if args.action == 'open':
        request['code'] = ask(_PROMPT).strip()
    if args.action == 'ack':
        request |= {'id': args.id, 'by': f'{getpass.getuser()}@{socket.gethostname()}'}
    return _answer(send, config, request)


def merge_main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    table: Mapping[str, Any] | None = None,
    send: Send = _send,
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
    repo = repo_of(root).rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')
    emit(f'BREAK-GLASS {repo}#{pull.number} [{pull.state}] {pull.title}: {pull.head} -> {pull.base} at {pull.head_sha}')
    request = {'action': 'merge', 'repo': repo, 'pr': pull.number, 'head': pull.head_sha, 'reason': args.reason}
    return _answer(send, config, request)
