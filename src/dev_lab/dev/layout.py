"""DECLARED-LAYOUT and NO-BACKUP-COPIES: a checkout's whole directory tree is an ALLOW-LIST, scanned incrementally.

User rulings 2026-11-23: "There must be no copied checkouts! Strictly lay out the WHOLE directory AND SUBDIRECTORY
architecture and the file formats each directory allows" and "Forbid backing up content into output and scratch!
Everything is either cleaned or merged, no backup."

THE DECLARATION IS THE REPO'S, ONCE, in ``[layout]`` of its root ``layout.toml`` (user ruling 2026-11-24; the
retired ``[tool.dev_lab.placement]`` of ``pyproject.toml`` is refused by name by ``placement_table``):
each key is a directory PATTERN (repo-relative POSIX, one :func:`fnmatch.fnmatchcase` glob per segment, ``.`` for
the root's own files), each value the list of what a file there may be -- a ``.suffix``, an exact file name,
``""`` for a file with no suffix, or ``*`` for anything::

    # layout.toml
    read_only = ['temp']                      # user-maintained input: never written, never cleaned, never judged
    tool_caches = ['pytest', 'ruff']          # output/cache/<tool>/ of each NAMED tool holds what the tool writes
    [layout]
    '.' = ['.toml', '.md', '.lock', '.gitignore']
    src = ['.py', '.typed']
    'src/*' = ['.py']                         # an open level is an explicit glob row
    output = []                               # nothing loose at the top of output/
    'output/logs/[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*' = ['.json', '.csv', '.log']

NO INHERITANCE (user ruling 2026-11-24): EVERY directory matches a row of its own depth, exact or globbed; a
directory no row matches is refused by name (and not descended), and a file is judged only by its own directory's
row. A MIRROR row ``'tests/unit' = { mirror = 'src/pkg', allow = ['.py'], extra = ['verification'] }`` declares
a directory below it iff its twin under the mirrored root is declared (a mirror of a mirror follows the chain;
``extra`` names directories with no twin). Among the rows matching one directory, a row with no glob character
beats a globbed one, then the row with fewer wildcards wins, and rows still tied are refused by name as ambiguous.
Nothing is allowed by default: a new directory or format is refused until it is declared on purpose.

THE FAMILY HOLDS THREE THINGS, NOT THE TREE (a repo's formats are its own): every family home
(:data:`dev_lab.dev.codeplace.FAMILY_HOMES`) must be declared; ``output`` may never allow a
:data:`~dev_lab.dev._deny_outputcode_row.CODE_SUFFIXES` suffix nor ``*``; and under :data:`NO_COPY_ROOTS` a COPY
is refused whatever the table says -- a directory holding ``.git`` (a clone or worktree), a ``pyproject.toml``
beside a ``src/`` (an exported tree), or a :data:`BACKUP_SUFFIXES` file (a bundle or patch parked as a backup).
Its door is MERGE-OR-DELETE: land the work through its branch, or delete it.

TWO EXEMPTIONS, BOTH NAMED (user rulings 2026-11-24). A ``read_only`` path is user input of whatever format the
user keeps: the scan never judges or descends it, and the write hook refuses any write into it. A tool in
``tool_caches`` owns ``output/cache/<tool>/`` (every tool cache lives there, never at the root): the scan and the
hook leave its files unjudged. Each entry is ONE tool's name -- a glob, a path or an empty name is refused, so an
unnamed tool's cache is judged like any undeclared directory.

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
import re
import sys
from pathlib import Path
from typing import Final

from lab_commons.log import emit

from dev_lab.dev import floors, gitdirs
from dev_lab.dev._deny_outputcode_row import CODE_SUFFIXES
from dev_lab.dev.codeplace import FAMILY_HOMES, LAYOUT_FILE, PRUNED_NAMES, PlacementNotDeclared, placement_table
from dev_lab.dev.disclosure import details_for

__all__ = [
    'BACKUP_SUFFIXES',
    'COPY_DOOR',
    'COPY_RULE_ID',
    'NO_COPY_ROOTS',
    'OTHER_CONFIG_SUFFIXES',
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
_TABLE: Final = f'[layout] of {LAYOUT_FILE}'
#: Where nothing is ever a copy or a backup: what a program regenerates, and the one-off sink.
NO_COPY_ROOTS: Final = ('output', 'scratch')
#: A file that is a parked copy of work rather than a product: a git bundle, a patch, a diff.
BACKUP_SUFFIXES: Final = frozenset({'.bundle', '.patch', '.diff'})
#: The family homes' top-level directories: every adopter declares each of them.
REQUIRED: Final = frozenset(home.split('/', 1)[0] for home in FAMILY_HOMES.values())
#: What makes a pattern segment a glob (:func:`fnmatch.fnmatchcase`): each match is one wildcard.
_GLOB: Final = re.compile(r'[*?]|\[[^]]*\]')
_ANY: Final = '*'
#: How many mirror hops a twin lookup follows (a mirror of a mirror is two); a cycle stops here, undeclared.
_MIRROR_HOPS: Final = 8
#: Where a named tool's cache lives: ``output/cache/<tool>/`` (user ruling 2026-11-24).
TOOL_CACHE_ROOT: Final = 'output/cache'
#: One tool's name: a plain word, so an entry can never widen into a glob or a path.
_TOOL: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')
#: ONE-FORMAT-PER-NEED: configuration is TOML, so a second configuration format is never declared -- except where a
#: forge dictates its own (its workflow directories) and in ``output/``, which holds what a program writes.
OTHER_CONFIG_SUFFIXES: Final = frozenset({'.yaml', '.yml', '.ini', '.cfg'})
_FORMAT_RULE: Final = 'ONE-FORMAT-PER-NEED'
_FORGE_DIRS: Final = frozenset({'.github', '.gitea', 'output'})
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
    """A repo's ``[layout]`` of ``layout.toml`` is absent or not the declared shape."""


