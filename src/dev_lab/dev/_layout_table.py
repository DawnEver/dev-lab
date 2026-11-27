"""The DECLARED half of :mod:`dev_lab.dev.layout`: ``[layout]`` of ``layout.toml`` read, validated and matched.

Split out of :mod:`dev_lab.dev.layout` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: this module turns the
table into rows, refuses a malformed one, and matches a path against the rows (:func:`row_for`, :func:`declares` --
the rows alone, never the disk, so OWNER-DAG asks it of a path not created yet); that module judges a tree against
the rows and scans it.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import hashlib
import json
import re
from pathlib import Path
from typing import Final

from dev_lab.dev import gitdirs
from dev_lab.dev._deny_outputcode_row import CODE_SUFFIXES
from dev_lab.dev.codeplace import (
    FAMILY_HOMES,
    LAYOUT_FILE,
    PlacementNotDeclared,
    declared_placement,
    placement_table,
)
from dev_lab.dev.datedlog import FAMILY_KINDS

__all__ = [
    'ANY',
    'DOC_SITE_ROOT',
    'FAMILY_ROWS',
    'OTHER_CONFIG_SUFFIXES',
    'REQUIRED',
    'RULE_ID',
    'TABLE',
    'TOOL_CACHE_ROOT',
    'VENDOR_JOB_ROOT',
    'AmbiguousRowError',
    'Layout',
    'LayoutNotDeclared',
    'allowed',
    'declared_at',
    'declared_layout',
    'declares',
    'family_kind',
    'row_for',
]

RULE_ID: Final = 'DECLARED-LAYOUT'
#: Where the table lives, as every refusal names it.
TABLE: Final = f'[layout] of {LAYOUT_FILE}'
#: The family homes' top-level directories: every adopter declares each of them.
REQUIRED: Final = frozenset(home.split('/', 1)[0] for home in FAMILY_HOMES.values())
#: An allow entry admitting any file.
ANY: Final = '*'
#: Where a named tool's cache lives: ``output/cache/<tool>/`` (user ruling 2026-11-24).
TOOL_CACHE_ROOT: Final = 'output/cache'
#: Where a named program's job tree lives: ``output/logs/<yy>/<mm>/<dd>/vendor/<program>/`` (D95, 2026-11-25).
VENDOR_JOB_ROOT: Final = 'output/logs/[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/vendor'
#: Where a named builder's documentation site lives: ``output/docs/<site>/`` (FAM-08, 2026-11-26).
DOC_SITE_ROOT: Final = 'output/docs'
#: One tool's or program's name: a plain word, so an entry can never widen into a glob or a path.
_TOOL: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')
#: ONE-FORMAT-PER-NEED: configuration is TOML, so a second configuration format is never declared -- except where a
#: forge dictates its own (its workflow directories) and in ``output/``, which holds what a program writes.
OTHER_CONFIG_SUFFIXES: Final = frozenset({'.yaml', '.yml', '.ini', '.cfg'})
_FORMAT_RULE: Final = 'ONE-FORMAT-PER-NEED'
_FORGE_DIRS: Final = frozenset({'.github', '.gitea', 'output'})
#: The family's dated tree under its ``artifacts`` home, down to the day: ``output/logs/<yy>/<mm>/<dd>``.
_DATED: Final = tuple(FAMILY_HOMES['artifacts'].strip('/').split('/'))
_DAY_GLOB: Final = '[0-9][0-9]'
_DAY: Final = (*_DATED, _DAY_GLOB, _DAY_GLOB, _DAY_GLOB)
#: The dated tree's own levels, declared for a repo that declares nothing under its output home.
_DATED_LEVELS: Final = tuple('/'.join(_DAY[:depth]) for depth in range(len(_DATED), len(_DAY) + 1))
#: THE FAMILY'S ROWS (:data:`dev_lab.dev.datedlog.FAMILY_KINDS` as layout rows): every adopter's, never its own.
FAMILY_ROWS: Final = {
    '/'.join((*_DAY, kind, *([] if shape == '.' else [shape]))): suffixes
    for kind, shapes in FAMILY_KINDS.items()
    for shape, suffixes in shapes.items()
}

#: Directories the family RENDERS into every checkout (dev_lab.dev.vscodesettings): the family's rows, never a repo's.
RENDERED_ROWS: Final = {'.vscode': frozenset({'.json'})}


def family_kind(parts: list[str]) -> str | None:
    """The family kind a directory (or row pattern) *parts* is at or below, else ``None``.

    Inside a family kind only :data:`FAMILY_ROWS` judge: a repo's open row (``<day>/*``) never widens one.
    """
    day = len(_DAY)
    if len(parts) <= day or tuple(parts[: len(_DATED)]) != _DATED or parts[day] not in FAMILY_KINDS:
        return None
    return parts[day]


def _with_family_rows(manifest: Path, rows: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """*rows* with the dated levels (where undeclared) and :data:`FAMILY_ROWS`; a repo row naming a family kind reds."""
    for key in rows:
        if (kind := family_kind(key.split('/'))) is not None:
            shapes = {shape: sorted(suffixes) for shape, suffixes in FAMILY_KINDS[kind].items()}
            raise _refuse(
                manifest,
                f'{key} declares the family kind {kind!r}, which dev-lab declares ONCE for every repo '
                f'(dev_lab.dev.datedlog.FAMILY_KINDS: {shapes}); drop the row -- a repo lists only its own kinds, '
                f'and a family kind that needs another format changes in dev-lab',
            )
    return {**dict.fromkeys(_DATED_LEVELS, frozenset()), **rows, **FAMILY_ROWS, **RENDERED_ROWS}


class LayoutNotDeclared(LookupError):
    """A repo's ``[layout]`` of ``layout.toml`` is absent or not the declared shape."""


