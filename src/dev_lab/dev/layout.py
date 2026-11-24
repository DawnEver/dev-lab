"""DECLARED-LAYOUT and NO-BACKUP-COPIES: a checkout's whole directory tree is an ALLOW-LIST, scanned incrementally.

User rulings 2026-11-23: "There must be no copied checkouts! Strictly lay out the WHOLE directory AND SUBDIRECTORY
architecture and the file formats each directory allows" and "Forbid backing up content into output and scratch!
Everything is either cleaned or merged, no backup."

THE DECLARATION IS THE REPO'S, ONCE, in ``[tool.dev_lab.placement.layout]`` of its ``pyproject.toml``: each key
is a directory PATTERN (repo-relative POSIX, one :func:`fnmatch.fnmatchcase` glob per segment, ``.`` for the
root's own files), each value the list of what a file there may be -- a ``.suffix``, an exact file name, ``""``
for a file with no suffix, or ``*`` for anything::

    [tool.dev_lab.placement]
    read_only = ['temp']                      # user-maintained input: never written, never cleaned
    [tool.dev_lab.placement.layout]
    '.' = ['.toml', '.md', '.lock', '.gitignore']
    src = ['.py', '.typed']
    output = []                               # nothing loose at the top of output/
    'output/logs/[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*' = ['.json', '.csv', '.log']

A file is judged by the DEEPEST pattern matching a prefix of its directory; a file no pattern reaches is
undeclared. So every subdirectory inherits its nearest declared ancestor, and a subtree that matters declares its
own row. Nothing is allowed by default: a new directory or format is refused until it is declared on purpose.

THE FAMILY HOLDS THREE THINGS, NOT THE TREE (a repo's formats are its own): every family home
(:data:`dev_lab.dev.codeplace.FAMILY_HOMES`) must be declared; ``output`` may never allow a
:data:`~dev_lab.dev._deny_outputcode_row.CODE_SUFFIXES` suffix nor ``*``; and under :data:`NO_COPY_ROOTS` a COPY
is refused whatever the table says -- a directory holding ``.git`` (a clone or worktree), a ``pyproject.toml``
beside a ``src/`` (an exported tree), or a :data:`BACKUP_SUFFIXES` file (a bundle or patch parked as a backup).
Its door is MERGE-OR-DELETE: land the work through its branch, or delete it.

ONE TABLE, ONE PREDICATE, THREE CALLERS: the scan :func:`layout_violations`, the write hook's
:func:`refuse_layout`, and the scan entry :func:`main` that ``verify`` and every forge tick run.

THE SCAN IS INCREMENTAL, so it is cheap enough for every ``verify``, every measure and every forge tick: a
directory whose mtime is unchanged since the last scan (its entries are the same -- a create, delete or rename in
it moves its mtime) reuses its recorded entries and verdict without being listed. The journal lives in the
checkout's own git dir (``<git-dir>/dev-lab/layout-scan.json``), keyed by the declaration, so a changed table
rescans everything. A copy is reported once and never descended into.

THE CLI: ``python -m dev_lab.dev.layout [--root DIR] [--full] [--floor N]`` prints every violation; exit 1 when
any, 2 when the checkout declares no layout.
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Final

from lab_commons.log import emit

from dev_lab.dev import floors, gitdirs
from dev_lab.dev._deny_outputcode_row import CODE_SUFFIXES
from dev_lab.dev.codeplace import FAMILY_HOMES, PRUNED_NAMES
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.family import declared_table

__all__ = [
    'BACKUP_SUFFIXES',
    'COPY_DOOR',
    'COPY_RULE_ID',
    'NO_COPY_ROOTS',
    'REQUIRED',
    'RULE_ID',
    'Layout',
    'LayoutNotDeclared',
    'allowed',
    'copy_marker',
    'declared_layout',
    'judge',
    'layout_violations',
    'main',
    'refuse_layout',
    'scan_refusal',
]

RULE_ID: Final = 'DECLARED-LAYOUT'
COPY_RULE_ID: Final = 'NO-BACKUP-COPIES'
_TABLE: Final = '[tool.dev_lab.placement.layout]'
#: Where nothing is ever a copy or a backup: what a program regenerates, and the one-off sink.
NO_COPY_ROOTS: Final = ('output', 'scratch')
#: A file that is a parked copy of work rather than a product: a git bundle, a patch, a diff.
BACKUP_SUFFIXES: Final = frozenset({'.bundle', '.patch', '.diff'})
#: The family homes' top-level directories: every adopter declares each of them.
REQUIRED: Final = frozenset(home.split('/', 1)[0] for home in FAMILY_HOMES.values())
_ANY: Final = '*'
#: Agent state lives once, at the checkout root (user ruling 2026-11-23): a scoped ``.claude/`` below it is refused.
_SCOPED: Final = '.claude'
_SCOPED_CAUSE: Final = (
    'a .claude/ below the repo root: memory and rules live once in the root .claude/ (memory under '
    '.claude/memory/<yyyy>/<mm>/<dd>/); migrate it there once (FORMATS-MIGRATE-ONCE) and delete it'
)
#: How many violations a run entry's refusal lists before it counts the rest.
_SHOWN: Final = 20
_JOURNAL: Final = ('dev-lab', 'layout-scan.json')
COPY_DOOR: Final = (
    'The door is MERGE-OR-DELETE: commit the work on its branch and land it through a PR, or delete it; a second '
    'tree of this repo is <repo>/.claude/worktrees/<name>, never a copy or backup under output/ or scratch/.'
)


class LayoutNotDeclared(LookupError):
    """A repo's ``[tool.dev_lab.placement.layout]`` is absent or not the declared shape."""


