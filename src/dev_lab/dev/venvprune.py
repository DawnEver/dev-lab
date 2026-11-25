"""SUPERSEDED ENVIRONMENTS GO THROUGH A DOOR: list, then remove, the ``.venvs/<name>`` no launch will take again.

:mod:`dev_lab.dev.venvcurrent` publishes each new environment beside the live one and reclaims the old ones after a
publish; one a holder kept then, or one a checkout never re-published past, stays on disk. This door sweeps them
across many checkouts at once. Per checkout whose ``.venv`` is a link it KEEPS: the environment the link
names, the newest one (by its ``<utc stamp>``), and any a live process executes from (the holder
census of :func:`dev_lab.dev.liverun.removal_holders`, as ``dep`` reads it). Everything else is listed with its bytes
and, with ``--apply``, removed moved-aside first (:func:`dev_lab.dev.venvcurrent.reclaimed`). A checkout without a
pointer is the legacy layout and is left alone.

A HALF-BUILT environment (a ``<name>.building`` marker beside it, :func:`dev_lab.dev.venvcurrent.fresh`) is read in
every checkout with a ``.venvs/``, pointer or not (:func:`builds`): kept while its builder lives, else ABANDONED and
removed with its marker; the ``build.lock`` no process holds then goes too.

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
from dev_lab.dev.servelock import held
from dev_lab.dev.venvcurrent import BUILD_LOCK, BUILDING, RECLAIMING, building, reclaimed
from dev_lab.dev.venvpointer import HOME, POINTER, is_link, named

__all__ = ['Row', 'builds', 'checkouts', 'main', 'plan']

#: The ``<utc stamp>`` :func:`dev_lab.dev.venvcurrent.fresh` puts in every environment's name.
_STAMP: Final = re.compile(r'\d{8}T\d{6}Z')


@dataclass(frozen=True)
class Row:
    """One environment: its bytes and why it is kept, ``''`` when it goes."""

    env: Path
    bytes: int
    keep: str


def checkouts(roots: Iterable[Path]) -> Iterator[Path]:
    """Each checkout (a :data:`POINTER` link or :data:`HOME`) at, under (one level) or in the worktrees of a root."""
    for root in map(Path, roots):
        if not root.is_dir():
            continue
        repos = [root] if _is_checkout(root) else sorted(p for p in root.iterdir() if p.is_dir())
        for repo in repos:
            if _is_checkout(repo):
                yield repo
            trees = repo / '.claude' / 'worktrees'
            if trees.is_dir():
                yield from (tree for tree in sorted(trees.iterdir()) if _is_checkout(tree))


def _is_checkout(path: Path) -> bool:
    return is_link(path / POINTER) or (path / HOME).is_dir()


def _stamp(env: Path) -> str:
    hit = _STAMP.search(env.name)
    return hit.group(0) if hit else ''


def plan(root: Path, *, census: Census = processes) -> tuple[Row, ...]:
    """Each environment of *root* with its bytes and keep reason; ``()`` for a checkout with no pointer."""
    root = Path(root)
    live, home = named(root), root / HOME
    if live is None or not home.is_dir():
        return ()
    marked = {m.name.removesuffix(BUILDING) for m in home.glob(f'*{BUILDING}')}
    envs = sorted(p for p in home.iterdir() if p.is_dir() and not p.name.endswith(BUILDING) and p.name not in marked)
    if not envs:
        return ()
    newest = max(envs, key=lambda p: (not p.name.endswith(RECLAIMING), _stamp(p), p.name))
    table = tuple(census())
    rows = []
    for env in envs:
        if env.name == live.name:
            keep = 'current'
        elif env == newest:
            keep = 'newest'
        elif users := removal_holders(env, census=lambda: table):
            keep = f'held by {len(users)} process(es)'
        else:
            keep = ''
        rows.append(Row(env, measure(env)[0], keep))
    return tuple(rows)


def builds(root: Path, *, census: Census = processes) -> tuple[Row, ...]:
    """Each half-built environment of *root* (a :data:`BUILDING` marker in its :data:`HOME`) and its keep reason.

    A build is kept only while its builder is ALIVE: the pid the marker names is in the census and the marker is
    younger than :data:`BUILD_WALL_S` (an older one is a dead builder's, its pid possibly reused). Else it is
    abandoned, ``keep == ''``. Read for any checkout with a :data:`HOME`, pointer or not.
    """
    home = Path(root) / HOME
    if not home.is_dir():
        return ()
    pids = {p.pid for p in census()}
    rows = []
    for marker in sorted(home.glob(f'*{BUILDING}')):
        env = marker.with_name(marker.name.removesuffix(BUILDING))
        pid = marker.read_text(encoding='utf-8', errors='replace').strip()
        alive = building(env) and (not pid.isdigit() or int(pid) in pids)
        size = measure(env)[0] if env.is_dir() else 0
        rows.append(Row(env, size, f'builder pid {pid or "?"} alive' if alive else ''))
    return tuple(rows)


def _abandon(env: Path, *, apply: bool) -> str:
    """Remove an abandoned build: its environment (moved aside first), then its marker."""
    if not apply:
        return f'would remove {env.name}'
    line = reclaimed(env) if env.is_dir() else f'reclaimed {env}'
    if line.startswith('reclaimed'):
        env.with_name(env.name + BUILDING).unlink(missing_ok=True)
    return line


def _stale_lock(root: Path) -> str:
    """Remove :data:`BUILD_LOCK` when no process holds it and no build marker is left; the line saying so, or ``''``."""
    home = Path(root) / HOME
    lock = home / BUILD_LOCK
    if not lock.is_file() or any(home.glob(f'*{BUILDING}')):
        return ''
    with held(lock) as mine:
        if not mine:
            return ''
    try:
        lock.unlink(missing_ok=True)
    except OSError as exc:  # a build took it between the release and the unlink
        return f'kept     {lock}  ({exc})'
    return f'reclaimed {lock}'


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
        if half := builds(root, census=lambda: table):
            lines.append('  half-built (.building marker; abandoned builds go: builder dead or marker past the wall):')
        for row in half:
            if row.keep:
                lines.append(f'  keep         {row.env.name}  ({row.keep})')
                continue
            total += row.bytes
            lines.append(f'  {_abandon(row.env, apply=args.apply)}  {_gib(row.bytes)}')
        if args.apply and (line := _stale_lock(root)):
            lines.append(f'  {line}')
    verb = 'reclaimed' if args.apply else 'reclaimable'
    lines.append(f'{verb}: {total} bytes ({_gib(total)})')
    out.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
