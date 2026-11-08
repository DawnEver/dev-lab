"""``python -m dev_lab.dev.opsserver <server> <verb> [<unit>]`` -- the ops door's fixed verbs on a DECLARED server.

User ruling 2026-11-07: ssh has two kinds of target. A cluster account is :mod:`dev_lab.dev.hpcaccount`'s; a server
the integrator deploys (the forge host, its mirrors, the other services) is this door's. Before it, a server change
was a hand-written ``ssh ... sudo ...`` line, which no rule could tell from any other write to any other host.

THE SERVERS ARE THE MACHINE FILE'S ``[[server]]`` TABLES -- ``name``, ``target`` (``ops@<host>``), and optionally
``root`` (the server's kit checkout, :data:`DEFAULT_ROOT`) and ``config`` (its supervise file,
:data:`DEFAULT_CONFIG`). Nothing here lists a host, and a name not declared is refused before any ssh.

THE VERBS ARE THE OPS ACCOUNT'S FIXED SUDO LIST (user ruling 2026-11-04), nothing wider: ``install`` (the ops door's
own install), ``status|restart|reload|logs <unit>`` and ``daemon-reload``. The ops login asks the key AND the user's
one-time code, so the ssh runs attached to this terminal (:func:`dev_lab.dev.remote.ssh_argv` ``batch=False``);
``--dry-run`` prints the line and runs nothing.
"""

from __future__ import annotations

import argparse
import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final

from lab_commons.config import machine
from lab_commons.log import emit

from dev_lab.dev.remote import run, ssh_argv
from dev_lab.dev.venvpath import venv_interpreter

__all__ = ['DEFAULT_CONFIG', 'DEFAULT_ROOT', 'UNIT_VERBS', 'VERBS', 'Server', 'declared_servers', 'main', 'remote_line']

DEFAULT_ROOT: Final = '/opt/dev-lab'
DEFAULT_CONFIG: Final = '/etc/dev-lab/supervise.toml'
#: The verbs taking a systemd unit, each the ops account's fixed sudo command.
UNIT_VERBS: Final = {
    'status': 'systemctl --no-pager status',
    'restart': 'systemctl restart',
    'reload': 'systemctl reload',
    'logs': 'journalctl --no-pager -n 200 -u',
}
VERBS: Final = (*UNIT_VERBS, 'daemon-reload', 'install')
_UNIT: Final = re.compile(r'[A-Za-z0-9@_.-]+')
_TIMEOUT_S: Final = 1800


@dataclass(frozen=True)
class Server:
    """One declared server: its name, its ``ops@<host>`` target, its kit checkout and supervise file."""

    name: str
    target: str
    root: str = DEFAULT_ROOT
    config: str = DEFAULT_CONFIG


def declared_servers(file: Mapping[str, Any]) -> dict[str, Server]:
    """The machine file's ``[[server]]`` tables by name; a table missing ``name`` or ``target`` is refused."""
    out: dict[str, Server] = {}
    for row in file.get('server', ()) or ():
        if not row.get('name') or not row.get('target'):
            msg = f'a [[server]] table needs name and target: {row}'
            raise ValueError(msg)
        out[row['name']] = Server(
            row['name'], row['target'], row.get('root', DEFAULT_ROOT), row.get('config', DEFAULT_CONFIG)
        )
    return out


def remote_line(server: Server, verb: str, unit: str | None) -> str:
    """The one POSIX line the verb runs on *server*: a fixed sudo command, never anything an argument widens."""
    if verb in UNIT_VERBS:
        if unit is None or not _UNIT.fullmatch(unit):
            msg = f'{verb} takes one systemd unit name, got {unit!r}'
            raise ValueError(msg)
        return f'sudo {UNIT_VERBS[verb]} {shlex.quote(unit)}'
    if unit is not None:
        msg = f'{verb} takes no unit'
        raise ValueError(msg)
    if verb == 'daemon-reload':
        return 'sudo systemctl daemon-reload'
    python = PurePosixPath(server.root) / venv_interpreter(os_name='posix')
    return f'sudo {python} -m dev_lab.ops --config {shlex.quote(server.config)} install'


def main(
    argv: Sequence[str] | None = None,
    *,
    file: Callable[[], Mapping[str, Any]] = machine,
    runner: Callable[[Sequence[str]], int] = lambda line: run(line, timeout_s=_TIMEOUT_S),
) -> int:
    """Run one fixed verb on one declared server. Exit 2 refused (nothing ran), else the ssh's own code."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.opsserver', description=__doc__.splitlines()[0])
    parser.add_argument('server')
    parser.add_argument('verb', choices=VERBS)
    parser.add_argument('unit', nargs='?')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    servers = declared_servers(file())
    if args.server not in servers:
        emit(f'opsserver: refused -- {args.server!r} is not a declared [[server]] ({sorted(servers)})', err=True)
        return 2
    server = servers[args.server]
    try:
        line = ssh_argv(server.target, remote_line(server, args.verb, args.unit), batch=False)
    except ValueError as bad:
        emit(f'opsserver: refused -- {bad}', err=True)
        return 2
    emit(f'{server.name}: {"would run" if args.dry_run else "running"} {shlex.join(line)}')
    return 0 if args.dry_run else runner(line)


if __name__ == '__main__':
    raise SystemExit(main())
