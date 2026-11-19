"""NO-REFLECTION: one origin-aware scanner for attribute and namespace reflection.

User ruling 2026-10-04, family-wide, superseding the 2026-09-26 getattr-only directive: reflection
is banned outright. A declared field is read by attribute access, a capability by ``isinstance``
against a Protocol, a dataclass surface by ``dataclasses.fields``/``replace``, a name-keyed choice
by an explicit dict, and an absent attribute by ``pytest.raises(AttributeError)``. Moving the call
behind ``vars()`` or ``__dict__`` is the same probe renamed, and is not a fix.

THE CORPUS IS EVERY TRACKED ``*.py`` -- source, tests, scripts, examples -- except archived code
(:func:`dev_lab.dev.codeplace.is_archived`: an ``attic``/``archived`` segment or a memory day's
``attachments/``), which is read-only history. Each consumer had its own copy of this
scan over its own subset of trees, and each copy banned a different subset of the four names.

THE ONE REPO-SHAPED FACT IS THE ALLOW-SET, keyed by repo-relative POSIX path with the REASON as the
value, and it has no default. It is TWO-SIDED: a path that no longer reflects is named too, so a
cleaned file must leave the set in the same edit. An irreducible boundary (a native extension's
optional symbol) belongs there; convenience does not.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from dev_lab.dev import floors
from dev_lab.dev.callorigins import call_origins
from dev_lab.dev.codeplace import ARCHIVED_SEGMENTS, is_archived
from dev_lab.dev.failprint import subject_lines
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['BANNED_CALLS', 'EXCLUDED_SEGMENTS', 'assert_no_reflection', 'reflection_sites', 'scanned_files']

BANNED_CALLS = frozenset({'getattr', 'hasattr', 'setattr', 'delattr', 'vars', 'dir'})
EXCLUDED_SEGMENTS = ARCHIVED_SEGMENTS
_HOOKS = frozenset({'__getattr__', '__getattribute__', '__setattr__', '__delattr__'})
_ORIGINS = frozenset(
    {
        *(f'builtins.{name}' for name in BANNED_CALLS),
        'operator.attrgetter',
        'inspect.getmembers',
        'inspect.getmembers_static',
        *(f'builtins.object.{name}' for name in _HOOKS),
    }
)


def _hook_lines(tree: ast.AST) -> set[int]:
    """Namespace access and hook declarations do not depend on callable origins."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == '__dict__':
            found.add(node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in _HOOKS:
            found.add(node.lineno)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                pending = [target]
                while pending:
                    part = pending.pop()
                    if isinstance(part, ast.Name) and part.id in _HOOKS:
                        found.add(part.lineno)
                    elif isinstance(part, (ast.Tuple, ast.List)):
                        pending.extend(part.elts)
    return found


def reflection_sites(source: str, filename: str) -> list[int]:
    """Unique lines of reflection calls, namespace accesses and hooks in *source*.

    Imports and simple assignments preserve callable origins; lexical bindings shadow builtins.
    Another owner's same-named API (e.g. monkeypatch.setattr or archive.getmembers) is not reflection.
    This recognises declared AST spellings, not arbitrary runtime-generated Python.
    """
    tree = ast.parse(source, filename=filename)
    found = _hook_lines(tree)
    found.update(
        call.lineno for call, origin in call_origins(tree, builtins=BANNED_CALLS | {'object'}) if origin in _ORIGINS
    )
    return sorted(found)


def scanned_files(root: Path) -> tuple[str, ...]:
    """Every tracked ``*.py`` under *root* that is not archived code, sorted."""
    return tuple(sorted(rel for rel in tracked_files(root) if rel.endswith('.py') and not is_archived(rel)))


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
            f'NO-REFLECTION: attribute/namespace probes, reflective helpers and hooks are banned. '
            f'Replace each with typed access (attribute, isinstance on a Protocol, dataclasses, a dict, '
            f'pytest.raises(AttributeError)) -- never vars()/__dict__. new={new} '
            f'stale allow entries (delete them)={stale} allow entries without a reason={unreasoned}\n'
            + subject_lines([*new, *stale, *unreasoned])
        )
        raise AssertionError(msg)