@dataclasses.dataclass(frozen=True)
class Layout:
    """A checkout's declared tree: pattern -> what a file there may be, the paths never judged, the read-only ones."""

    rows: dict[str, frozenset[str]]
    pruned_paths: tuple[str, ...] = ()
    read_only: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        """The declaration's fingerprint: a changed table invalidates every journalled verdict."""
        rows = sorted((k, sorted(v)) for k, v in self.rows.items())
        text = json.dumps([rows, self.pruned_paths, self.read_only])
        return hashlib.sha256(text.encode()).hexdigest()[:16]


def _refuse(manifest: Path, what: str) -> LayoutNotDeclared:
    return LayoutNotDeclared(f'{_TABLE} in {manifest}: {what} ({RULE_ID})')


def declared_layout(root: Path) -> Layout:
    """The layout *root* declares.

    Raises:
        LayoutNotDeclared: no readable manifest or table, a row that is not a list of strings, a family home left
            undeclared, or ``output`` allowing code or anything -- an adopter's test calls this, so it reds.

    """
    manifest = root / 'pyproject.toml'
    try:
        data = tomllib.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f'{manifest} is not a readable TOML manifest: {exc}'
        raise LayoutNotDeclared(msg) from exc
    placement = declared_table(data, 'placement')
    table = placement.get('layout') if isinstance(placement, dict) else None
    if not isinstance(table, dict):
        msg = f'{manifest} declares no {_TABLE}; declare the whole tree there ({RULE_ID})'
        raise LayoutNotDeclared(msg)
    rows: dict[str, frozenset[str]] = {}
    for pattern, allows in table.items():
        if not isinstance(allows, list) or not all(isinstance(s, str) for s in allows):
            raise _refuse(manifest, f'{pattern} = {allows!r} is not a list of ".suffix", file-name or "*" strings')
        rows[pattern.strip('/') or '.'] = frozenset(s.lower() for s in allows)
    missing = sorted(REQUIRED - set(rows))
    if missing:
        raise _refuse(manifest, f'the family home(s) {missing} are not declared')
    for key, allows in rows.items():
        if key.split('/', 1)[0] == 'output' and (bad := sorted(allows & {*CODE_SUFFIXES, _ANY})):
            raise _refuse(manifest, f'{key} allows {bad}, which output/ never holds')
    pruned = tuple(p.strip('/') for p in placement.get('pruned_paths', []) if isinstance(p, str))
    read_only = tuple(p.strip('/') for p in placement.get('read_only', []) if isinstance(p, str))
    return Layout(rows, pruned, read_only)


