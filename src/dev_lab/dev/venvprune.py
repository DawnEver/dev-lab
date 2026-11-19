"""SUPERSEDED ENVIRONMENTS GO THROUGH A DOOR: list, then remove, the ``.venvs/<name>`` no launch will take again.

:mod:`dev_lab.dev.venvcurrent` publishes each new environment beside the live one and reclaims the old ones after a
publish; one a holder kept then, or one a checkout never re-published past, stays on disk. This door sweeps them
across many checkouts at once. Per checkout with a ``.venv-current`` pointer it KEEPS: the environment the pointer
names, the newest one (by its ``<utc stamp>``), one being built, and any a live process executes from (the holder
census of :func:`dev_lab.dev.liverun.removal_holders`, as ``dep`` reads it). Everything else is listed with its bytes
and, with ``--apply``, removed moved-aside first (:func:`dev_lab.dev.venvcurrent.reclaimed`). A checkout without a
pointer is the legacy layout and is left alone.

``python -m dev_lab.dev.venvprune [--apply] [ROOT ...]``: each ROOT is a checkout, or a directory whose children
(and their ``.claude/worktrees/*``) are; default the current directory. Dry run by default; always exits 0.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.census import processes

from dev_lab.dev.diskusage import measure
from dev_lab.dev.liverun import Census, removal_holders
from dev_lab.dev.venvcurrent import BUILDING, RECLAIMING, building, reclaimed
from dev_lab.dev.venvpointer import HOME, POINTER, named

__all__ = ['Row', 'checkouts', 'main', 'plan']

#: The ``<utc stamp>`` :func:`dev_lab.dev.venvcurrent.fresh` puts in every environment's name.
_STAMP: Final = re.compile(r'\d{8}T\d{6}Z')


@dataclass(frozen=True)
class Row:
    """One environment: its bytes and why it is kept, ``''`` when it goes."""

    env: Path
    bytes: int
    keep: str


def checkouts(roots: Iterable[Path]) -> Iterator[Path]:
    """Every checkout with a :data:`POINTER` at, under (one level), or in the ``.claude/worktrees/`` of each root."""
    for root in map(Path, roots):
        if not root.is_dir():
            continue
        repos = [root] if (root / POINTER).is_file() else sorted(p for p in root.iterdir() if p.is_dir())
        for repo in repos:
            if (repo / POINTER).is_file():
                yield repo
            trees = repo / '.claude' / 'worktrees'
            if trees.is_dir():
                yield from (tree for tree in sorted(trees.iterdir()) if (tree / POINTER).is_file())


def _stamp(env: Path) -> str:
    hit = _STAMP.search(env.name)
    return hit.group(0) if hit else ''


def plan(root: Path, *, census: Census = processes) -> tuple[Row, ...]:
    """Each environment of *root* with its bytes and keep reason; ``()`` for a checkout with no pointer."""
    root = Path(root)
    live, home = named(root), root / HOME
    if live is None or not home.is_dir():
        return ()
    envs = sorted(p for p in home.iterdir() if p.is_dir() and not p.name.endswith(BUILDING))
    newest = max(envs, key=lambda p: (not p.name.endswith(RECLAIMING), _stamp(p), p.name))
    table = tuple(census())
    rows = []
    for env in envs:
        if env.name == live.name:
            keep = 'current'
        elif env == newest:
            keep = 'newest'
        elif building(env):
            keep = 'being built'
        elif users := removal_holders(env, census=lambda: table):
            keep = f'held by {len(users)} process(es)'
        else:
            keep = ''
        rows.append(Row(env, measure(env)[0], keep))
    return tuple(rows)


def _gib(size: int) -> str:
    return f'{size / 2**30:.2f} GiB'


def main(argv: Sequence[str] | None = None, *, census: Census = processes) -> int:
    """List (or with ``--apply`` remove) every unkept environment under the roots; always 0."""
    out = sys.stdout
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.venvprune', description=__doc__.split('\n')[0])
    parser.add_argument('--apply', action='store_true', help='remove what the dry run lists')
    parser.add_argument('roots', nargs='*', type=Path, default=[Path.cwd()])
    args = parser.parse_args(argv)
    table = tuple(census())
    lines, total = [], 0
    for root in checkouts(args.roots):
        lines.append(str(root))
        for row in plan(root, census=lambda: table):
            if row.keep:
                lines.append(f'  keep         {row.env.name}  ({row.keep})')
                continue
            total += row.bytes
            line = reclaimed(row.env) if args.apply else f'would remove {row.env.name}'
            lines.append(f'  {line}  {_gib(row.bytes)}')
    verb = 'reclaimed' if args.apply else 'reclaimable'
    lines.append(f'{verb}: {total} bytes ({_gib(total)})')
    out.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
