"""``python -m dev_lab.dev.hpcaccount storage-check --account <user> <remote>`` -- a placed secret, proved in place.

``secretplace distribute`` writes a storage secret to every declaring account and then runs ``storage check`` in each
account's kit. When only that check failed (measured 2026-11-23: the account kit refused "Cannot declare ('hpc',)
twice", repaired by a redeploy), re-proving it must not cost a consent code and a re-write. This door runs the same
``python -m dev_lab.dev.storage check <remote>`` in the account's declared checkout through the grant's own runner
(:func:`~dev_lab.dev.hpcaccount.transport.grant_runner`: a held session on a key+TOTP host, key-only ssh otherwise)
and prints its last line. No secret travels; exit 2 when the check refused or the account could not be reached.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable, Sequence
from typing import Final

from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import declared_target, in_checkout
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = ['REMOTE_NAME', 'check_in_kit', 'main', 'storage_check']

#: A storage remote name: a declared table key, never a shell word.
REMOTE_NAME: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
_TIMEOUT_S: Final = 300.0


def check_in_kit(shell: Runner, grant: Grant, remote: str) -> tuple[bool, str]:
    """``storage check`` in *grant*'s kit: (passed, its last line or why it could not run)."""
    target = declared_target(grant, shell)
    if isinstance(target, str):
        return False, f'check skipped: {target}'
    try:
        said = shell(in_checkout(target, ['-m', 'dev_lab.dev.storage', 'check', remote]), None).strip().splitlines()[-1]
    except (RuntimeError, OSError, IndexError) as failed:
        return False, f'check refused: {failed} (the account kit needs dev_lab.dev.storage check: redeploy it)'
    return True, said


def storage_check(user: str, remote: str, *, say: Callable[[str], None] = emit) -> int:
    """Prove *remote*'s placed secret on *user*'s account; 0 reached, 2 refused or unreachable."""
    if not REMOTE_NAME.fullmatch(remote):
        say(f'storage-check: {remote!r} is not a remote name ({REMOTE_NAME.pattern})')
        return 2
    try:
        grant = next(g for g in reached_machine([user]).grants if g.user == user)
        passed, said = check_in_kit(grant_runner(grant, timeout=_TIMEOUT_S), grant, remote)
    except Unreachable as down:
        say(f'storage-check: {user}: refused -- unreachable: {down}')
        return 2
    except (PermissionError, LookupError, RuntimeError, OSError) as refused:
        say(f'storage-check: {user}: refused -- {refused}')
        return 2
    say(f'{user}: {said}')
    return 0 if passed else 2


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``storage-check`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount storage-check', description=__doc__.splitlines()[0])
    parser.add_argument('--account', required=True, help='one account of the fleet')
    parser.add_argument('remote', help='a storage remote the account declares it reaches')
    args = parser.parse_args(list(argv or ()))
    return storage_check(args.account, args.remote)