def _within(rel: str, prefixes: tuple[str, ...]) -> bool:
    """Whether *rel* is at or below one of *prefixes*, each a per-segment glob (``output/logs/*/*/*/pytest``)."""
    parts = rel.split('/')
    for prefix in prefixes:
        segs = prefix.split('/')
        if len(segs) <= len(parts) and all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts, segs, strict=False)):
            return True
    return False


def _skipped(rel_dir: str, layout: Layout) -> bool:
    """A directory never judged: tool state by name, or a declared pruned path (another checkout's worktrees)."""
    parts = [] if rel_dir == '.' else rel_dir.split('/')
    return bool(PRUNED_NAMES.intersection(parts)) or _within(rel_dir, layout.pruned_paths)


def _row_for(rel_dir: str, layout: Layout) -> tuple[str, frozenset[str]] | None:
    """The deepest declared pattern matching a prefix of *rel_dir* (``.`` is the root), with what it allows."""
    if rel_dir == '.':
        return ('.', layout.rows['.']) if '.' in layout.rows else None
    parts = rel_dir.split('/')
    best: tuple[int, str] | None = None
    for pattern in layout.rows:
        segs = pattern.split('/')
        if pattern == '.' or len(segs) > len(parts):
            continue
        if all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts, segs, strict=False)):
            best = max(best or (0, ''), (len(segs), pattern))
    return None if best is None else (best[1], layout.rows[best[1]])


def allowed(name: str, allows: frozenset[str]) -> bool:
    """Whether file *name* is one of *allows*: ``*``, its exact (lower-cased) name, or its suffix (``""``: none)."""
    lower = name.lower()
    return _ANY in allows or lower in allows or Path(lower).suffix in allows


def copy_marker(rel_dir: str, files: set[str], dirs: set[str]) -> str | None:
    """Why the directory *rel_dir* (holding *files* and *dirs*) is a copied checkout under a no-copy root, or None."""
    if rel_dir.split('/', 1)[0] not in NO_COPY_ROOTS:
        return None
    if '.git' in files or '.git' in dirs:
        return 'holds .git: a cloned or worktree checkout'
    if 'pyproject.toml' in files and 'src' in dirs:
        return 'holds pyproject.toml beside src/: an exported copy of a tree'
    return None


def judge(rel: str, layout: Layout) -> str | None:
    """THE ONE PREDICATE for a FILE: the cause *rel* (repo-relative POSIX) breaks the layout, or ``None``."""
    rel_dir, _, name = rel.rpartition('/')
    rel_dir = rel_dir or '.'
    if _skipped(rel_dir, layout):
        return None
    suffix = Path(name.lower()).suffix
    top = rel_dir.split('/', 1)[0]
    if _SCOPED in rel_dir.split('/')[1:]:
        return f'{_SCOPED_CAUSE} ({rel_dir.split(f"/{_SCOPED}", 1)[0]}/{_SCOPED}/)'
    if top in NO_COPY_ROOTS and suffix in BACKUP_SUFFIXES:
        return f'{COPY_RULE_ID}: a {suffix} under {top}/ is a parked backup'
    row = _row_for(rel_dir, layout)
    if row is None:
        return f'{rel_dir}/ is not declared (no row of {_TABLE} reaches it)'
    pattern, allows = row
    if not allowed(name, allows):
        return f'{suffix or name} is not allowed under {pattern} (allowed: {sorted(allows) or "nothing"})'
    return None


