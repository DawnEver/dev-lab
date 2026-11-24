"""PURGE ONE NAMED PATH: the door that deletes a git-ignored, untracked path of a checkout, and only such a path.

User rulings 2026-11-23: "No backup: everything is merged or deleted" -- and an agent hitting a copied checkout,
a stray directory or a parked bundle under ``output/`` had no door to delete it (raw ``rm -rf`` is denied).

``python -m dev_lab.dev.purge --root <checkout> --path <rel> [--apply] [--limit N]``: a dry run prints what would
go (files, directories, bytes); ``--apply`` removes it. EVERY REFUSAL NAMES ITS CAUSE AND ITS DOOR
(:class:`PurgeRefused`, exit 1). The path is refused when it

* lies outside the checkout, or IS the checkout (a link is judged where it points, never followed);
* does not exist;
* holds a TRACKED file (``git ls-files``) -- tracked work leaves through a commit, never a purge;
* is not git-IGNORED (``git check-ignore``) -- untracked, unignored work is work in progress -- unless it lies in
  the declared scratch (``[tool.dev_lab.placement] scratch``), which holds nothing tracked by declaration;
* is, holds or lies under a ``read_only`` path the repo declares (``[tool.dev_lab.placement] read_only``,
  user-maintained input such as ``temp``, ``attic``);
* is, holds or lies under a declared STORE (``[tool.dev_lab.placement] stores``: a content store, a cache a
  run reads back) -- both keys are the repo's, read here, never hard-coded; a repo declaring neither is refused;
* holds a bundle or patch (:data:`PARKED_SUFFIXES`) that no MERGE-CHECK RECORD classifies :data:`CLEARED`;
* holds more than ``--limit`` entries (the removal is bounded).

MERGE-CHECK RECORDS are JSONL under the repo's declared output, ``<output>/<yy>/<mm>/<dd>/merge-check/*.jsonl``
(:func:`merge_check_records`), one object per line with ``path`` (checkout-relative POSIX) and ``cls``; a later
file's line for a path overrides an earlier one. ``landed`` and ``superseded`` clear a file; ``unlanded``,
``error``, ``unreadable`` or no record keep the whole path.

THE REMOVAL is the walk the dry run counted: bottom-up, a link or junction unlinked and never followed, a
read-only file made writable first. Each removed directory is a JSONL line in today's
``<output>/<yy>/<mm>/<dd>/purge/`` log, closed by a summary line; an entry that appeared after the walk makes its
directory's removal fail, and the failure is logged and reported, never retried wider.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import stat
import subprocess
import time
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

from lab_commons.log import emit

from dev_lab.dev import datedlog
from dev_lab.dev.family import declared_table

__all__ = [
    'CLEARED',
    'DEFAULT_LIMIT',
    'PARKED_SUFFIXES',
    'Plan',
    'PurgeRefused',
    'apply',
    'main',
    'merge_check_records',
    'plan',
]

#: A file that parks work rather than being a product: it goes only once a merge check cleared it.
PARKED_SUFFIXES: Final = frozenset({'.bundle', '.patch', '.diff'})
#: The merge-check classes that say the parked work is on origin, or its content is.
CLEARED: Final = frozenset({'landed', 'superseded'})
#: The most entries one purge removes; a larger tree is refused, naming the flag.
DEFAULT_LIMIT: Final = 2_000_000
_KIND: Final = 'merge-check'
_SHOWN: Final = 20


class PurgeRefused(ValueError):
    """The named path may not be purged: the message names the cause and the door."""


@dataclasses.dataclass(frozen=True)
class Plan:
    """What one purge removes: the path, and its walk (files and links, then directories, deepest first)."""

    root: Path
    rel: str
    leaves: tuple[Path, ...]
    dirs: tuple[Path, ...]
    size: int

    def summary(self) -> str:
        """The dry run's one line: counts and bytes."""
        return f'{self.rel}: {len(self.leaves)} files, {len(self.dirs)} directories, {self.size} bytes'


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=False)  # noqa: S607


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _inside(rel: str, other: str) -> bool:
    """*rel* is *other* or below it."""
    return rel == other or rel.startswith(other.rstrip('/') + '/')


