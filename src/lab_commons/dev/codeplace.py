"""Where source code may live, and the lifecycle of a one-off script -- one scan, every repo.

Migrated 2026-09-25 from consumer-a, where a probe, a patch script and 132 one-off drivers had
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

THE PLACEMENT MAP IS THE FAMILY'S, THE EXTRA ROOTS ARE THE REPO'S (user ruling 2026-10-02). Every
file kind has ONE home, :data:`FAMILY_HOMES`; the homes that hold code are :data:`FAMILY_CODE_ROOTS`.
A repo declares ONLY what it adds, in ONE place -- ``[tool.lab_commons.placement]`` of its
``pyproject.toml``, read by :func:`declared_placement`::

    [tool.lab_commons.placement]
    code_roots = ['rust/', 'attic/']        # the repo's own roots, beyond the family's
    pruned_paths = ['.claude/worktrees']    # other checkouts inside this one, judged by their own run

ONE TABLE, ONE PREDICATE, TWO CALLERS. The architecture test calls :func:`declared_misplaced` over
the tree; the ``PreToolUse`` hook (``python -m lab_commons.dev.codeplace``, wired on
``Write|Edit|MultiEdit``) calls :func:`refuse_write` on the one path about to be written. Both
decide through :func:`admits` over the same declaration, so the hook cannot refuse what the test
admits or the reverse -- the second copy of the rule a hand-written hook would be. The scratch
directory and the memory root stay the repo's answer to the lifecycle functions, with no default.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import shutil
import sys
import time
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from lab_commons.log import emit

__all__ = [
    'ARCHIVE_DIRECTORY',
    'CODE_SUFFIXES',
    'FAMILY_CODE_ROOTS',
    'FAMILY_HOMES',
    'PRUNED_NAMES',
    'Placement',
    'PlacementNotDeclared',
    'admits',
    'archive_scratch',
    'declared_misplaced',
    'declared_placement',
    'main',
    'misplaced_code',
    'overdue_scratch',
    'pending_scratch',
    'refuse_write',
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

#: THE FAMILY PLACEMENT MAP: every file kind and its ONE home, repo-relative POSIX.
FAMILY_HOMES: dict[str, str] = {
    'product source': 'src/',
    'tests': 'tests/',
    'repo-development mechanism': 'scripts/',
    'one-off experiment, probe or verification': 'scratch/',
    'memory, and archived one-offs': '.claude/memory/',
    'docs': 'docs-src/',
    'artefacts': 'output/logs/',
}

#: The family homes that hold CODE; docs and artefacts are homes, but never for a source file.
FAMILY_CODE_ROOTS: tuple[str, ...] = tuple(
    FAMILY_HOMES[kind]
    for kind in (
        'product source',
        'tests',
        'repo-development mechanism',
        'one-off experiment, probe or verification',
        'memory, and archived one-offs',
    )
)

#: The directory under a day's memory that holds archived one-offs, with an ``INDEX.md`` of reasons.
ARCHIVE_DIRECTORY = 'attachments'
_INDEX = 'INDEX.md'
_SECONDS_PER_DAY = 86400.0
#: Where a repo declares its delta: ``[tool.lab_commons.placement]`` in this file.
_MANIFEST = 'pyproject.toml'
_TABLE = '[tool.lab_commons.placement]'


def admits(rel: str, code_roots: tuple[str, ...]) -> bool:
    """THE ONE PREDICATE: may repo-relative POSIX *rel* live where it is? A non-code file always may."""
    return Path(rel).suffix.lower() not in CODE_SUFFIXES or rel.startswith(code_roots)


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
            rel = name if rel_dir == '.' else f'{rel_dir}/{name}'
            if not admits(rel, roots):
                found.append(rel)
    return sorted(found)


class PlacementNotDeclared(LookupError):
    """A repo's ``[tool.lab_commons.placement]`` is absent or not the declared shape."""


@dataclasses.dataclass(frozen=True)
class Placement:
    """A repo's placement: the family code roots plus its own, and the paths not walked."""

    code_roots: tuple[str, ...]
    pruned_paths: tuple[str, ...] = ()