def _dir_verdicts(rel_dir: str, files: list[str], layout: Layout) -> list[str]:
    """Every violation among the files of the directory *rel_dir*, one line per cause (files grouped)."""
    by_cause: dict[str, list[str]] = {}
    for name in files:
        if name in PRUNED_NAMES:
            continue  # a linked worktree's `.git` file is tool state, never a declared format
        if (cause := judge(name if rel_dir == '.' else f'{rel_dir}/{name}', layout)) is not None:
            by_cause.setdefault(cause, []).append(name)
    lines = []
    for cause, names in sorted(by_cause.items()):
        where = f'{rel_dir}/{names[0]}' if len(names) == 1 else f'{rel_dir}/ ({len(names)} files, e.g. {names[0]})'
        lines.append(f'{where.removeprefix("./")}: {cause}')
    return lines


def _journal_path(root: Path) -> Path | None:
    own = gitdirs.git_dir(root)
    return None if own is None else own.joinpath(*_JOURNAL)


def _read_journal(path: Path | None, digest: str) -> dict[str, list]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data.get('dirs', {}) if isinstance(data, dict) and data.get('digest') == digest else {}


def _write_journal(path: Path | None, digest: str, dirs: dict[str, list]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'digest': digest, 'dirs': dirs}), encoding='utf-8')
        tmp.replace(path)
    except OSError:
        return  # a journal is a cache: an unwritable one costs the next scan a full walk, never a verdict


def _listing(folder: Path) -> tuple[list[str], list[str]]:
    files, dirs = [], []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                (dirs if entry.is_dir(follow_symlinks=False) else files).append(entry.name)
    except OSError:
        pass
    return sorted(files), sorted(dirs)


def _scan_dir(rel_dir: str, folder: Path, layout: Layout) -> tuple[list[str], list[str]]:
    """``(subdirectories to descend, violations)`` of one directory: a copy is named whole and not descended."""
    files, dirs = _listing(folder)
    if (why := copy_marker(rel_dir, set(files), set(dirs))) is not None:
        return [], [f'{rel_dir}/: {COPY_RULE_ID}: {why}. {COPY_DOOR}']
    lines = _dir_verdicts(rel_dir, files, layout)
    if rel_dir != '.' and _SCOPED in dirs:
        lines.append(f'{rel_dir}/{_SCOPED}/: {_SCOPED_CAUSE}')
        dirs = [d for d in dirs if d != _SCOPED]
    return dirs, lines


def _descends(child: str, layout: Layout) -> bool:
    """Whether the walk enters *child*: never a pruned one, nor a ``*`` row outside the no-copy roots."""
    if _skipped(child, layout):
        return False
    row = _row_for(child, layout)
    return row is None or _ANY not in row[1] or child.split('/', 1)[0] in NO_COPY_ROOTS


def layout_violations(root: Path, layout: Layout | None = None, *, incremental: bool = False) -> tuple[int, list[str]]:
    """``(top-level directories read, every violation as '<where>: <cause>')`` over *root*'s FILESYSTEM.

    The walk is of the filesystem, never the index: the defect is precisely an untracked or ignored tree.
    *incremental* reuses the journal for every directory whose mtime is unchanged since the last scan.
    """
    layout = declared_layout(root) if layout is None else layout
    journal = _journal_path(root) if incremental else None
    before = _read_journal(journal, layout.digest)
    after: dict[str, list] = {}
    found: list[str] = []
    tops = 0
    stack = ['.']
    while stack:
        rel_dir = stack.pop()
        folder = root if rel_dir == '.' else root / rel_dir
        try:
            mtime = folder.stat().st_mtime_ns
        except OSError:
            continue
        cached = before.get(rel_dir)
        if cached is not None and cached[0] == mtime:
            subdirs, lines = cached[1], cached[2]
        else:
            subdirs, lines = _scan_dir(rel_dir, folder, layout)
        after[rel_dir] = [mtime, subdirs, lines]
        found += lines
        tops = len(subdirs) if rel_dir == '.' else tops
        stack += [c for name in subdirs if _descends(c := name if rel_dir == '.' else f'{rel_dir}/{name}', layout)]
    if incremental:
        _write_journal(journal, layout.digest, after)
    return tops, sorted(found)


