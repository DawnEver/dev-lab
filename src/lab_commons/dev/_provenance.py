"""THE PROVENANCE REGISTRY -- what a kit module says about the consumer file it replaced, as DATA.

SPLIT OUT OF :mod:`lab_commons.dev.supersede` because it is a different subject: that module GRADES a
roster against a kit, and this one reads and audits the kit's own declaration. Every name here is
re-exported there, so a consumer imports one module and never learns where the seam falls.

WHY THE DECLARATION IS DATA AND NOT PROSE. :mod:`lab_commons.dev.supersede`'s PROVENANCE detector
reads a docstring, which is a convention: a module that forgets to name its consumer is silent, and a
silent module is indistinguishable from one with nothing to say. MEASURED 2026-09-17 --
:mod:`lab_commons.dev.famtests.rulespages` published ``page_lines``/``ratchet_breaks``/
``assert_rules_ratchet`` over a consumer's whole subject, named no consumer path, and was imported by
nobody, so BOTH detectors went silent and the row graded UNTOUCHED. A registry turns the omission
into a RED: :func:`undeclared_modules` names a published module that has no row.

OVERLAP IS STILL NOT A DETECTOR, and this row is why the question was asked again rather than
answered by promoting it. MEASURED on that same file: the consumer shares exactly ONE of its six
public names with the kit module that supersedes it (``ratchet_breaks``; ``rule_pages`` became
``page_lines``), so a surface-overlap detector would have MISSED this row too while re-admitting the
``_symbol_coverage``/``checkout`` false positive the refusal was protecting against.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # a type-only import: `supersede` imports THIS module, and a cycle is not a type.
    from .supersede import KitModule

__all__ = [
    'ADOPTED_BY',
    'ORIGINAL',
    'PROVENANCE_ROWS',
    'SUPERSEDES',
    'provenance_rows',
    'undeclared_modules',
]

#: Where a kit module states its provenance as DATA, read beside the directory it belongs to, and the
#: name the registry is bound to in it. Prose alone is a convention: MEASURED 2026-09-17,
#: ``famtests.rulespages`` published a superset of a consumer file's whole subject, named no consumer
#: and was imported by nobody -- so BOTH detectors were silent on the very shape this module exists
#: to catch. A row is a MECHANISM because :func:`undeclared_modules` reds on a module that has none.
PROVENANCE_ROWS = '_provenance_rows.py'
_ROWS_NAME = 'PROVENANCE'

#: What a row may say, and only the first of them opens a provenance case. A consumer that DELEGATES
#: has not been replaced, and folding the two together is the false positive already measured here:
#: ``verify``'s prose names ``scripts/gate/runner.py`` as the tree it was carved from, and that file
#: shares 0 of its 51 names. :data:`ORIGINAL` is a module with no consumer fork behind it at all.
SUPERSEDES = 'supersedes'
ADOPTED_BY = 'adopted_by'
ORIGINAL = 'original'
_KINDS = frozenset({SUPERSEDES, ADOPTED_BY, ORIGINAL})


def provenance_rows(directory: Path) -> dict[str, tuple[str, ...]]:
    """Read :data:`PROVENANCE_ROWS` beside *directory* AS SOURCE. An absent registry is no rows.

    Absent is permitted because a kit directory is an argument here and a planted one has no
    registry. What is NOT permitted is a shipped registry that misses a module, and that is
    :func:`undeclared_modules`.
    """
    path = directory / PROVENANCE_ROWS
    if not path.is_file():
        return {}
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if node.value is not None and any(isinstance(t, ast.Name) and t.id == _ROWS_NAME for t in targets):
            return {name: tuple(row) for name, row in ast.literal_eval(node.value).items()}
    return {}


def undeclared_modules(modules: Iterable[KitModule], rows: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    """TWO-SIDED, and this is the half a convention cannot have: what the registry fails to say.

    A published module with no row, a row naming no published module, and a row whose first token is
    not one of :data:`SUPERSEDES` / :data:`ADOPTED_BY` / :data:`ORIGINAL`. Pure over its arguments.
    """
    names = {module.name for module in modules}
    missing = f'published with no provenance row -- name what it supersedes, or declare it {ORIGINAL}'
    out = [f'{name}: {missing}' for name in sorted(names - set(rows))]
    out += [f'{name}: a provenance row naming no published module' for name in sorted(set(rows) - names)]
    out += [
        f'{name}: the row opens with {row[:1]}, which is not one of {sorted(_KINDS)}'
        for name, row in sorted(rows.items())
        if row[:1] not in ((SUPERSEDES,), (ADOPTED_BY,), (ORIGINAL,))
    ]
    return tuple(out)
