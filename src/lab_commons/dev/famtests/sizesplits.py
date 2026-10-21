"""SPLIT-BY-CONCEPT: a module is split along a concept, never into a sibling that only holds its overflow.

A module past the size band (MODULE-SIZE-ALARM) is refactored, and the cheapest refactor that silences
the band is ``rows.py`` -> ``rows.py`` + ``rows_b.py``: two files, one concept, and every reader now
needs to know which half holds the row they want. An audit (2026-10-21) found the rules registry split
exactly so. The name says it: a suffix that is a letter, a number or ``partN``/``more``/``rest``/``cont``
/``extra`` on a stem whose sibling module exists names no concept, only an order.

THE READING IS PATHS ONLY, so it runs on any repo's tracked module list, and the debt is a NAMED SET
with no default (two-sided: a split not in it reds, and a debt entry no longer in the tree reds).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Final

__all__ = ['SizeSplit', 'assert_no_new_size_splits', 'size_splits']

#: A stem ``<base>_<overflow>`` whose suffix orders, rather than names.
_OVERFLOW: Final = re.compile(r'^(?P<base>.+)_(?:[a-z]|\d+|part\d+|more|rest|cont|extra)$')


class SizeSplit(AssertionError):
    """A module is its sibling's overflow, or the debt names a split the tree no longer has."""


def size_splits(modules: Iterable[str]) -> tuple[str, ...]:
    """Every POSIX module path in *modules* that is a size split of a sibling module in the same directory."""
    listed = {PurePosixPath(path) for path in modules}
    found = []
    for path in listed:
        matched = _OVERFLOW.match(path.stem)
        if matched and path.with_name(f'{matched["base"]}{path.suffix}') in listed:
            found.append(path.as_posix())
    return tuple(sorted(found))


def assert_no_new_size_splits(modules: Iterable[str], *, debt: frozenset[str]) -> None:
    """Refuse a size split outside *debt*, and a *debt* entry the tree no longer has.

    Raises:
        SizeSplit: naming each new split and each stale debt entry.

    """
    found = set(size_splits(modules))
    problems = [
        f'{path} is the size overflow of a sibling module; split along a concept and name it' for path in found - debt
    ]
    problems += [f'{path} is in the debt and no longer a size split: remove it from the debt' for path in debt - found]
    if problems:
        raise SizeSplit('\n  '.join(['SPLIT-BY-CONCEPT:', *sorted(problems)]))