def _declared(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(read_only, stores) *root* declares under ``[tool.dev_lab.placement]``."""
    manifest = root / 'pyproject.toml'
    data = tomllib.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    placement = declared_table(data, 'placement', {})
    found = {}
    for key in ('read_only', 'stores'):
        value = placement.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            msg = (
                f'{manifest} declares no [tool.dev_lab.placement] {key} (a list of checkout-relative paths, may be '
                f'empty): a purge cannot tell what it must never touch. Door: declare read_only (user-maintained '
                f'input, e.g. ["temp", "attic"]) and stores (every content store or cache a run reads back) there.'
            )
            raise PurgeRefused(msg)
        found[key] = tuple(v.strip('/') for v in value)
    return found['read_only'], found['stores']


def merge_check_records(root: Path) -> dict[str, str]:
    """Checkout-relative path -> class, from every ``merge-check/*.jsonl`` under *root*'s declared output."""
    base = datedlog.dated_base(root, datedlog.declared_output(root))
    classes: dict[str, str] = {}
    for record in sorted(base.glob(f'[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/{_KIND}/*.jsonl')):
        for line in record.read_text(encoding='utf-8').splitlines():
            row = json.loads(line) if line.strip() else {}
            if isinstance(row.get('path'), str) and isinstance(row.get('cls'), str):
                classes[row['path'].replace('\\', '/').strip('/')] = row['cls']
    return classes


def _walk(top: Path, limit: int) -> Iterator[tuple[Path, bool]]:
    """(entry, is_dir) under *top*, children before their directory, never following a link; at most *limit*."""
    count = 0
    stack: list[tuple[Path, bool]] = [(top, False)]
    while stack:
        path, listed = stack.pop()
        if listed:
            yield path, True
            continue
        stack.append((path, True))
        with os.scandir(path) as entries:
            for entry in entries:
                count += 1
                if count > limit:
                    msg = f'more than {limit} entries: the removal is bounded. Door: pass --limit N above the count.'
                    raise PurgeRefused(msg)
                child = Path(entry.path)
                if entry.is_dir(follow_symlinks=False) and not entry.is_junction():
                    stack.append((child, False))
                else:
                    yield child, False


def _in_scratch(root: Path, rel: str) -> bool:
    """*rel* lies strictly below *root*'s declared scratch directory."""
    manifest = root / 'pyproject.toml'
    data = tomllib.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    scratch = declared_table(data, 'placement', {}).get('scratch')
    return isinstance(scratch, str) and bool(scratch.strip('/')) and rel.startswith(scratch.strip('/') + '/')


def _refuse_scope(root: Path, rel: str, target: Path) -> None:
    if target == root or root not in target.parents:
        msg = f'{rel} is outside the checkout {root} (or is the checkout). Door: purge a path inside it, from its root.'
        raise PurgeRefused(msg)
    if not target.exists() and not _is_link(target):
        msg = f'{rel} does not exist under {root}. Door: name an existing checkout-relative path.'
        raise PurgeRefused(msg)
    tracked = _git(root, 'ls-files', '-z', '--', rel).stdout.split(b'\0')
    if any(tracked):
        msg = (
            f'{rel} holds {len([t for t in tracked if t])} tracked files ({tracked[0].decode(errors="replace")} ...). '
            'Door: tracked work leaves through a commit (git rm on a branch, landed by a PR), never a purge.'
        )
        raise PurgeRefused(msg)
    if _git(root, 'check-ignore', '-q', '--', rel).returncode != 0 and not _in_scratch(root, rel):
        msg = (
            f'{rel} is untracked but not git-ignored: that is work in progress. Door: commit it on its branch, or '
            'ignore its location in .gitignore through a reviewed commit, then purge.'
        )
        raise PurgeRefused(msg)


def _refuse_declared(root: Path, rel: str) -> None:
    read_only, stores = _declared(root)
    for what, paths, door in (
        ('read_only', read_only, 'it is user-maintained input; only the user edits it'),
        ('stores', stores, 'a store is pruned by its own eviction, never purged'),
    ):
        hit = [p for p in paths if _inside(rel, p) or _inside(p, rel)]
        if hit:
            msg = f'{rel} is, holds or lies under the declared {what} path {hit[0]} ([tool.dev_lab.placement]). '
            msg += f'Door: {door}.'
            raise PurgeRefused(msg)


def plan(root: Path, rel: str, *, limit: int = DEFAULT_LIMIT) -> Plan:
    """The purge of *rel* under *root*, once every refusal passed.

    Raises:
        PurgeRefused: any refusal the module docstring lists; the message names the door.

    """
    root = root.resolve()
    rel = Path(rel).as_posix().strip('/')
    target = (root / rel).resolve() if not _is_link(root / rel) else root / rel
    _refuse_scope(root, rel, target)
    rel = target.relative_to(root).as_posix()
    _refuse_declared(root, rel)
    if _is_link(target) or target.is_file():
        leaves, dirs = (target,), ()
    else:
        walked = list(_walk(target, limit))
        leaves = tuple(p for p, is_dir in walked if not is_dir)
        dirs = tuple(p for p, is_dir in walked if is_dir)
    parked = [p.relative_to(root).as_posix() for p in leaves if p.suffix in PARKED_SUFFIXES and not _is_link(p)]
    if parked:
        records = merge_check_records(root)
        open_ = [f'{p} ({records.get(p, "no record")})' for p in parked if records.get(p) not in CLEARED]
        if open_:
            listed = '\n  '.join(open_[:_SHOWN]) + (
                f'\n  ... and {len(open_) - _SHOWN} more' if len(open_) > _SHOWN else ''
            )
            msg = (
                f'{rel} holds {len(open_)} bundles or patches no merge check cleared:\n  {listed}\n'
                f'Door: land each through a PR, then record it landed/superseded in a {_KIND}/*.jsonl under the '
                'declared output; an unlanded one is merged, never purged.'
            )
            raise PurgeRefused(msg)
    size = sum(p.lstat().st_size for p in leaves)
    return Plan(root=root, rel=rel, leaves=leaves, dirs=dirs, size=size)


def _unlink(path: Path) -> None:
    if path.is_junction() or (path.is_symlink() and path.is_dir() and os.name == 'nt'):
        path.rmdir()
        return
    try:
        path.unlink()
    except PermissionError:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def apply(purge: Plan) -> list[str]:
    """Remove *purge*'s walk bottom-up, logging each directory; returns the failures (empty: all gone)."""
    log = datedlog.output_dir(purge.root, 'purge') / f'purge-{time.strftime("%H%M%S")}-{os.getpid()}.jsonl'
    failures: list[str] = []
    files_in: dict[Path, int] = {}
    with log.open('a', encoding='utf-8') as out:
        for leaf in purge.leaves:
            try:
                _unlink(leaf)
                files_in[leaf.parent] = files_in.get(leaf.parent, 0) + 1
            except OSError as exc:
                failures.append(f'{leaf}: {exc}')
        for directory in purge.dirs:
            try:
                directory.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                directory.rmdir()
                row = {'removed': directory.relative_to(purge.root).as_posix(), 'files': files_in.get(directory, 0)}
            except OSError as exc:
                failures.append(f'{directory}: {exc}')
                row = {'failed': directory.relative_to(purge.root).as_posix(), 'error': str(exc)}
            out.write(json.dumps(row) + '\n')
        out.write(
            json.dumps(
                {
                    'purged': purge.rel,
                    'files': len(purge.leaves),
                    'dirs': len(purge.dirs),
                    'bytes': purge.size,
                    'failures': len(failures),
                }
            )
            + '\n'
        )
    emit(f'log: {log}')
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.purge --root <checkout> --path <rel> [--apply] [--limit N]``."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.purge', description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', type=Path, required=True, help='the checkout')
    parser.add_argument('--path', required=True, help='the checkout-relative path to delete')
    parser.add_argument('--apply', action='store_true', help='delete; without it, a dry run')
    parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help='the most entries one purge removes')
    args = parser.parse_args(argv)
    try:
        purge = plan(args.root, args.path, limit=args.limit)
    except PurgeRefused as exc:
        emit(f'purge refused: {exc}', err=True)
        return 1
    emit(('purging ' if args.apply else 'would purge ') + purge.summary())
    if not args.apply:
        return 0
    failures = apply(purge)
    for failure in failures[:_SHOWN]:
        emit(f'  not removed: {failure}', err=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
