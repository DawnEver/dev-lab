"""``python -m dev_lab.dev.hpcaccount archive|archive-clean --account <user> <path> [--as <name>] [--apply]``.

User ruling 2026-11-25: an account is cleaned completely, and its RESULTS OF RECORD are archived to the family's
run store with hash verification BEFORE the local copy is deleted. No door did either half: an agent had only the
clean door (``lab_commons.hpc clean``), which deletes without asking whether anything was kept.

* ``archive`` sends ``~/<path>`` of the account to ``<runs>/archive/<user>/<path>`` -- ``<runs>`` the family file's
  ``[storage] runs`` (:mod:`lab_commons.storage`), the one declared store, never a flag -- as tar parts, reads each
  part back from the store and compares its sha256 with the one taken on the way up, then writes the manifest
  (:mod:`~dev_lab.dev.hpcaccount.archivestream`, streamed to the account and run there: the data never crosses the
  workstation). Without ``--apply`` it prints the plan and writes nothing. ``--as <name>`` archives under another
  leaf name, the door when an EARLIER verified archive of the path exists (one is never overwritten).
* ``archive-clean`` deletes ``~/<path>`` only through the clean door (:mod:`lab_commons.hpc.clean`: confined to its
  parent, refused while a running job works under it, verified gone) and only after the account half has proved
  the release: a verified manifest, every part on the store at its size, the tree unchanged since. Without
  ``--apply`` the clean door's own dry run.

Before either, the account must reach the store's remote: ``storage check`` runs in the account's kit
(:func:`~dev_lab.dev.hpcaccount.storagecheck.check_in_kit`), which renders the account's rclone config; the kit names
its rclone. An undeclared store, or one the account does not reach, is refused naming the door that closes it.
Everything runs pinned to the account's declared login host, through the grant's own runner; a verification account
needs this session's integrator role, as every verb. Exit 2 when refused.
"""

from __future__ import annotations

import argparse
import functools
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple

from lab_commons import storage as _storage
from lab_commons.hpc import clean as _clean
from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.hpc.grants import Grant, Machine
from lab_commons.log import emit
from lab_commons.objects import RCLONE_CONFIG

from dev_lab.dev.artifactstores import ArtifactRefused, check_key
from dev_lab.dev.devhost import RENDER_DOOR
from dev_lab.dev.hpcaccount import archivestream
from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import Target, declared_target, in_checkout
from dev_lab.dev.hpcaccount.look import REPO_NAME, home_path
from dev_lab.dev.hpcaccount.storage import UNREACHABLE, Pin, on_host
from dev_lab.dev.hpcaccount.storagecheck import check_in_kit
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = ['ARCHIVE_PREFIX', 'STREAM_SOURCE', 'TIMEOUT', 'Refused', 'archive', 'archive_clean', 'destination', 'main']

#: The key prefix every account archive lives under on the run store.
ARCHIVE_PREFIX: Final = 'archive'
#: Seconds the account half may run: sending AND reading back a directory of hundreds of GB takes hours.
TIMEOUT: Final = 12 * 3600.0
#: The account half, streamed whole (as :data:`dev_lab.dev.hpcaccount.storage.SWEEP_SOURCE`).
STREAM_SOURCE: Final = Path(archivestream.__file__).read_text(encoding='utf-8')
#: What the account's kit names as its rclone (:func:`dev_lab.dev.storage.rclone_exe`, the pinned install).
_KIT_RCLONE: Final = 'from dev_lab.dev.storage import rclone_exe; print(rclone_exe())'


class Refused(Exception):
    """Nothing was sent or deleted; the message names why and the door."""


def destination(runs: str, user: str, path: str, name: str = '') -> str:
    """Where ``~/<path>`` of *user* is archived on the run store *runs*: ``<runs>/archive/<user>/<path>``.

    *name* replaces the leaf (``--as``). Raises :class:`Refused` for a key a remote cannot hold.
    """
    parent, _, leaf = path.rpartition('/')
    key = '/'.join(part for part in (ARCHIVE_PREFIX, user, parent, name or leaf) if part)
    try:
        check_key(key)
    except ArtifactRefused as bad:
        raise Refused(str(bad)) from bad
    return f'{runs.rstrip("/")}/{key}'


def run_store(declared: _storage.Storage | None = None) -> tuple[str, str]:
    """The family's run store and its remote; undeclared is refused naming where it is declared."""
    declared = _storage.declared() if declared is None else declared
    if declared.runs is None or declared.runs_remote is None:
        reached = sorted(remote.name for remote in declared.reach) or ['none reached here']
        msg = (
            'the family file declares no run store: add `runs = "<remote>:<path>"` under [storage] in the config '
            f"source's family file (a remote it declares; reached here: {', '.join(reached)}), then re-render this "
            f'machine: {RENDER_DOOR}'
        )
        raise Refused(msg)
    return declared.runs, declared.runs_remote


class _Account(NamedTuple):
    """One reached account: the machine that reached it, its grant, its declared target, a runner pinned there."""

    machine: Machine
    grant: Grant
    target: Target
    run: Runner


def _account(user: str, connect: Callable[[Grant], Runner], pin: Pin) -> _Account:
    machine = reached_machine([user])
    grant = next(g for g in machine.grants if g.user == user)
    target = declared_target(grant, connect(grant))
    if isinstance(target, str):
        raise Refused(target)
    return _Account(machine, grant, target, pin(grant, target.host))