@dataclasses.dataclass(frozen=True)
class Layout:
    """A checkout's declared tree: pattern -> what a file there may be, the paths never judged, the read-only ones."""

    rows: dict[str, frozenset[str]]
    pruned_paths: tuple[str, ...] = ()
    read_only: tuple[str, ...] = ()
    tool_caches: tuple[str, ...] = ()
    #: MIRROR rows: pattern -> (the mirrored root, the explicit extra names below the row).
    mirrors: dict[str, tuple[str, tuple[str, ...]]] = dataclasses.field(default_factory=dict)

    @property
    def digest(self) -> str:
        """The declaration's fingerprint: a changed table invalidates every journalled verdict."""
        rows = sorted((k, sorted(v)) for k, v in self.rows.items())
        mirrors = sorted((k, v[0], list(v[1])) for k, v in self.mirrors.items())
        text = json.dumps([rows, self.pruned_paths, self.read_only, self.tool_caches, mirrors])
        return hashlib.sha256(text.encode()).hexdigest()[:16]


def _refuse(manifest: Path, what: str) -> LayoutNotDeclared:
    return LayoutNotDeclared(f'{_TABLE} in {manifest}: {what} ({RULE_ID})')


def declared_layout(root: Path) -> Layout:
    """The layout *root* declares.

    Raises:
        LayoutNotDeclared: no readable manifest or table, a row that is not a list of strings, a family home left
            undeclared, ``output`` allowing code or anything, or a second configuration format
            (:data:`OTHER_CONFIG_SUFFIXES`) outside a forge's own directories -- an adopter's test calls this, so it
            reds.

    """
    manifest = root / LAYOUT_FILE
    try:
        placement = placement_table(root) or {}
    except PlacementNotDeclared as exc:
        msg = f'{exc} ({RULE_ID})'
        raise LayoutNotDeclared(msg) from exc
    table = placement.get('layout')
    if not isinstance(table, dict):
        msg = f'{root} declares no {_TABLE}; declare the whole tree there ({RULE_ID})'
        raise LayoutNotDeclared(msg)
    rows, mirrors = _declared_rows(manifest, table)
    missing = sorted(REQUIRED - set(rows))
    if missing:
        raise _refuse(manifest, f'the family home(s) {missing} are not declared')
    for key, allows in rows.items():
        if key.split('/', 1)[0] == 'output' and (bad := sorted(allows & {*CODE_SUFFIXES, _ANY})):
            raise _refuse(manifest, f'{key} allows {bad}, which output/ never holds')
        if key.split('/', 1)[0] not in _FORGE_DIRS and (bad := sorted(allows & OTHER_CONFIG_SUFFIXES)):
            raise _refuse(
                manifest,
                f'{key} allows {bad}: configuration is TOML ({_FORMAT_RULE}), so a second config format is declared '
                f'only where a forge dictates it (.github/, .gitea/); move that config into pyproject.toml or a .toml',
            )
    pruned = tuple(p.strip('/') for p in placement.get('pruned_paths', []) if isinstance(p, str))
    read_only = tuple(p.strip('/') for p in placement.get('read_only', []) if isinstance(p, str))
    tools = placement.get('tool_caches', [])
    if not isinstance(tools, list) or not all(isinstance(t, str) and _TOOL.fullmatch(t) for t in tools):
        raise _refuse(manifest, f'tool_caches = {tools!r} must name tools one by one (no glob, path or empty name)')
    return Layout(rows, pruned, read_only, tuple(tools), mirrors)


