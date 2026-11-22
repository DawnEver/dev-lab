"""``hpcaccount keys <user@host> --hosts DIR [--dry-run]``: the account's ssh login keys DERIVED from hosts-config.

User ruling 2026-11-22: every development workstation can do everything another can, controlled by config, and the
hosts config is the single source of truth. So a cluster account's ``~/.ssh/authorized_keys`` is not hand-kept: it
holds the ``[dev] client_keys`` of EVERY workstation whose ``[dev] hpc`` reach lists that account's grant role
(:func:`reaching`), read from ``DIR`` -- a checkout of the hosts config's ``hosts/`` -- never from this machine's
memory.

A MANAGED BLOCK, NEVER THE FILE. The keys live between :data:`BEGIN` and :data:`END`; every line outside them (a key
someone placed by hand, the cluster's own) is kept as it was (:func:`merged`). The write goes through the grant's
own key-only connection (:func:`dev_lab.dev.hpcaccount.transport.grant_runner`): a backup
``~/.ssh/authorized_keys.bak-<ts>`` first, the new text staged under umask 077, mode 0600, atomic ``mv``. Running it
again with the same declaration changes nothing (idempotent: an unchanged file is not rewritten).

READ BACK BEFORE IT SAYS SO. After the write the file is read again; only when its managed block is exactly the
derived keys does the door print ``verified`` and exit 0, else 2 naming what it found. ``--dry-run`` connects to
nothing and prints each derived key by a sha256 prefix only. A key is never printed in full.
"""

from __future__ import annotations

import argparse
import shlex
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev.credstore import digest, stamp_now
from dev_lab.dev.hpcaccount.division import Division, division_of, reached_machine
from dev_lab.dev.hpcaccount.transport import grant_runner
from dev_lab.ops import clientkeys

__all__ = ['BEGIN', 'END', 'main', 'merged', 'place_keys', 'reaching']

#: The first line of the managed block.
BEGIN: Final = '# BEGIN dev-lab derived client keys (hpcaccount keys; edits inside are replaced)'
#: The last line of the managed block.
END: Final = '# END dev-lab derived client keys'
#: The account's key file, relative to its home.
FILE: Final = '.ssh/authorized_keys'
#: Where a reaching workstation is declared, for every refusal that finds none.
_DOOR: Final = 'a workstation host file in the hosts config: [dev] hpc = ["<role>"] and [dev] client_keys'


def reaching(files: Mapping[str, str], role: str) -> tuple[str, ...]:
    """The client keys of every development machine in *files* (name -> text) whose ``[dev] hpc`` lists *role*.

    Ordered by file name, each key once.

    Raises:
        ValueError: a file is not TOML or declares a malformed key -- naming the file.

    """
    picked: dict[str, str] = {}
    for name in sorted(files):
        try:
            dev = tomllib.loads(files[name]).get('dev')
        except tomllib.TOMLDecodeError as bad:
            msg = f'{name} is not TOML ({bad}): no key is derived'
            raise ValueError(msg) from bad
        if isinstance(dev, Mapping) and role in (dev.get('hpc') or []) and clientkeys.DEV_KEY in dev:
            picked[name] = files[name]
    return clientkeys.derive(picked)


def merged(current: str, keys: Sequence[str]) -> str:
    """*current* (an authorized_keys text) with its managed block replaced by *keys*; every foreign line kept.

    Raises:
        ValueError: *current* holds a :data:`BEGIN` without its :data:`END` (or the reverse) -- nothing is rewritten.

    """
    lines = current.splitlines()
    if (BEGIN in lines) != (END in lines) or (BEGIN in lines and lines.index(BEGIN) > lines.index(END)):
        msg = f'~/{FILE} holds a broken managed block (one of {BEGIN!r} / {END!r} alone): repair it by hand first'
        raise ValueError(msg)
    if BEGIN in lines:
        lines = lines[: lines.index(BEGIN)] + lines[lines.index(END) + 1 :]
    block = [BEGIN, *keys, END] if keys else []
    return '\n'.join([*lines, *block]) + '\n' if lines or block else ''