def _spec(mode: str, path: str, name: str, declared: _storage.Storage | None, account: _Account) -> dict[str, Any]:
    """What the account half runs: the mode, the path, its destination, and the account's own rclone and config."""
    user = account.grant.user
    runs, remote = run_store(declared)
    dest = destination(runs, user, path, name)
    run, target = account.run, account.target
    passed, said = check_in_kit(run, account.grant, remote)
    if not passed:
        msg = (
            f'the account does not reach the run store {remote!r}: {said} -- place its secret with `python -m '
            f'dev_lab.ops.secretplace distribute --remote {remote}`, then prove it with `python -m '
            f'dev_lab.dev.hpcaccount storage-check --account {user} {remote}`'
        )
        raise Refused(msg)
    rclone = run(in_checkout(target, ['-c', _KIT_RCLONE]), None).strip().splitlines()[-1:]
    if not rclone:
        msg = "the account's kit named no rclone"
        raise Refused(msg)
    return {
        'mode': mode, 'path': path, 'dest': dest, 'rclone': rclone, 'config': RCLONE_CONFIG.as_posix(),
        'part_bytes': archivestream.PART_BYTES, 'tar': ['tar'],
    }  # fmt: skip


def _stream(target: Target, run: Runner, spec: dict[str, Any], say: Callable[[str], None]) -> dict[str, Any]:
    """Run the account half with *spec*; its lines said, its verdict returned."""
    lines = run(in_checkout(target, ['-', json.dumps(spec)]), STREAM_SOURCE).rstrip().splitlines()
    verdict = lines.pop() if lines and lines[-1].startswith(archivestream.VERDICT) else ''
    for line in lines:
        say(line)
    if not verdict:
        msg = 'the account half printed no verdict line: nothing it did is proved'
        raise Refused(msg)
    return json.loads(verdict.removeprefix(archivestream.VERDICT))


def _checked(path: str, name: str) -> None:
    home_path(path)
    if name and not REPO_NAME.fullmatch(name):
        msg = f'--as {name!r} is not a name ({REPO_NAME.pattern})'
        raise ValueError(msg)


def archive(
    user: str, path: str, *, apply: bool, name: str = '', declared: _storage.Storage | None = None,
    connect: Callable[[Grant], Runner] = grant_runner, pin: Pin = on_host, say: Callable[[str], None] = emit,
) -> int:  # fmt: skip
    """Archive ``~/<path>`` of *user* to the run store (*apply*), else print the plan; 0 done, 2 refused."""
    try:
        _checked(path, name)
        run_store(declared)  # an undeclared store is refused before any account is reached
        account = _account(user, connect, pin)
        spec = _spec('archive' if apply else 'plan', path, name, declared, account)
        verdict = _stream(account.target, account.run, spec, say)
    except (Refused, ValueError, PermissionError, LookupError, RuntimeError, OSError) as refused:
        say(f'archive: {user}: refused -- {UNREACHABLE if isinstance(refused, Unreachable) else refused}')
        return 2
    if not verdict.get('ok'):
        say(f'archive: {user}: refused -- {verdict.get("why")}')
        return 2
    return 0


def archive_clean(
    user: str, path: str, *, apply: bool, name: str = '', timeout: float = _clean.TIMEOUT_S,
    declared: _storage.Storage | None = None, connect: Callable[[Grant], Runner] = grant_runner, pin: Pin = on_host,
    clean: Callable[..., int] = _clean.main, say: Callable[[str], None] = emit,
) -> int:  # fmt: skip
    """Delete ``~/<path>`` through the clean door once its archive is proved; a dry run unless *apply*."""
    try:
        _checked(path, name)
        run_store(declared)
        account = _account(user, connect, pin)
        verdict = _stream(account.target, account.run, _spec('release', path, name, declared, account), say)
    except (Refused, ValueError, PermissionError, LookupError, RuntimeError, OSError) as refused:
        say(f'archive-clean: {user}: refused -- {UNREACHABLE if isinstance(refused, Unreachable) else refused}')
        return 2
    if verdict.get('verdict') != 'released':
        say(f'archive-clean: {user}: refused, nothing deleted -- {verdict.get("why")}')
        return 2
    host = account.target.host
    argv = ['--root', verdict['parent'], '--grant', user, '--timeout', f'{timeout:g}', verdict['name']]
    return clean([*argv, *([] if apply else ['--dry-run'])], machine=account.machine, reach=lambda g, _t: pin(g, host))


def _parser(verb: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f'dev_lab.dev.hpcaccount {verb}', description=__doc__.splitlines()[0])
    parser.add_argument('--account', required=True, help='one account of the fleet')
    parser.add_argument('path', help='a home-relative path of names on the account')
    parser.add_argument('--as', dest='name', default='', help="archive under this leaf name instead of the path's")
    parser.add_argument('--apply', action='store_true', help='do it; default: print what would be done')
    parser.add_argument('--timeout', type=float, default=TIMEOUT, help=f'seconds per remote command ({TIMEOUT:g})')
    return parser


def main(argv: Sequence[str] | None = None, *, verb: str = 'archive') -> int:
    """Parse ``archive`` or ``archive-clean`` and run it."""
    args = _parser(verb).parse_args(list(argv or ()))
    connect = functools.partial(grant_runner, timeout=args.timeout)
    pin = functools.partial(on_host, timeout=args.timeout)
    if verb == 'archive-clean':
        return archive_clean(args.account, args.path, apply=args.apply, name=args.name, timeout=args.timeout,
                             connect=connect, pin=pin)  # fmt: skip
    return archive(args.account, args.path, apply=args.apply, name=args.name, connect=connect, pin=pin)