def _declared_rows(
    manifest: Path, table: dict
) -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, tuple[str, ...]]]]:
    """``(pattern -> allowed formats, pattern -> mirror)`` of the ``[layout]`` table."""
    rows: dict[str, frozenset[str]] = {}
    mirrors: dict[str, tuple[str, tuple[str, ...]]] = {}
    for pattern, value in table.items():
        key = pattern.strip('/') or '.'
        allows = value
        if isinstance(value, dict):
            allows, mirrors[key] = _mirror_row(manifest, pattern, value)
        if not isinstance(allows, list) or not all(isinstance(s, str) for s in allows):
            raise _refuse(manifest, f'{pattern} = {allows!r} is not a list of ".suffix", file-name or "*" strings')
        rows[key] = frozenset(s.lower() for s in allows)
    return rows, mirrors


def _mirror_row(manifest: Path, pattern: str, value: dict) -> tuple[object, tuple[str, tuple[str, ...]]]:
    """``(allow, (mirror, extra))`` of a MIRROR row ``{ mirror = '<root>', allow = [...], extra = [...] }``."""
    target, extra = value.get('mirror'), value.get('extra', [])
    if set(value) - {'mirror', 'allow', 'extra'} or 'allow' not in value or not isinstance(target, str) or not target:
        raise _refuse(manifest, f'{pattern} = {value!r} is not a mirror row {{ mirror, allow[, extra] }}')
    if not isinstance(extra, list) or not all(isinstance(e, str) and e.strip('/') for e in extra):
        raise _refuse(manifest, f'{pattern} mirror extra = {extra!r} must list relative directory names')
    return value['allow'], (target.strip('/'), tuple(e.strip('/') for e in extra))


def _within(rel: str, prefixes: tuple[str, ...]) -> bool:
    """Whether *rel* is at or below one of *prefixes*, each a per-segment glob (``output/logs/*/*/*/pytest``)."""
    parts = rel.split('/')
    for prefix in prefixes:
        segs = prefix.split('/')
        if len(segs) <= len(parts) and all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts, segs, strict=False)):
            return True
    return False


def _skipped(rel_dir: str, layout: Layout) -> bool:
    """A directory never judged: tool state by name, a pruned path, a read_only input, or a named tool cache."""
    parts = [] if rel_dir == '.' else rel_dir.split('/')
    caches = tuple(f'{TOOL_CACHE_ROOT}/{tool}' for tool in layout.tool_caches)
    return (
        bool(PRUNED_NAMES.intersection(parts))
        or _within(rel_dir, layout.pruned_paths)
        or _within(rel_dir, layout.read_only)
        or _within(rel_dir, caches)
    )


class _AmbiguousRowError(ValueError):
    """Two or more rows judge one directory with equal precedence: the table must say which."""


def _precedence(pattern: str) -> tuple[bool, int]:
    """Among the rows of one depth: an explicit (unglobbed) row wins, then fewer wildcards win."""
    wildcards = len(_GLOB.findall(pattern))
    return (wildcards == 0, -wildcards)


def _mirrored(parts: list[str], pattern: str, layout: Layout, hops: int) -> bool:
    """Whether MIRROR row *pattern* declares the directory *parts*: an extra name, or a declared twin."""
    segs = pattern.split('/')
    if len(segs) >= len(parts) or not all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts, segs, strict=False)):
        return False
    target, extra = layout.mirrors[pattern]
    rel = '/'.join(parts[len(segs) :])
    if rel in extra:
        return True
    if hops >= _MIRROR_HOPS:
        return False
    try:
        return _row_for(f'{target}/{rel}', layout, hops + 1) is not None
    except _AmbiguousRowError:
        return True  # the twin is declared; its own files are named ambiguous