@dataclasses.dataclass(frozen=True)
class Layout:
    """A checkout's declared tree: pattern -> what a file there may be, the paths never judged, the read-only ones."""

    rows: dict[str, frozenset[str]]
    pruned_paths: tuple[str, ...] = ()
    read_only: tuple[str, ...] = ()
    tool_caches: tuple[str, ...] = ()
    vendor_jobs: tuple[str, ...] = ()
    doc_sites: tuple[str, ...] = ()
    #: The declared one-off sink (``scratch`` of the placement): its content is never judged by a row (#1034).
    scratch: str = 'scratch'
    #: MIRROR rows: pattern -> (the mirrored root, the explicit extra names below the row, the depth or None).
    mirrors: dict[str, tuple[str, tuple[str, ...], int | None]] = dataclasses.field(default_factory=dict)

    @property
    def digest(self) -> str:
        """The declaration's fingerprint: a changed table invalidates every journalled verdict."""
        rows = sorted((k, sorted(v)) for k, v in self.rows.items())
        mirrors = sorted((k, v[0], list(v[1]), v[2]) for k, v in self.mirrors.items())
        text = json.dumps(
            [
                rows,
                self.pruned_paths,
                self.read_only,
                self.tool_caches,
                mirrors,
                self.vendor_jobs,
                self.doc_sites,
                self.scratch,
            ]
        )
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def judging(self, parts: list[str]) -> dict[str, frozenset[str]]:
        """The rows that may judge the directory *parts*: inside a family kind :data:`FAMILY_ROWS` alone, else all."""
        return FAMILY_ROWS if family_kind(parts) is not None else self.rows

    def in_tool_cache(self, rel: str) -> bool:
        """Whether repo-relative POSIX *rel* is at or below a NAMED tool's cache (``tool_caches``)."""
        return _below(rel, TOOL_CACHE_ROOT, self.tool_caches)

    def in_vendor_job(self, rel: str) -> bool:
        """Whether repo-relative POSIX *rel* is at or below a NAMED program's job tree (``vendor_jobs``)."""
        return _below(rel, VENDOR_JOB_ROOT, self.vendor_jobs)

    def in_doc_site(self, rel: str) -> bool:
        """Whether repo-relative POSIX *rel* is at or below a NAMED doc site (``doc_sites``)."""
        return _below(rel, DOC_SITE_ROOT, self.doc_sites)


def _below(rel: str, root: str, names: tuple[str, ...]) -> bool:
    """Whether *rel* is at or below ``<root>/<name>`` for one of *names*; *root* is a per-segment glob."""
    parts, segs = rel.split('/'), root.split('/')
    return (
        len(parts) > len(segs)
        and parts[len(segs)] in names
        and all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts, segs, strict=False))
    )


