"""``python -m dev_lab.dev.oraclegc report`` -- which objects of the family's run store no lock names (ruling D86).

The run store (``[storage] runs``, :mod:`dev_lab.dev.largeobjects`) is content-addressed and write-once: an object
lives under ``<prefix>/<sha[:2]>/<sha>``, and a repo names the objects it needs by sha256 in a committed lock file
(:data:`LOCK_NAMES`). The GC ROOTS are every lock on EVERY branch of EVERY family repo (``[repos]`` of the machine
file): a branch nobody has merged yet still needs its objects.

This lane is REPORT-ONLY: there is no delete verb. ``report`` writes, under
``<output>/<yy>/<mm>/<dd>/oraclegc/``, the objects no root names (size and age), the sha256s a lock names that the
store does not hold, and totals. A later ``--apply`` is a separate user ruling.

A PARTIAL ROOT SET IS REFUSED, never reported: a repo whose branches cannot be listed, or whose branch tip is not in
the local checkout, would make every object only it names look like garbage. :class:`RootsUnread` names each such
repo and its remedy, and no report is written.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol

from lab_commons import launch as _door

from dev_lab.dev.netverb import run_network_verb

__all__ = [
    'LOCK_NAMES',
    'Forge',
    'GitForge',
    'Missing',
    'Report',
    'RootsUnread',
    'Store',
    'Stored',
    'Unreferenced',
    'collect_roots',
    'main',
    'render',
    'report',
]

#: The basenames of the files that name run-store objects by sha256, at any depth of a tree.
LOCK_NAMES: Final = ('references.lock',)
#: The report's kind: its leaf directory under the dated output tree.
KIND: Final = 'oraclegc'

_SHA256: Final = re.compile(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])')
_HEAD: Final = re.compile(r'^([0-9a-f]{40})\trefs/heads/(\S+)$', re.MULTILINE)
_GIT: Final = 'git'


class RootsUnread(RuntimeError):
    """One or more repos could not be read; the root set would be partial, so no report is written."""


class Forge(Protocol):
    """Where a repo's branches are read: branch name -> tip sha, every branch the forge holds."""

    def heads(self, name: str, checkout: Path) -> Mapping[str, str]:
        """Every branch of *name* on its forge; raises :class:`RootsUnread` when it cannot be listed."""
        ...


class Store(Protocol):
    """The run store's listing: ``rclone lsjson -R`` rows (``Path``, ``Size``, ``ModTime``) under its prefix."""

    def files(self) -> list[dict[str, Any]]:
        """Every file under the object prefix, paths relative to it."""
        ...


@dataclass(frozen=True)
class GitForge:
    """The forge as ``git ls-remote --heads origin``, through the network-verb door."""

    run: Callable[..., Any] | None = None

    def heads(self, name: str, checkout: Path) -> Mapping[str, str]:
        """The heads ``origin`` advertises; a refusal or an empty answer is :class:`RootsUnread`."""
        argv = [_GIT, '-C', str(checkout), 'ls-remote', '--heads', 'origin']
        done = run_network_verb(argv) if self.run is None else run_network_verb(argv, run=self.run)
        found = {branch: sha for sha, branch in _HEAD.findall(done.attempts[-1].output if done.attempts else '')}
        if not done.ok or not found:
            msg = f'{name}: the forge listed no branches ({done.remedy})'
            raise RootsUnread(msg)
        return found


@dataclass(frozen=True)
class Stored:
    """One object the store holds."""

    sha256: str
    bytes: int
    modified: datetime


@dataclass(frozen=True)
class Unreferenced:
    """An object no lock names, with its age at the report's instant."""

    stored: Stored
    age_days: float


@dataclass(frozen=True)
class Missing:
    """A sha256 a lock names that the store does not hold, with every place naming it."""

    sha256: str
    named_by: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    """What the store holds against what the family names."""

    repos: tuple[str, ...]
    branches: int
    stored: tuple[Stored, ...]
    referenced: int
    unreferenced: tuple[Unreferenced, ...]
    missing: tuple[Missing, ...]
    foreign: tuple[str, ...] = field(default=())


def _git(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(checkout), *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False,
    )  # fmt: skip


def _locks_at(checkout: Path, sha: str, names: Sequence[str]) -> dict[str, str]:
    """Each lock file in the tree of *sha*: its path -> its text."""
    listed = _git(checkout, 'ls-tree', '-r', '--name-only', sha)
    if listed.returncode != 0:
        msg = (
            f'{checkout.name}: {sha[:12]} is not in the local checkout ({listed.stderr.strip()[-200:]}) -- '
            f'python -m dev_lab.dev.netverb -- git -C {checkout} fetch origin'
        )
        raise RootsUnread(msg)
    found = {}
    for path in listed.stdout.splitlines():
        if PurePosixPath(path).name in names:
            shown = _git(checkout, 'show', f'{sha}:{path}')
            if shown.returncode != 0:
                msg = f'{checkout.name}: {sha[:12]}:{path} unreadable ({shown.stderr.strip()[-200:]})'
                raise RootsUnread(msg)
            found[path] = shown.stdout
    return found


