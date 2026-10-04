"""NO-REFLECTION: no tracked Python calls ``getattr``/``hasattr``/``setattr``/``delattr`` or defines ``__getattr__``.

User ruling 2026-10-04, family-wide, superseding the 2026-09-26 getattr-only directive: reflection
is banned outright. A declared field is read by attribute access, a capability by ``isinstance``
against a Protocol, a dataclass surface by ``dataclasses.fields``/``replace``, a name-keyed choice
by an explicit dict, and an absent attribute by ``pytest.raises(AttributeError)``. Moving the call
behind ``vars()`` or ``__dict__`` is the same probe renamed, and is not a fix.

THE CORPUS IS EVERY TRACKED ``*.py`` -- source, tests, scripts, examples -- except a path with an
``attic`` or ``archived`` segment, which is read-only history. Each consumer had its own copy of this
scan over its own subset of trees, and each copy banned a different subset of the four names.

THE ONE REPO-SHAPED FACT IS THE ALLOW-SET, keyed by repo-relative POSIX path with the REASON as the
value, and it has no default. It is TWO-SIDED: a path that no longer reflects is named too, so a
cleaned file must leave the set in the same edit. An irreducible boundary (a native extension's
optional symbol) belongs there; convenience does not.
"""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lab_commons.dev import floors
from lab_commons.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['BANNED_CALLS', 'EXCLUDED_SEGMENTS', 'assert_no_reflection', 'reflection_sites', 'scanned_files']

BANNED_CALLS = frozenset({'getattr', 'hasattr', 'setattr', 'delattr'})
EXCLUDED_SEGMENTS = frozenset({'attic', 'archived'})


def reflection_sites(source: str, filename: str) -> list[int]:
    """Line numbers of every banned call and every ``__getattr__`` definition in *source*."""
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source, filename=filename))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS)
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == '__getattr__')
    )


def scanned_files(root: Path) -> tuple[str, ...]:
    """Every tracked ``*.py`` under *root* outside an excluded segment, sorted."""
    return tuple(
        sorted(
            rel
            for rel in tracked_files(root)
            if rel.endswith('.py') and not EXCLUDED_SEGMENTS.intersection(PurePosixPath(rel).parts)
        )
    )


def assert_no_reflection(*, root: Path, allowed: Mapping[str, str], floor: int) -> None:
    """Refuse every reflection site outside *allowed*, every stale or unreasoned entry, and an unread tree."""
    files = [rel for rel in scanned_files(root) if (root / rel).is_file()]
    floors.assert_floor(len(files), floor=floor, what='reflection')
    found = {rel: lines for rel in files if (lines := reflection_sites((root / rel).read_text(encoding='utf-8'), rel))}
    new = [f'{rel}:{line}' for rel, lines in found.items() if rel not in allowed for line in lines]
    stale = sorted(set(allowed) - set(found))
    unreasoned = sorted(rel for rel, why in allowed.items() if not why.strip())
    if new or stale or unreasoned:
        msg = (
            f'NO-REFLECTION: getattr/hasattr/setattr/delattr/__getattr__ are banned. '
            f'Replace each with typed access (attribute, isinstance on a Protocol, dataclasses, a dict, '
            f'pytest.raises(AttributeError)) -- never vars()/__dict__. new={new} '
            f'stale allow entries (delete them)={stale} allow entries without a reason={unreasoned}'
        )
        raise AssertionError(msg)
