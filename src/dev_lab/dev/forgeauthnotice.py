"""A REFUSED TOKEN IS HEARD AT SESSION START, not when an agent complains about it.

The ``SessionStart`` hook (:data:`dev_lab.dev.agent_wiring.WIRING`) asks each forge the checkout's remotes declare
ONE question -- ``GET /user`` with the token git's store holds for that host (``auth check``'s first read,
:func:`dev_lab.dev.forgeauth.tick_refusal`) -- through the retrying client (:class:`~dev_lab.dev.forgework.Client`)
under one shared :data:`BUDGET_S`. It never prompts: the credential is read with git's no-prompt switches, and no
provider refresh is asked.

* the forge answers: silent;
* the forge REFUSES the token (an answered refusal, :func:`dev_lab.dev.forgeauth.answered_refusal`): one line naming
  the host and the remedy door (``forge auth login --host <host>``);
* the forge is not reached within the budget, or answers only transients: one line saying UNREACHABLE -- never
  "refused", so nobody re-stores a token that works;
* no credential stored for the host: silent (an anonymous checkout is no fault).

``python -m dev_lab.dev.forgeauthnotice --session-start`` (the hook; its cwd from the payload) or ``--root R``;
always exits 0.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.checkout import git_out
from dev_lab.dev.forge import Forge, NoCredential, UnreadableRemote, credential_for, forge_from_remote, forge_transport
from dev_lab.dev.forgeauth import answered_refusal
from dev_lab.dev.forgefailure import BudgetSpent, ForgeCallFailed, within
from dev_lab.dev.forgework import Client
from dev_lab.dev.venvfollow import toplevel
from dev_lab.dev.venvpath import running_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from dev_lab.dev.forge import Transport

__all__ = ['BUDGET_S', 'declared_forges', 'main', 'notices']

#: The wall every forge question of one session start shares, in seconds.
BUDGET_S: Final = 2.0


def declared_forges(root: Path) -> tuple[Forge, ...]:
    """One :class:`~dev_lab.dev.forge.Forge` per distinct host among *root*'s git remotes, in remote order."""
    found: dict[str, Forge] = {}
    for name in (git_out(root, 'remote') or '').split():
        try:
            forge = forge_from_remote(root, remote=name)
        except (UnreadableRemote, ValueError):
            continue
        found.setdefault(forge.host, forge)
    return tuple(found.values())


def _notice(forge: Forge, root: Path, env: Mapping[str, str] | None, transport: Transport) -> str:
    try:
        username, secret = credential_for(forge.host, cwd=root, env=env)
    except NoCredential:
        return ''
    client = Client(forge, secret, transport=transport, username=username, sleep=lambda _s: None, timeout=BUDGET_S)
    try:
        client.whoami()
    except ForgeCallFailed as failed:
        if answered_refusal(failed):
            return (f"[forge] {forge.host} refuses this machine's token (GET /user): "
                    f'{running_interpreter()} -m dev_lab.dev.forge auth login --host {forge.host}')  # fmt: skip
        return _unreachable(forge, f'{len(failed.report.attempts)} attempts')
    except BudgetSpent:
        return _unreachable(forge, f'not answered within {BUDGET_S:g} s')
    return ''


def _unreachable(forge: Forge, why: str) -> str:
    return f'[forge] {forge.host} unreachable at session start ({why}): the token was not checked -- not a refusal'


def notices(
    root: Path,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
    now: Callable[[], float] = time.monotonic,
) -> tuple[str, ...]:
    """The line for every forge of *root* that refused its token or was not reached; empty when all answered."""
    bounded = within(transport, now() + BUDGET_S, 'the session-start token check', BUDGET_S, now=now)
    return tuple(said for forge in declared_forges(root) if (said := _notice(forge, root, env, bounded)))


def _session_root(stdin: TextIO) -> Path | None:
    try:
        payload = json.load(stdin)
    except ValueError:
        payload = {}
    cwd = (payload if isinstance(payload, dict) else {}).get('cwd') or Path.cwd()
    return toplevel(Path(cwd))


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """Print a line per forge refusing this machine's token (or unreachable); silent when all answer. Always 0."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forgeauthnotice', description=main.__doc__)
    where = parser.add_mutually_exclusive_group()
    where.add_argument('--root', type=Path, default=None, help='the checkout (default: the one cwd lies in)')
    where.add_argument('--session-start', action='store_true', help='the SessionStart hook: the payload names cwd')
    args = parser.parse_args(argv)
    try:
        root = _session_root(stdin or sys.stdin) if args.session_start else (args.root or toplevel(Path.cwd()))
        for line in notices(root) if root is not None else ():
            emit(line)
    except OSError as exc:  # a hook never blocks the session it serves
        emit(f'[forge] the session-start token check did not run: {exc}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
