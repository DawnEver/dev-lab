"""WRITE one confirmed vendor location row into the config source, as a branch that becomes its pull request.

The config source (hosts-config) owns where each program is installed on each machine: one
``[dev.vendors.<program>]`` row (``version``, ``home``; :data:`dev_lab.dev.devschema.VENDOR`) in
``hosts/<machine>.toml``. A program PROPOSES a location (a consumer's ``vendor <program> locate``); the user
CONFIRMS it; this door WRITES it -- never into the clone's checkout and never into a machine file, but into a worktree
branch :func:`branch_for` cut from the source's trunk, committed, and left for its push and pull request.

``python -m dev_lab.dev.devhost vendor-row --from CLONE --host NAME --program P --version V --home PATH --confirmed``
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final

from lab_commons import launch

from dev_lab.dev._machinefile import merged

if TYPE_CHECKING:
    import argparse

__all__ = ['Proposal', 'Unconfirmed', 'add_vendor_row', 'branch_for', 'row_text', 'write']

#: A program or machine name: what a TOML bare key and a branch segment both hold.
_NAME: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')


class Unconfirmed(PermissionError):
    """A proposal the user has not confirmed: nothing is written."""


@dataclass(frozen=True)
class Proposal:
    """One machine's location of one program, as a program proposed it."""

    host: str
    program: str
    version: str
    home: str

    def defects(self) -> list[str]:
        """Why this row is malformed, each naming its field; empty when well-formed."""
        found = [f'{field} {value!r} must be a name ([A-Za-z0-9_-], no space)'
                 for field, value in (('host', self.host), ('program', self.program))
                 if not _NAME.fullmatch(value)]  # fmt: skip
        if not self.version.strip() or any(c in self.version for c in '\r\n"'):
            found.append(f'version {self.version!r} must be a non-empty one-line string')
        home = self.home
        if any(c in home for c in '\r\n') or not (PurePosixPath(home).is_absolute() or PureWindowsPath(home).drive):
            found.append(f'home {home!r} must be an absolute install path')
        elif '\\' in home:
            found.append(f'home {home!r} must use forward slashes ({home.replace(chr(92), "/")!r})')
        return found


def branch_for(proposal: Proposal) -> str:
    """The worktree branch a proposal is written on."""
    return f'pr/vendor/{proposal.host}-{proposal.program}'


def row_text(text: str, proposal: Proposal) -> str:
    """The host file *text* with *proposal*'s row set; every other line kept. Malformed: ``ValueError``."""
    if found := proposal.defects():
        msg = f'the vendor row is malformed: {"; ".join(found)}'
        raise ValueError(msg)
    table = f'dev.vendors.{proposal.program}'
    out = merged(text, {table: {'version': proposal.version, 'home': proposal.home}})
    row = tomllib.loads(out)['dev']['vendors'][proposal.program]
    if (row.get('version'), row.get('home')) != (proposal.version, proposal.home):  # pragma: no cover - merged checks
        msg = f'[{table}] does not read back as written'
        raise ValueError(msg)
    return out


def _git(cwd: Path, *args: str) -> str:
    done = launch.run(
        [shutil.which('git') or 'git', *args], cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=False
    )
    if done.returncode:
        msg = f'git {" ".join(args)} failed in {cwd}: {done.stderr.strip()}'
        raise RuntimeError(msg)
    return done.stdout.strip()


def write(clone: Path, proposal: Proposal, *, confirmed: bool, base: str = 'origin/main') -> tuple[Path, str]:
    """Write *proposal* on its branch in a new worktree of *clone*, from *base*, and commit; the worktree and sha.

    Raises:
        Unconfirmed: the user did not confirm (nothing is touched).
        ValueError: the row is malformed, or the machine has no host file at *base*.
        RuntimeError: git refused (the branch or worktree exists, *base* is unknown).

    """
    if not confirmed:
        msg = (f'the {proposal.program} location on {proposal.host} is a proposal: the user confirms it, then run '
               'again with --confirmed')  # fmt: skip
        raise Unconfirmed(msg)
    if found := proposal.defects():
        msg = f'the vendor row is malformed: {"; ".join(found)}'
        raise ValueError(msg)
    branch = branch_for(proposal)
    tree = clone / '.claude' / 'worktrees' / f'vendor-{proposal.host}-{proposal.program}'
    host_file = f'hosts/{proposal.host}.toml'
    _git(clone, 'rev-parse', '--verify', '--quiet', f'{base}:{host_file}')  # an unknown machine is refused here
    _git(clone, 'worktree', 'add', '-q', '-b', branch, str(tree), base)
    path = tree / host_file
    path.write_text(row_text(path.read_text(encoding='utf-8'), proposal), encoding='utf-8', newline='\n')
    _git(tree, 'add', '--', host_file)
    _git(tree, 'commit', '-q', '-m', f'feat(hosts): {proposal.host} {proposal.program} {proposal.version} at '
         f'{proposal.home}\n\nConfirmed by the user (devhost vendor-row --confirmed).', '--', host_file)  # fmt: skip
    return tree, _git(tree, 'rev-parse', 'HEAD')


def add_vendor_row(row: argparse.ArgumentParser) -> None:
    """The ``vendor-row`` verb's arguments on its parser *row*."""
    row.add_argument('--from', dest='clone', type=Path, required=True, help='the config-source clone')
    row.add_argument('--host', required=True, help='the machine whose host file holds the row')
    row.add_argument('--program', required=True, help='the vendor program, e.g. jmag')
    row.add_argument('--version', dest='program_version', required=True, help='its installed version')
    row.add_argument('--home', required=True, help='its absolute install home')
    row.add_argument('--base', default='origin/main', help="the source's trunk the branch is cut from")
    row.add_argument('--confirmed', action='store_true', help='the user confirmed this location')
