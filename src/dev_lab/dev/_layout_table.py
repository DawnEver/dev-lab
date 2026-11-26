"""The DECLARED half of :mod:`dev_lab.dev.layout`: ``[layout]`` of ``layout.toml`` read and validated as rows.

Split out of :mod:`dev_lab.dev.layout` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: this module turns the
table into rows and refuses a malformed one; that module judges a tree against the rows and scans it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev._deny_outputcode_row import CODE_SUFFIXES
from dev_lab.dev.codeplace import FAMILY_HOMES, LAYOUT_FILE, PlacementNotDeclared, placement_table
from dev_lab.dev.datedlog import FAMILY_KINDS

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'ANY',
    'FAMILY_ROWS',
    'OTHER_CONFIG_SUFFIXES',
    'REQUIRED',
    'RULE_ID',
    'TABLE',
    'TOOL_CACHE_ROOT',
    'Layout',
    'LayoutNotDeclared',
    'declared_layout',
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
#: One tool's name: a plain word, so an entry can never widen into a glob or a path.
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


def _family_kind(parts: list[str]) -> str | None:
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
        if (kind := _family_kind(key.split('/'))) is not None:
            shapes = {shape: sorted(suffixes) for shape, suffixes in FAMILY_KINDS[kind].items()}
            raise _refuse(
                manifest,
                f'{key} declares the family kind {kind!r}, which dev-lab declares ONCE for every repo '
                f'(dev_lab.dev.datedlog.FAMILY_KINDS: {shapes}); drop the row -- a repo lists only its own kinds, '
                f'and a family kind that needs another format changes in dev-lab',
            )
    return {**dict.fromkeys(_DATED_LEVELS, frozenset()), **rows, **FAMILY_ROWS}


class LayoutNotDeclared(LookupError):
    """A repo's ``[layout]`` of ``layout.toml`` is absent or not the declared shape."""


@dataclasses.dataclass(frozen=True)
class Layout:
    """A checkout's declared tree: pattern -> what a file there may be, the paths never judged, the read-only ones."""

    rows: dict[str, frozenset[str]]
    pruned_paths: tuple[str, ...] = ()
    read_only: tuple[str, ...] = ()
    tool_caches: tuple[str, ...] = ()
    #: MIRROR rows: pattern -> (the mirrored root, the explicit extra names below the row, the depth or None).
    mirrors: dict[str, tuple[str, tuple[str, ...], int | None]] = dataclasses.field(default_factory=dict)

    @property
    def digest(self) -> str:
        """The declaration's fingerprint: a changed table invalidates every journalled verdict."""
        rows = sorted((k, sorted(v)) for k, v in self.rows.items())
        mirrors = sorted((k, v[0], list(v[1]), v[2]) for k, v in self.mirrors.items())
        text = json.dumps([rows, self.pruned_paths, self.read_only, self.tool_caches, mirrors])
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def judging(self, parts: list[str]) -> dict[str, frozenset[str]]:
        """The rows that may judge the directory *parts*: inside a family kind :data:`FAMILY_ROWS` alone, else all."""
        return FAMILY_ROWS if _family_kind(parts) is not None else self.rows


def _refuse(manifest: Path, what: str) -> LayoutNotDeclared:
    return LayoutNotDeclared(f'{TABLE} in {manifest}: {what} ({RULE_ID})')


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
    tools = placement.get('tool_caches', [])
    if not isinstance(tools, list) or not all(isinstance(t, str) and _TOOL.fullmatch(t) for t in tools):
        raise _refuse(manifest, f'tool_caches = {tools!r} must name tools one by one (no glob, path or empty name)')
    return Layout(rows, pruned, read_only, tuple(tools), mirrors)


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
