"""THE RESERVE VERBS -- ``forge reserve <scope> <res=amount,...> --for ... --until ...`` and ``forge release <id>``.

A reservation is a lease on one host or cluster account, written to the forge ledger
(:mod:`lab_commons.compute.ledger`) by the host's own login or a login its user designated in
``[reserve] delegates``; any other writer is refused, here and by every reader. ``forge queue`` lists
the live ones. A daily-moving share is a reservation that expires daily.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from lab_commons.compute import ledger
from lab_commons.dev.forge import NoCredential, Transport, UnreadableRemote, https_transport
from lab_commons.dev.forgeclaim import forge_now
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.log import emit

__all__ = ['release_main', 'reserve_main']

_Act = Callable[[Client, argparse.Namespace], str]


def _run(
    parser: argparse.ArgumentParser,
    act: _Act,
    argv: Sequence[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str] | None,
    transport: Transport,
) -> int:
    args = parser.parse_args(list(argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        built = client_for(root, env=dict(os.environ) if env is None else env, transport=transport)
        emit(act(built, args))
    except (ForgeCallFailed, NoCredential, UnreadableRemote, OSError, ValueError) as failed:
        emit(f'[{parser.prog.rsplit(" ", 1)[-1]}] {failed}', err=True)
        return 2 if isinstance(failed, ValueError) else 1
    return 0


def _reserve(client: Client, args: argparse.Namespace) -> str:
    now = forge_now(client)
    ask = ledger.Ask(
        args.scope,
        ledger.parse_resources(args.resources),
        ledger.parse_for(args.for_),
        ledger.parse_until(args.until, now),
    )
    made = ledger.reserve(client, ask)
    return f'reserved {made.id}: {made.text().splitlines()[1]} (by {made.reservation.by})'


def _release(client: Client, args: argparse.Namespace) -> str:
    gone = ledger.release(client, args.id)
    return f'released {gone.id}: {gone.text().splitlines()[1]}'


def reserve_main(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``reserve <scope> <res=amount,...> --for login:X|repo:Y|needs:a+b --until <iso|duration>``; 2 refused."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge reserve', description=__doc__.splitlines()[0])
    parser.add_argument('scope', help='a host card name: a machine, or <cluster>/<account>')
    parser.add_argument('resources', help='cpu=8,mem_gb=32,jmag=1')
    parser.add_argument('--for', dest='for_', required=True, help='login:X, repo:Y or needs:a+b')
    parser.add_argument('--until', required=True, help='an ISO moment, or a duration: 30m, 36h, 2d')
    return _run(parser, _reserve, argv, cwd=cwd, env=env, transport=transport)


def release_main(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``release <id>``: delete one reservation; 2 refused."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge release', description='release one reservation')
    parser.add_argument('id', type=int, help='the reservation id forge queue lists')
    return _run(parser, _release, argv, cwd=cwd, env=env, transport=transport)