def managed(text: str) -> tuple[str, ...]:
    """The key lines inside *text*'s managed block (empty: none)."""
    lines = text.splitlines()
    if BEGIN not in lines or END not in lines:
        return ()
    return tuple(lines[lines.index(BEGIN) + 1 : lines.index(END)])


_READ: Final = f'cat ~/{FILE} 2>/dev/null || true'


def _write(stamp: str) -> str:
    """The remote line writing stdin as ``~/.ssh/authorized_keys``: backup, staged under umask 077, 0600, atomic."""
    new, bak = f'~/{FILE}.new-{stamp}', f'~/{FILE}.bak-{stamp}'
    return (
        f'umask 077 && mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
        f'{{ [ ! -e ~/{FILE} ] || cp -p ~/{FILE} {bak}; }} && '
        f'cat > {new} && chmod 600 {new} && mv -f {new} ~/{FILE} && echo {shlex.quote(f"backup {bak}")}'
    )


def place_keys(
    account: str,
    *,
    files: Mapping[str, str],
    grants: Sequence[Grant],
    division: Division,
    say: Callable[[str], None],
    dry_run: bool = False,
    connect: Callable[[Grant], Runner] | None = None,
    stamp: str = '',
) -> int:
    """Place the derived keys on *account*'s managed block, read them back; 0 verified (or dry run), 2 refused."""
    user = account.partition('@')[0]
    grant = next((g for g in grants if g.user == user), None)
    role = division.role_of(user) if grant else ''
    try:
        keys = reaching(files, role) if role else ()
    except ValueError as bad:
        say(f'keys: refused -- {bad}')
        return 2
    if grant is None:
        why = f'{user} holds no [[hpc.grant]] (declare it in this machine file, or reach it: [dev] hpc)'
    elif not role:
        why = f'{user} declares no grant role ([[hpc.grant]] role)'
    elif not keys:
        why = f'no workstation reaches the role {role!r}: declare {_DOOR}'
    else:
        why = ''
    if why:
        say(f'keys: refused -- {why}')
        return 2
    hashes = ', '.join(digest(key) for key in keys)
    if dry_run:
        say(f'keys: dry run -- {user} ({role}) would hold {len(keys)} derived key(s): {hashes}')
        return 0
    shell = connect(grant) if connect else grant_runner(grant, first=account)
    try:
        current = shell(_READ, None)
        wanted = merged(current, keys)
        backup = 'unchanged' if wanted == current else shell(_write(stamp or stamp_now()), wanted).strip()
        found = managed(shell(_READ, None))
    except (RuntimeError, OSError, ValueError) as failed:
        say(f'keys: refused -- {user}: {failed}')
        return 2
    if found != keys:
        said = ', '.join(digest(key) for key in found) or 'no managed block'
        say(f'keys: not verified -- {user}: ~/{FILE} holds {said}, not {hashes}')
        return 2
    say(f'verified: {user} ({role}): ~/{FILE} managed block holds {hashes} ({backup})')
    return 0


def _host_files(folder: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding='utf-8') for path in sorted(folder.glob('*.toml'))}


def parser() -> argparse.ArgumentParser:
    """The ``keys`` command line."""
    made = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount keys', description=__doc__.splitlines()[0])
    made.add_argument('account', metavar='<user>@<login host>', help='a declared [[hpc.grant]] account')
    made.add_argument(
        '--hosts', type=Path, required=True, metavar='<dir>', help="a checkout of the hosts config's hosts/ directory"
    )
    made.add_argument('--dry-run', action='store_true', help='connect to nothing; print the derived keys as hashes')
    return made


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``keys``; place (or, dry, show) the account's derived login keys."""
    args = parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    if not args.hosts.is_dir():
        emit(f"keys: refused -- {args.hosts} is not a directory: pass a checkout of the hosts config's hosts/")
        return 2
    try:
        machine = reached_machine([args.account.split('@', 1)[0]])
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'keys: refused -- {refused}')
        return 2
    return place_keys(
        args.account, files=_host_files(args.hosts), grants=machine.grants, division=division_of(machine),
        say=emit, dry_run=args.dry_run,
    )  # fmt: skip