def collect_roots(
    repos: Mapping[str, Path], forge: Forge, *, names: Sequence[str] = LOCK_NAMES
) -> tuple[dict[str, list[str]], int]:
    """Every sha256 any lock names on any branch of any repo -> where; and how many branches were read.

    Raises:
        RootsUnread: naming EVERY repo that could not be read, after trying all of them.

    """
    roots: dict[str, list[str]] = {}
    unread: list[str] = []
    branches = 0
    for name, checkout in sorted(repos.items()):
        try:
            heads = forge.heads(name, checkout)
            for branch, sha in sorted(heads.items()):
                for path, text in _locks_at(checkout, sha, names).items():
                    for sha256 in _SHA256.findall(text):
                        roots.setdefault(sha256, []).append(f'{name}:{branch}:{path}')
            branches += len(heads)
        except RootsUnread as cause:
            unread.append(str(cause))
    if unread:
        msg = 'the root set would be partial, so no report was written:\n  ' + '\n  '.join(unread)
        raise RootsUnread(msg)
    return roots, branches


def _listed(rows: Iterable[Mapping[str, Any]]) -> tuple[list[Stored], list[str]]:
    stored, foreign = [], []
    for row in rows:
        parts = PurePosixPath(row['Path']).parts
        if len(parts) == 2 and _SHA256.fullmatch(parts[1]) and parts[0] == parts[1][:2]:  # noqa: PLR2004 -- <sha[:2]>/<sha>
            when = datetime.fromisoformat(str(row['ModTime']))
            stored.append(Stored(parts[1], int(row['Size']), when))
        else:
            foreign.append(row['Path'])
    return stored, foreign


def report(
    repos: Mapping[str, Path], forge: Forge, store: Store, *, now: datetime, names: Sequence[str] = LOCK_NAMES
) -> Report:
    """The roots first (a partial set raises before the store is asked), then the store against them."""
    roots, branches = collect_roots(repos, forge, names=names)
    stored, foreign = _listed(store.files())
    held = {item.sha256 for item in stored}
    unreferenced = tuple(
        Unreferenced(item, (now - item.modified).total_seconds() / 86400)
        for item in sorted(stored, key=lambda s: s.modified)
        if item.sha256 not in roots
    )
    missing = tuple(Missing(sha, tuple(where)) for sha, where in sorted(roots.items()) if sha not in held)
    return Report(tuple(sorted(repos)), branches, tuple(stored), len(held & roots.keys()), unreferenced, missing,
                  tuple(sorted(foreign)))  # fmt: skip


def _mib(size: int) -> str:
    return f'{size / (1 << 20):.1f} MiB'


def render(found: Report, *, now: datetime) -> str:
    """The report as Markdown."""
    loose = sum(item.stored.bytes for item in found.unreferenced)
    lines = [
        f'# Oracle GC report (report-only) -- {now:%Y-%m-%dT%H:%M:%SZ}',
        '',
        f'- roots: {len(found.repos)} repos ({", ".join(found.repos)}), {found.branches} branches',
        f'- stored: {len(found.stored)} objects, {_mib(sum(item.bytes for item in found.stored))}',
        f'- referenced and held: {found.referenced}',
        f'- unreferenced: {len(found.unreferenced)} objects, {_mib(loose)}',
        f'- referenced but missing: {len(found.missing)}',
        f'- not an object key: {len(found.foreign)}',
        '',
        '## Unreferenced objects',
        '',
        '| sha256 | bytes | age (days) |',
        '|---|---:|---:|',
        *(f'| `{u.stored.sha256}` | {u.stored.bytes} | {u.age_days:.1f} |' for u in found.unreferenced),
        '',
        '## Referenced but missing',
        '',
        '| sha256 | named by |',
        '|---|---|',
        *(f'| `{m.sha256}` | {"<br>".join(m.named_by)} |' for m in found.missing),
        '',
        '## Not an object key',
        '',
        *(f'- `{path}`' for path in found.foreign),
    ]
    return '\n'.join(lines) + '\n'


@dataclass(frozen=True)
class _RunStore:
    """The declared run store's listing, through :class:`~dev_lab.dev.artifactstores.RcloneStore`."""

    tree: Path

    def files(self) -> list[dict[str, Any]]:
        from dev_lab.dev.artifactstores import RcloneStore  # noqa: PLC0415 -- the real store only on the real run
        from dev_lab.dev.largeobjects import run_objects  # noqa: PLC0415

        objects = run_objects(self.tree)
        if objects is None:
            msg = 'the family declares no run store ([storage] runs): there is nothing to collect'
            raise SystemExit(msg)
        return RcloneStore(objects.remote, objects.prefix, objects.rclone).files(objects.prefix)


def main(argv: Sequence[str] | None = None) -> int:
    """``report [--lock NAME ...]``: write the report; exit 1 naming the unread repos when the roots are partial."""
    from lab_commons.home import repos  # noqa: PLC0415

    from dev_lab.dev.datedlog import dated_log, declared_output  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.oraclegc', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    verb = verbs.add_parser('report', help='write the report-only GC report; never deletes')
    verb.add_argument('--lock', action='append', help=f'a lock basename (default {", ".join(LOCK_NAMES)})')
    args = parser.parse_args(argv)
    tree = Path.cwd()
    now = datetime.now(UTC)
    try:
        found = report(repos(), GitForge(), _RunStore(tree), now=now, names=tuple(args.lock or LOCK_NAMES))
    except RootsUnread as cause:
        sys.stderr.write(f'REFUSED: {cause}\n')
        return 1
    out = dated_log(tree, f'report-{now:%H%M%S}.md', base=declared_output(tree), kind=KIND)
    out.write_text(render(found, now=now), encoding='utf-8')
    sys.stdout.write(f'{out}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
