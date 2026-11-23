"""DECLARED-LAYOUT: every top-level directory of a checkout is declared, with the suffixes forbidden beneath it.

User requirement 2026-11-23: each repo's folders are declared, and a declared folder may forbid file suffixes --
``output/`` never holds source. CODE-IN-CODE-ROOTS (:mod:`dev_lab.dev.codeplace`) is the allow-list for CODE;
this is the allow-list for DIRECTORIES, so a new top-level directory (a ``tmp/``, a vendor's dump, a copy of a
sibling) is refused until it is declared on purpose, and a declared one cannot quietly change kind.

THE DECLARATION IS THE REPO'S, beside its placement, in ``pyproject.toml``::

    [tool.dev_lab.placement.layout]
    src = []                       # declared, nothing forbidden beyond the family's
    rust = []
    output = ['.md']               # adds to the family's forbidden set for output/

The family's homes (:data:`dev_lab.dev.codeplace.FAMILY_HOMES`) are always declared, and ``output/`` always
forbids OUTPUT-HOLDS-NO-CODE's suffixes (:data:`dev_lab.dev._deny_outputcode_row.CODE_SUFFIXES`, one list).
A repo with no ``layout`` table has not adopted the rule: the hook leaves it alone and the famtest
(:func:`dev_lab.dev.famtests.layout.assert_layout_holds`) reds until it declares one.

ONE TABLE, ONE PREDICATE, TWO CALLERS, as in :mod:`dev_lab.dev.codeplace`: the scan :func:`layout_violations`
and the write hook's :func:`refuse_layout` both decide through :func:`judge`. Tool state and environments
(:data:`dev_lab.dev.codeplace.PRUNED_NAMES`) and the repo's ``pruned_paths`` are never judged.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
from pathlib import Path
from typing import Final

from dev_lab.dev import gitdirs
from dev_lab.dev._deny_outputcode_row import CODE_SUFFIXES as OUTPUT_FORBIDDEN
from dev_lab.dev.codeplace import FAMILY_HOMES, PRUNED_NAMES
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.family import declared_table

__all__ = [
    'FAMILY_LAYOUT',
    'RULE_ID',
    'Layout',
    'LayoutNotDeclared',
    'declared_layout',
    'judge',
    'layout_violations',
    'refuse_layout',
]

RULE_ID: Final = 'DECLARED-LAYOUT'
_TABLE: Final = '[tool.dev_lab.placement.layout]'

#: The family's top-level directories and what each forbids beneath it: every family home, and output/'s code.
FAMILY_LAYOUT: Final[dict[str, frozenset[str]]] = {
    home.split('/', 1)[0]: frozenset(OUTPUT_FORBIDDEN if home.startswith('output/') else ())
    for home in FAMILY_HOMES.values()
}


class LayoutNotDeclared(LookupError):
    """A repo's ``[tool.dev_lab.placement.layout]`` is absent or not the declared shape."""


@dataclasses.dataclass(frozen=True)
class Layout:
    """A checkout's declared top-level directories, each with its forbidden suffixes, and the paths never judged."""

    dirs: dict[str, frozenset[str]]
    pruned_paths: tuple[str, ...] = ()


def declared_layout(root: Path) -> Layout:
    """The layout *root* declares: :data:`FAMILY_LAYOUT` merged with its ``layout`` table.

    Raises:
        LayoutNotDeclared: no readable manifest, no placement, no layout table, or a row that is not a list of
            ``.suffix`` strings -- an adopter's test calls this, so an undeclared repo reds instead of passing.

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
        msg = f'{manifest} declares no {_TABLE}; declare every top-level directory there ({RULE_ID})'
        raise LayoutNotDeclared(msg)
    dirs = dict(FAMILY_LAYOUT)
    for name, forbidden in table.items():
        ok = isinstance(forbidden, list) and all(isinstance(s, str) and s.startswith('.') for s in forbidden)
        if not ok or '/' in name:
            msg = f'{_TABLE} {name} = {forbidden!r} in {manifest}: a top-level name and a list of ".suffix" strings'
            raise LayoutNotDeclared(msg)
        dirs[name] = dirs.get(name, frozenset()) | {s.lower() for s in forbidden}
    pruned = placement.get('pruned_paths', [])
    return Layout(dirs, tuple(p.strip('/') for p in pruned if isinstance(p, str)))


def _skipped(rel: str, layout: Layout) -> bool:
    parts = rel.split('/')
    return bool(PRUNED_NAMES.intersection(parts[:-1] or parts)) or any(
        rel == p or rel.startswith(f'{p}/') for p in layout.pruned_paths
    )


def judge(rel: str, layout: Layout, *, is_dir: bool = False) -> str | None:
    """THE ONE PREDICATE: the cause *rel* (repo-relative POSIX) breaks the layout, or ``None``.

    A loose file at the top level is not this rule's: STRAY-FILE-REFUSED judges it.
    """
    parts = rel.split('/')
    if _skipped(rel, layout) or (len(parts) == 1 and not is_dir):
        return None
    top = parts[0]
    if top not in layout.dirs:
        return f'{top}/ is not a declared top-level directory (declared: {sorted(layout.dirs)})'
    suffix = Path(rel).suffix.lower()
    if not is_dir and suffix in layout.dirs[top]:
        return f'{suffix} is forbidden under {top}/'
    return None


def layout_violations(root: Path, layout: Layout | None = None) -> tuple[int, list[str]]:
    """``(top-level directories read, every violation as '<rel>: <cause>')`` over *root*'s filesystem.

    The walk is of the FILESYSTEM, not the index, because the defect is precisely an untracked directory or file.
    Only declared directories that forbid something are descended into.
    """
    layout = declared_layout(root) if layout is None else layout
    tops = sorted(p.name for p in root.iterdir() if p.is_dir())
    found = [f'{top}/: {cause}' for top in tops if (cause := judge(top, layout, is_dir=True))]
    for top in tops:
        if top not in layout.dirs or not layout.dirs[top] or _skipped(top, layout):
            continue
        for current, subdirs, files in os.walk(root / top):
            rel_dir = Path(current).relative_to(root).as_posix()
            subdirs[:] = [d for d in subdirs if not _skipped(f'{rel_dir}/{d}/x', layout)]
            found += [f'{rel}: {cause}' for name in files if (cause := judge(rel := f'{rel_dir}/{name}', layout))]
    return len(tops), sorted(found)


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
    cause = judge(rel, layout)
    if cause is None:
        return None
    homes = ', '.join(f'{kind} -> {home}' for kind, home in FAMILY_HOMES.items())
    return (
        f'{RULE_ID}: {rel} -- {cause}. Write it under its home ({homes}); a new directory or suffix rule is '
        f'declared first in {_TABLE} of {root.name}/pyproject.toml, in its own reviewed commit.\n{details_for(RULE_ID)}'
    )