def refuse_layout(path: Path) -> str | None:
    """The write hook's refusal for *path*; ``None`` when admitted or the checkout declares no layout."""
    target = Path(path).resolve()
    root = gitdirs.checkout_of(target.parent)
    if root is None:
        return None
    try:
        layout = declared_layout(root)
    except LayoutNotDeclared:
        return None
    rel = target.relative_to(root).as_posix()
    if _within(rel, layout.read_only):
        return (
            f'{RULE_ID}: {rel} -- {rel.split("/", 1)[0]}/ is declared read_only in [tool.dev_lab.placement] of '
            f'{root.name}/pyproject.toml: user-maintained input, read freely, never written or cleaned. A '
            f'derived artefact goes to output/logs/<yy>/<mm>/<dd>/<kind>/.\n{details_for(RULE_ID)}'
        )
    cause = judge(rel, layout)
    if cause is None:
        return None
    if cause.startswith(COPY_RULE_ID):
        return f'{cause}: {rel}. {COPY_DOOR}\n{details_for(COPY_RULE_ID)}'
    homes = ', '.join(f'{kind} -> {home}' for kind, home in FAMILY_HOMES.items())
    return (
        f'{RULE_ID}: {rel} -- {cause}. Write it under its home ({homes}); a new directory or format is declared '
        f'first in {_TABLE} of {root.name}/pyproject.toml, in its own reviewed commit.\n{details_for(RULE_ID)}'
    )


def scan_refusal(root: Path) -> str | None:
    """The incremental scan as a one-paragraph refusal for a run entry (``verify``, a tick); ``None`` when clean.

    A checkout declaring no layout has not adopted the rule and is not judged here (its famtest reds instead).
    """
    try:
        _, found = layout_violations(root, incremental=True)
    except LayoutNotDeclared:
        return None
    if not found:
        return None
    shown = '\n'.join(f'  {line}' for line in found[:_SHOWN])
    more = f'\n  ... and {len(found) - _SHOWN} more' if len(found) > _SHOWN else ''
    return (
        f'{RULE_ID}/{COPY_RULE_ID}: {len(found)} violation(s) in {root.as_posix()}:\n{shown}{more}\nMove each '
        f'file home or delete it; a copy or backup is merged or deleted ({COPY_DOOR}); a new directory or format '
        f'is declared in {_TABLE} first.\n{details_for(RULE_ID)}'
    )


def main(argv: list[str] | None = None) -> int:
    """``python -m dev_lab.dev.layout [--root DIR] [--full] [--floor N]``: 0 clean, 1 violations, 2 undeclared."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.layout', description='DECLARED-LAYOUT scan')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--full', action='store_true', help='ignore the journal and list every directory')
    parser.add_argument('--floor', type=int, default=1, help='fewest top-level directories the walk must read')
    args = parser.parse_args(argv)
    root = gitdirs.checkout_of(args.root.resolve()) or args.root.resolve()
    try:
        read, found = layout_violations(root, incremental=not args.full)
        floors.assert_floor(read, floor=args.floor, what=f'{RULE_ID} top-level directory')
    except LayoutNotDeclared as exc:
        emit(f'layout: {exc}', err=True)
        return 2
    except floors.FloorUnmet as exc:
        emit(f'layout: {exc}', err=True)
        return 1
    for line in found:
        emit(line)
    emit(f'layout: {root.as_posix()}: {read} top-level directories read, {len(found)} violation(s)', err=bool(found))
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
