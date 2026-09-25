"""Where source code may live, and the lifecycle of a one-off script -- one scan, every repo.

Migrated 2026-09-25 from motronics-studio, where a probe, a patch script and 132 one-off drivers had
accumulated under ``output/logs/...``: untracked, untested, and never reaching the entry point the
repo ships. One of them patched ``src/`` instead of the function it was changing being edited.

TWO RULES, ONE MODULE, because the second is the exit from the first:

* ``CODE-IN-CODE-ROOTS`` -- a source file (:data:`CODE_SUFFIXES`) lives only under a root the repo
  DECLARES for code. An ALLOW-list, not a deny-list: a new directory is refused until it is added
  on purpose, so the next ``output/`` cannot happen silently. The walk is of the FILESYSTEM, never
  ``git ls-files``, because the defect is precisely an untracked file.
* ``SCRATCH-ARCHIVED-OR-PROMOTED`` -- a one-off lives in the repo's scratch directory for a bounded
  time, then is either PROMOTED into the function that owns its behaviour or ARCHIVED as evidence
  beside that day's memory (``<memory>/<yyyy>/<mm>/<dd>/attachments/``) with its reason recorded.

THE ROOTS, THE SCRATCH DIRECTORY AND THE MEMORY ROOT ARE THE REPO'S ANSWER AND HAVE NO DEFAULT --
the same stance as :mod:`lab_commons.dev.datedlog`: the family's repos lay out differently, and a
default here would hand one repo's layout to the others while looking like a convention.
"""

from __future__ import annotations

import datetime
import os
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

__all__ = [
    'ARCHIVE_DIRECTORY',
    'CODE_SUFFIXES',
    'PRUNED_NAMES',
    'archive_scratch',
    'misplaced_code',
    'overdue_scratch',
    'pending_scratch',
]

#: The file suffixes that are SOURCE CODE -- a language a machine executes or compiles.
CODE_SUFFIXES = frozenset({
    '.py', '.pyx', '.pyi', '.rs', '.sh', '.bash', '.ps1', '.psm1', '.bat', '.cmd', '.vbs',
    '.js', '.mjs', '.cjs', '.ts', '.m', '.lua', '.jl', '.c', '.cc', '.cpp', '.h', '.hpp',
})  # fmt: skip

#: Directories never walked, matched by NAME at any depth: tool state, environments and build
#: output, none of it written by a person.
PRUNED_NAMES = frozenset({
    '.git', '.venv', 'venv', 'node_modules', 'target', '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache',
})  # fmt: skip

#: The directory under a day's memory that holds archived one-offs, with an ``INDEX.md`` of reasons.
ARCHIVE_DIRECTORY = 'attachments'
_INDEX = 'INDEX.md'
_SECONDS_PER_DAY = 86400.0


def misplaced_code(root: Path, *, code_roots: Iterable[str], pruned_paths: Iterable[str] = ()) -> list[str]:
    """Every source file under *root* that no *code_roots* prefix admits, repo-relative POSIX, sorted.

    Args:
        root: the tree to walk.
        code_roots: repo-relative POSIX prefixes where code may live, e.g. ``'src/'``.
        pruned_paths: repo-relative directories not walked at all -- another checkout's worktrees,
            which are judged by their own run.

    Raises:
        ValueError: no code roots -- a scan that admits nothing refuses every repo, and one that is
            handed an empty list by mistake must not read as a verdict.

    """
    roots = tuple(code_roots)
    if not roots:
        msg = 'misplaced_code needs the code roots this repo declares; an empty allow-list refuses everything'
        raise ValueError(msg)
    skip = {p.strip('/') for p in pruned_paths}
    found: list[str] = []
    for current, dirs, files in os.walk(root):
        rel_dir = Path(current).relative_to(root).as_posix()
        dirs[:] = [d for d in dirs if d not in PRUNED_NAMES and (d if rel_dir == '.' else f'{rel_dir}/{d}') not in skip]
        for name in files:
            if Path(name).suffix.lower() not in CODE_SUFFIXES:
                continue
            rel = name if rel_dir == '.' else f'{rel_dir}/{name}'
            if not rel.startswith(roots):
                found.append(rel)
    return sorted(found)


def pending_scratch(scratch: Path, *, root: Path, now: float | None = None) -> list[tuple[str, float]]:
    """``[(root-relative path, age in days), ...]`` of every file in *scratch*, oldest first."""
    if not scratch.is_dir():
        return []
    stamp = time.time() if now is None else now
    rows = [
        (path.relative_to(root).as_posix(), (stamp - path.stat().st_mtime) / _SECONDS_PER_DAY)
        for path in scratch.rglob('*')
        if path.is_file() and not PRUNED_NAMES.intersection(path.relative_to(scratch).parts)
    ]
    return sorted(rows, key=lambda row: -row[1])


def overdue_scratch(scratch: Path, *, root: Path, max_age_days: float, now: float | None = None) -> list[str]:
    """The scratch files older than *max_age_days*: each must be archived or promoted."""
    return [path for path, age in pending_scratch(scratch, root=root, now=now) if age > max_age_days]


def archive_scratch(
    source: Path, *, why: str, root: Path, memory: Path, day: datetime.date | None = None, name: str | None = None
) -> Path:
    """Move *source* into ``<memory>/<yyyy>/<mm>/<dd>/attachments/`` and record *why* in its INDEX.

    Args:
        source: the one-off, absolute or relative to *root*.
        why: the finding it produced -- required, because an archive without a reason is a heap.
        root: the repository root, for the recorded origin.
        memory: the repository's dated memory root, e.g. ``root / '.claude' / 'memory'``.
        day: the memory day it belongs to; the file's own modification day when omitted.
        name: the archived file name; the source's own name when omitted.

    Raises:
        ValueError: an empty reason, a missing source, or a destination that already exists.

    """
    reason = why.strip()
    if not reason:
        msg = 'an archived script must say WHY it is kept -- the finding it produced'
        raise ValueError(msg)
    src = source if source.is_absolute() else root / source
    if not src.is_file():
        msg = f'{src} is not a file'
        raise ValueError(msg)
    date = day or datetime.datetime.fromtimestamp(src.stat().st_mtime, tz=datetime.UTC).date()
    folder = memory / f'{date:%Y}' / f'{date:%m}' / f'{date:%d}' / ARCHIVE_DIRECTORY
    dest = folder / (name or src.name)
    if dest.exists():
        msg = f'{dest} already exists; archive it under another name or day'
        raise ValueError(msg)
    origin = src.relative_to(root).as_posix() if src.is_relative_to(root) else str(src)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    index = folder / _INDEX
    header = '' if index.exists() else '# Archived one-off scripts\n\n'
    with index.open('a', encoding='utf-8') as handle:
        handle.write(f'{header}- `{dest.name}` -- {reason} (from `{origin}`)\n')
    return dest
