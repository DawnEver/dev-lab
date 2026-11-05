"""WRITES-STAY-IN-THE-TREE, the census and the sweep over the write-prone roots of :mod:`dev_lab.dev.writeroots`.

The shape of ``codeplace stray``: ONE census (:func:`census`, one level deep, never walked past a root's direct
entries), read by three callers --

* the ``Stop`` hook (``python -m dev_lab.dev.tmpsweep stop``) REPORTS the scripts and notes this session left in a
  root (:func:`session_report`), blocking the stop once; it never deletes;
* the command (``python -m dev_lab.dev.tmpsweep``) prints the census; ``--apply`` removes what :func:`sweep`
  admits, for a person or a scheduled task to run;
* :func:`sweep` itself, which removes an entry only when its root is a ``temp`` root, it is older than the age in
  EVERY file it holds (a fresh file is a live writer), it is no link or junction (never followed out of the root),
  it holds no ``.git`` (a checkout is somebody's work), and the filesystem lets go of it (an open file is kept).

Excluded paths (:func:`dev_lab.dev.writeroots.excluded_paths`: the harness ``claude/`` subtree, declared caches)
are never listed, so nothing can remove them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.codeplace import CODE_SUFFIXES
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.writeroots import REMEDY, RULE_ID, Root, excluded_paths, write_prone_roots

__all__ = ['MAX_AGE_DAYS', 'REPORT_WINDOW_S', 'Entry', 'census', 'main', 'session_report', 'sweep']

#: The age past which a ``temp`` root's entry is swept.
MAX_AGE_DAYS: Final = 7.0
#: How far back the Stop report looks when the session's start cannot be read off its transcript.
REPORT_WINDOW_S: Final = 12 * 3600.0
#: What the Stop report names: what an agent writes by hand -- a script, or a note.
_REPORTED_SUFFIXES: Final = CODE_SUFFIXES | {'.md', '.txt'}
_SHOWN: Final = 5
_DAY: Final = 86400.0


@dataclass(frozen=True, slots=True)
class Entry:
    """One direct entry of a write-prone root."""

    path: Path
    root: Root
    mtime: float


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _excluded(path: Path, excluded: Sequence[Path]) -> bool:
    return any(path == one or one in path.parents for one in excluded)


def census(roots: Iterable[Root], excluded: Iterable[Path]) -> list[Entry]:
    """Every direct entry of each root that exists, minus *excluded*; a ``home`` root lists loose non-dot files."""
    skip = tuple(excluded)
    found: list[Entry] = []
    for root in roots:
        try:
            children = sorted(root.path.iterdir())
        except OSError:
            continue  # absent or unreadable: nothing written there to name
        for child in children:
            if _excluded(child, skip):
                continue
            if root.kind == 'home' and (child.name.startswith('.') or _linked(child) or not child.is_file()):
                continue
            try:
                found.append(Entry(child, root, child.lstat().st_mtime))
            except OSError:
                continue  # gone between listing and stat
    return found


def _newest(path: Path) -> float:
    """The newest mtime in *path*'s tree, links not followed."""
    newest = path.lstat().st_mtime
    if path.is_dir() and not _linked(path):
        for current, dirs, files in os.walk(path, followlinks=False):
            for name in (*dirs, *files):
                newest = max(newest, (Path(current) / name).lstat().st_mtime)
    return newest


def _why_kept(entry: Entry, cutoff: float) -> str | None:
    if entry.root.kind != 'temp':
        return f'a {entry.root.kind} root is reported, never swept'
    if _linked(entry.path):
        return 'a link or junction is never followed'
    if (entry.path / '.git').exists():
        return 'a checkout'
    if _newest(entry.path) > cutoff:
        return 'written within the age: in use'
    return None


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def sweep(
    entries: Iterable[Entry], *, max_age_days: float = MAX_AGE_DAYS, now: float | None = None
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Remove each entry the module docstring admits; return ``(removed, [(kept, why)])``."""
    cutoff = (time.time() if now is None else now) - max_age_days * _DAY
    removed: list[Path] = []
    kept: list[tuple[Path, str]] = []
    for entry in entries:
        try:
            why = _why_kept(entry, cutoff)
            if why is None:
                _remove(entry.path)
                removed.append(entry.path)
                continue
        except OSError as exc:
            why = f'held or unreadable: {exc.strerror or exc}'
        kept.append((entry.path, why))
    return removed, kept


def session_report(roots: Iterable[Root], excluded: Iterable[Path], *, since: float) -> str | None:
    """The ``WRITES-STAY-IN-THE-TREE`` report: scripts and notes written into a root after *since*; else ``None``."""
    found = [
        entry.path.as_posix()
        for entry in census(roots, excluded)
        if entry.mtime >= since and entry.path.suffix.lower() in _REPORTED_SUFFIXES
    ]
    if not found:
        return None
    shown = ', '.join(found[:_SHOWN]) + (f' (+{len(found) - _SHOWN} more)' if len(found) > _SHOWN else '')
    return (
        f'{RULE_ID}: {len(found)} file(s) written outside every checkout this session: {shown}.\n'
        f'Move each into the checkout and delete the original: {REMEDY}\n{details_for(RULE_ID)}'
    )


def _declared() -> tuple[tuple[Root, ...], tuple[Path, ...]]:
    roots = write_prone_roots()
    return roots, excluded_paths(roots)


def _session_start(payload: dict) -> float:
    """When the session began: its transcript's creation, else :data:`REPORT_WINDOW_S` ago."""
    transcript = payload.get('transcript_path')
    try:
        birth = getattr(Path(str(transcript)).stat(), 'st_birthtime', None) if transcript else None
    except OSError:
        birth = None
    return float(birth) if birth else time.time() - REPORT_WINDOW_S


def _stop(stdin: TextIO) -> int:
    try:
        payload = json.load(stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get('stop_hook_active'):
        return 0  # blocked once already: a file the agent cannot clear must not loop the session
    roots, excluded = _declared()
    reason = session_report(roots, excluded, since=_session_start(payload))
    if reason is not None:
        emit(json.dumps({'decision': 'block', 'reason': reason}))
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``stop``: the Stop hook. Otherwise the census, read-only unless ``--apply``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ['stop']:
        return _stop(stdin or sys.stdin)
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.tmpsweep', description=__doc__.splitlines()[0])
    parser.add_argument('--apply', action='store_true', help='remove what the sweep admits (default: list only)')
    parser.add_argument('--max-age-days', type=float, default=MAX_AGE_DAYS, help='sweep entries older than this')
    opts = parser.parse_args(args)
    roots, excluded = _declared()
    entries = census(roots, excluded)
    if not opts.apply:
        for entry in entries:
            day = time.strftime('%Y-%m-%d', time.localtime(entry.mtime))
            emit(f'{entry.root.kind:6} {day} {entry.path.as_posix()}')
        emit(f'{len(entries)} entr(y/ies) in {len(roots)} write-prone root(s); --apply sweeps the temp roots')
        return 0
    removed, kept = sweep(entries, max_age_days=opts.max_age_days)
    for path in removed:
        emit(f'removed {path.as_posix()}')
    for path, why in kept:
        emit(f'kept    {path.as_posix()} -- {why}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