def _refuse(manifest: Path, what: str) -> LayoutNotDeclared:
    return LayoutNotDeclared(f'{TABLE} in {manifest}: {what} ({RULE_ID})')


def declared_at(path: Path) -> tuple[Path, Layout, str] | None:
    """``(checkout, its layout, repo-relative POSIX path)`` of *path*; ``None`` outside a checkout declaring one."""
    target = Path(path).resolve()
    root = gitdirs.checkout_of(target.parent)
    if root is None:
        return None
    try:
        return root, declared_layout(root), target.relative_to(root).as_posix()
    except LayoutNotDeclared:
        return None


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
        msg = f'{root} declares no {TABLE}; declare the whole tree there ({RULE_ID})'
        raise LayoutNotDeclared(msg)
    rows, mirrors = _declared_rows(manifest, table)
    rows = _with_family_rows(manifest, rows)
    missing = sorted(REQUIRED - set(rows))
    if missing:
        raise _refuse(manifest, f'the family home(s) {missing} are not declared')
    for key, allows in rows.items():
        if key.split('/', 1)[0] == 'output' and (bad := sorted(allows & {*CODE_SUFFIXES, ANY})):
            raise _refuse(manifest, f'{key} allows {bad}, which output/ never holds')
        if key.split('/', 1)[0] not in _FORGE_DIRS and (bad := sorted(allows & OTHER_CONFIG_SUFFIXES)):
            raise _refuse(
                manifest,
                f'{key} allows {bad}: configuration is TOML ({_FORMAT_RULE}), so a second config format is declared '
                f'only where a forge dictates it (.github/, .gitea/); move that config into pyproject.toml or a .toml',
            )
    pruned = tuple(p.strip('/') for p in placement.get('pruned_paths', []) if isinstance(p, str))
    read_only = tuple(p.strip('/') for p in placement.get('read_only', []) if isinstance(p, str))
    tools = _named(manifest, placement, 'tool_caches', 'tools')
    vendor_jobs = _named(manifest, placement, 'vendor_jobs', 'programs')
    doc_sites = _named(manifest, placement, 'doc_sites', 'sites')
    try:
        sink = declared_placement(root).scratch.strip('/')
    except PlacementNotDeclared as exc:
        msg = f'{exc} ({RULE_ID})'
        raise LayoutNotDeclared(msg) from exc
    return Layout(
        rows, pruned, read_only, tools, vendor_jobs=vendor_jobs, doc_sites=doc_sites, mirrors=mirrors, scratch=sink
    )


def _named(manifest: Path, placement: dict, key: str, what: str) -> tuple[str, ...]:
    """The names under *key* (``tool_caches``, ``vendor_jobs``): each ONE name, never a glob, a path or ``''``."""
    names = placement.get(key, [])
    if not isinstance(names, list) or not all(isinstance(n, str) and _TOOL.fullmatch(n) for n in names):
        raise _refuse(manifest, f'{key} = {names!r} must name {what} one by one (no glob, path or empty name)')
    return tuple(names)


def _declared_rows(
    manifest: Path, table: dict
) -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, tuple[str, ...], int | None]]]:
    """``(pattern -> allowed formats, pattern -> mirror)`` of the ``[layout]`` table."""
    rows: dict[str, frozenset[str]] = {}
    mirrors: dict[str, tuple[str, tuple[str, ...], int | None]] = {}
    for pattern, value in table.items():
        key = pattern.strip('/') or '.'
        allows = value
        if isinstance(value, dict):
            allows, mirrors[key] = _mirror_row(manifest, pattern, value)
        if not isinstance(allows, list) or not all(isinstance(s, str) for s in allows):
            raise _refuse(manifest, f'{pattern} = {allows!r} is not a list of ".suffix", file-name or "*" strings')
        rows[key] = frozenset(s.lower() for s in allows)
    return rows, mirrors