def _strings(table: dict, key: str, manifest: Path) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f'{_TABLE} {key} in {manifest} is {value!r}; it must be a list of repo-relative POSIX paths'
        raise PlacementNotDeclared(msg)
    return tuple(value)


def declared_placement(root: Path) -> Placement:
    """The placement *root* declares: :data:`FAMILY_CODE_ROOTS` plus its own ``code_roots``.

    Raises:
        PlacementNotDeclared: no manifest, no table, or a key that is not a list of strings. An
            adopter's test calls this, so an undeclared repo is a red rather than a vacuous green.

    """
    manifest = root / _MANIFEST
    try:
        data = tomllib.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f'{manifest} is not a readable TOML manifest: {exc}'
        raise PlacementNotDeclared(msg) from exc
    table = data.get('tool', {}).get('lab_commons', {}).get('placement')
    if not isinstance(table, dict):
        msg = f'{manifest} declares no {_TABLE}; add it, even empty, to adopt the family placement map'
        raise PlacementNotDeclared(msg)
    extra = _strings(table, 'code_roots', manifest)
    return Placement((*FAMILY_CODE_ROOTS, *extra), _strings(table, 'pruned_paths', manifest))


def declared_misplaced(root: Path) -> list[str]:
    """:func:`misplaced_code` over *root* with the placement *root* declares -- the adopter's scan."""
    placement = declared_placement(root)
    return misplaced_code(root, code_roots=placement.code_roots, pruned_paths=placement.pruned_paths)


def _home_for(rel: str) -> str:
    path = Path(rel)
    if path.name.startswith('test_') or path.stem.endswith('_test') or path.name == 'conftest.py':
        return FAMILY_HOMES['tests']
    return (
        f'{FAMILY_HOMES["product source"]} if it is product code, '
        f'{FAMILY_HOMES["one-off experiment, probe or verification"]} if it is a one-off experiment, '
        f'probe or verification (archived or promoted later), {FAMILY_HOMES["repo-development mechanism"]} '
        f'ONLY if it is repo-development mechanism with no business logic'
    )


def _checkout_root(path: Path) -> Path | None:
    return next((candidate for candidate in path.parents if (candidate / '.git').exists()), None)


def refuse_write(path: Path) -> str | None:
    """The refusal for writing code at *path*, naming its home; ``None`` when the write is admitted.

    The checkout is the nearest ancestor holding ``.git`` -- a linked worktree's own, so a lane inside
    the checkout is judged by its own declaration. A path in no checkout, or in one that declares no
    placement, is not this hook's to judge: the adopter's own test reds on a missing declaration.
    """
    target = Path(path).resolve()
    root = _checkout_root(target)
    if root is None:
        return None
    try:
        placement = declared_placement(root)
    except PlacementNotDeclared:
        return None
    rel = target.relative_to(root).as_posix()
    pruned = tuple(f'{p.strip("/")}/' for p in placement.pruned_paths)
    if PRUNED_NAMES.intersection(rel.split('/')[:-1]) or rel.startswith(pruned) or admits(rel, placement.code_roots):
        return None
    homes = ', '.join(f'{kind} -> {home}' for kind, home in FAMILY_HOMES.items())
    return (
        f'CODE-IN-CODE-ROOTS: {rel} is a code file outside every declared code root '
        f'{list(placement.code_roots)}. Its home: {_home_for(rel)}. The family map: {homes}. A repo '
        f'adds a root only in {_TABLE} code_roots of its {_MANIFEST}, never by writing the file first.'
    )


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The ``PreToolUse`` hook on Write/Edit/MultiEdit: deny a misplaced code file, else stay silent.

    A payload naming no path is allowed: the hook judges a PATH, and such a payload names none.
    """
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    target = tool_input.get('file_path') if isinstance(tool_input, dict) else None
    if not isinstance(target, str) or not target:
        return 0
    path = Path(target)
    if not path.is_absolute():
        path = Path(payload.get('cwd') or Path.cwd()) / path
    reason = refuse_write(path)
    if reason is not None:
        decision = {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}
        emit(json.dumps({'hookSpecificOutput': decision}))
    return 0


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


if __name__ == '__main__':
    sys.exit(main())