def _row_for(rel_dir: str, layout: Layout, hops: int = 0) -> tuple[str, frozenset[str]] | None:
    """The row of *rel_dir* ITSELF (``.`` is the root) by :func:`_precedence`, with what it allows; no inheritance.

    A directory no row of its own depth matches is declared by a MIRROR row above it whose twin is declared.

    Raises:
        _AmbiguousRowError: rows tied on precedence, named.

    """
    if rel_dir == '.':
        return ('.', layout.rows['.']) if '.' in layout.rows else None
    parts = rel_dir.split('/')
    matching = [
        pattern
        for pattern in layout.rows
        if pattern != '.'
        and len(segs := pattern.split('/')) == len(parts)
        and all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts, segs, strict=False))
    ] or [pattern for pattern in layout.mirrors if _mirrored(parts, pattern, layout, hops)]
    if not matching:
        return None
    top = max(map(_precedence, matching))
    best = sorted(p for p in matching if _precedence(p) == top)
    if len(best) > 1:
        msg = (
            f'rows {best} judge {rel_dir} equally (same depth, same wildcard count): ambiguous; declare an explicit '
            f'row for it or make one pattern narrower'
        )
        raise _AmbiguousRowError(msg)
    return best[0], layout.rows[best[0]]


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
    return _row_verdict(rel_dir, name, layout)


def _row_verdict(rel_dir: str, name: str, layout: Layout) -> str | None:
    """Why the row judging *rel_dir* refuses file *name*: undeclared, ambiguous, or a format it does not allow."""
    try:
        row = _row_for(rel_dir, layout)
    except _AmbiguousRowError as exc:
        return str(exc)
    if row is None:
        return _undeclared(rel_dir)
    pattern, allows = row
    if allowed(name, allows):
        return None
    return (
        f'{Path(name.lower()).suffix or name} is not allowed under {pattern} (allowed: {sorted(allows) or "nothing"})'
    )


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


def _undeclared(rel_dir: str) -> str:
    return (
        f'{rel_dir}/ is not declared: no row of {_TABLE} matches it (no inheritance -- every directory declares '
        f'its own row; an open level is an explicit glob row)'
    )


def _scan_dir(rel_dir: str, folder: Path, layout: Layout) -> tuple[list[str], list[str]]:
    """``(subdirectories to descend, violations)`` of one directory: a copy is named whole and not descended."""
    files, dirs = _listing(folder)
    if (why := copy_marker(rel_dir, set(files), set(dirs))) is not None:
        return [], [f'{rel_dir}/: {COPY_RULE_ID}: {why}. {COPY_DOOR}']
    lines = _dir_verdicts(rel_dir, files, layout)
    if rel_dir != '.' and _SCOPED in dirs:
        lines.append(f'{rel_dir}/{_SCOPED}/: {_SCOPED_CAUSE}')
        dirs = [d for d in dirs if d != _SCOPED]
    for name in dirs:
        child = name if rel_dir == '.' else f'{rel_dir}/{name}'
        if not _skipped(child, layout) and _declared_row(child, layout) is None:
            lines.append(f'{child}/: {_undeclared(child)}')
    return dirs, lines


def _declared_row(rel_dir: str, layout: Layout) -> tuple[str, frozenset[str]] | bool | None:
    """The row of *rel_dir*, ``True`` when its rows tie (its files are each named ambiguous), else ``None``."""
    try:
        return _row_for(rel_dir, layout)
    except _AmbiguousRowError:
        return True


def _descends(child: str, layout: Layout) -> bool:
    """Whether the walk enters *child*: never a pruned one, nor an undeclared one (named whole by its parent)."""
    return not _skipped(child, layout) and _declared_row(child, layout) is not None


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
            f'{RULE_ID}: {rel} -- {rel.split("/", 1)[0]}/ is declared read_only in '
            f'{root.name}/{LAYOUT_FILE}: user-maintained input, read freely, never written or cleaned. A '
            f'derived artifact goes to output/logs/<yy>/<mm>/<dd>/<kind>/.\n{details_for(RULE_ID)}'
        )
    cause = judge(rel, layout)
    if cause is None:
        return None
    if cause.startswith(COPY_RULE_ID):
        return f'{cause}: {rel}. {COPY_DOOR}\n{details_for(COPY_RULE_ID)}'
    homes = ', '.join(f'{kind} -> {home}' for kind, home in FAMILY_HOMES.items())
    return (
        f'{RULE_ID}: {rel} -- {cause}. Write it under its home ({homes}); a new directory or format is declared '
        f'first in {_TABLE} ({root.name}/{LAYOUT_FILE}), in its own reviewed commit.\n{details_for(RULE_ID)}'
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