def _mirror_row(manifest: Path, pattern: str, value: dict) -> tuple[object, tuple[str, tuple[str, ...], int | None]]:
    """``(allow, (mirror, extra, depth))`` of a MIRROR row ``{ mirror, allow[, extra][, depth] }``."""
    target, extra, depth = value.get('mirror'), value.get('extra', []), value.get('depth')
    if (
        set(value) - {'mirror', 'allow', 'extra', 'depth'}
        or 'allow' not in value
        or not isinstance(target, str)
        or not target
    ):
        raise _refuse(manifest, f'{pattern} = {value!r} is not a mirror row {{ mirror, allow[, extra][, depth] }}')
    if depth is not None and (type(depth) is not int or depth < 1):
        raise _refuse(manifest, f'{pattern} mirror depth = {depth!r} must be a positive integer (levels twinned)')
    if not isinstance(extra, list) or not all(isinstance(e, str) and e.strip('/') for e in extra):
        raise _refuse(manifest, f'{pattern} mirror extra = {extra!r} must list relative directory names')
    return value['allow'], (target.strip('/'), tuple(e.strip('/') for e in extra), depth)


#: What makes a pattern segment a glob (:func:`fnmatch.fnmatchcase`): each match is one wildcard.
_GLOB: Final = re.compile(r'[*?]|\[[^]]*\]')
#: How many mirror hops a twin lookup follows (a mirror of a mirror is two); a cycle stops here, undeclared.
_MIRROR_HOPS: Final = 8


class AmbiguousRowError(ValueError):
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
    target, extra, depth = layout.mirrors[pattern]
    if depth is not None and len(parts) - len(segs) > depth:
        return False  # below the twinned levels: the ordinary rows judge it
    rel = '/'.join(parts[len(segs) :])
    if rel in extra:
        return True
    if hops >= _MIRROR_HOPS:
        return False
    try:
        return row_for(f'{target}/{rel}', layout, hops + 1) is not None
    except AmbiguousRowError:
        return True  # the twin is declared; its own files are named ambiguous


def row_for(rel_dir: str, layout: Layout, hops: int = 0) -> tuple[str, frozenset[str]] | None:
    """The row of *rel_dir* ITSELF (``.`` is the root) by :func:`_precedence`, with what it allows; no inheritance.

    A directory no row of its own depth matches is declared by a MIRROR row above it whose twin is declared.

    Raises:
        AmbiguousRowError: rows tied on precedence, named.

    """
    if rel_dir == '.':
        return ('.', layout.rows['.']) if '.' in layout.rows else None
    parts = rel_dir.split('/')
    rows = layout.judging(parts)  # inside a family kind, the family's rows alone
    matching = [
        pattern
        for pattern in rows
        if pattern != '.'
        and len(segs := pattern.split('/')) == len(parts)
        and all(fnmatch.fnmatchcase(p, s) for p, s in zip(parts, segs, strict=False))
    ] or [pattern for pattern in layout.mirrors if rows is layout.rows and _mirrored(parts, pattern, layout, hops)]
    if not matching:
        return None
    top = max(map(_precedence, matching))
    best = sorted(p for p in matching if _precedence(p) == top)
    if len(best) > 1:
        msg = (
            f'rows {best} judge {rel_dir} equally (same depth, same wildcard count): ambiguous; declare an explicit '
            f'row for it or make one pattern narrower'
        )
        raise AmbiguousRowError(msg)
    return best[0], rows[best[0]]


def declares(rel: str, layout: Layout) -> bool:
    """Whether *layout* declares the repo-relative path *rel*, never asking the disk (it may not exist yet).

    A directory with a row of its own (or a mirrored twin), or a file -- a last segment with a suffix -- that its
    directory's row allows. Rows tied on precedence still declare the path; the scan names their ambiguity.
    """
    rel = rel.strip('/') or '.'
    rel_dir, _, name = rel.rpartition('/')
    try:
        if row_for(rel, layout) is not None:
            return True
        row = row_for(rel_dir or '.', layout)
    except AmbiguousRowError:
        return True
    return row is not None and bool(Path(name).suffix) and allowed(name, row[1])


def allowed(name: str, allows: frozenset[str]) -> bool:
    """Whether file *name* is one of *allows*: ``*``, its exact (lower-cased) name, or its suffix (``""``: none)."""
    lower = name.lower()
    return ANY in allows or lower in allows or Path(lower).suffix in allows
