"""NATIVE-FIRST: Python declares and orchestrates, Rust computes -- the static half of the ``native-first`` principle.

User ruling 2026-11-25. A repo OPTS IN in its ``pyproject.toml``::

    [tool.dev_lab.native]
    orchestration = ["src/<pkg>/workflow", ...]   # repo-relative paths that only declare and orchestrate
    [tool.dev_lab.native.stages]
    <stage> = "<native module>"                    # each native-owned stage and the module that owns it

An undeclared repo is not judged, and the CLI says so. Three refusals, read off the source with ``ast`` (nothing
is imported or run):

1. NUMERIC LOOP (under an orchestration path): a ``for`` over ``range``/``ndindex``/``ndenumerate``, or a
   ``while`` with a counter it ``+=``s, whose body stores into, updates or does arithmetic on an element indexed by
   the loop variable, or calls ``math``/``cmath`` per element.
2. STAGE TWIN (under an orchestration path): a module named for a native-owned stage (``<stage>.py`` or a
   ``<stage>/`` package) that never imports the stage's native module -- a second implementation, not a wrapper.
3. TWIN TEST (any test file: ``test_*.py``, ``*_test.py`` or under ``tests/``): a test importing a stage's native
   module AND, outside the native module's top package, a module whose last name is the stage -- the native
   result compared against a Python twin instead of a reference.

WHAT IT CANNOT SEE, stated so a green is not read as more than it is: it has no types, so an index loop doing
element arithmetic on a dict or list is refused like one on an array, and iterating an array directly
(``for x in arr``), a comprehension, a loop hidden behind a helper call, and a twin under another name are not
seen. A twin is recognized by NAME only, and a wrapper by its import of the native module.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import importedges
from dev_lab.dev.family import declared_table

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ['DOOR', 'RULE_ID', 'Native', 'check', 'declared', 'declared_native', 'main', 'problems']

RULE_ID: Final = 'NATIVE-FIRST'
_TABLE: Final = 'native'
DOOR: Final = (
    'move the computation into the native stage and call it from Python (vectorized numpy is fine); accept the '
    'native result against a reference (analytic, the vendor ladder, the previous implementation during a '
    'migration), never a Python twin'
)
_DETAILS: Final = 'details: docs-src/dev/refusals.md#native-first (dev-lab)'
_INDEX_ITERATORS: Final = frozenset({'range', 'ndindex', 'ndenumerate'})
_MATH_MODULES: Final = frozenset({'math', 'cmath'})


@dataclass(frozen=True, slots=True)
class Native:
    """The declaration: the orchestration-only paths and each native-owned stage's native module."""

    orchestration: tuple[str, ...]
    stages: dict[str, str] = field(default_factory=dict)


def _manifest(root: Path) -> dict[str, object] | None:
    try:
        return tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except OSError:
        return None


def declared(root: Path) -> bool:
    """Whether *root* opts in: a ``[tool.dev_lab.native]`` table, or a manifest too broken to say (then judged)."""
    try:
        data = _manifest(root)
    except ValueError:
        return True
    return data is not None and declared_table(data, _TABLE) is not None


def declared_native(root: Path) -> Native | None:
    """*root*'s ``[tool.dev_lab.native]``; ``None`` when undeclared (not judged). A malformed one raises ValueError."""
    data = _manifest(root)
    table = None if data is None else declared_table(data, _TABLE)
    if table is None:
        return None
    paths, stages = table.get('orchestration', []), table.get('stages', {})
    if not isinstance(paths, list) or not all(isinstance(p, str) and p.strip('/') for p in paths):
        msg = f'[tool.dev_lab.{_TABLE}] orchestration must be a list of repo-relative paths, not {paths!r}'
        raise ValueError(msg)
    if not isinstance(stages, dict) or not all(isinstance(v, str) and v for v in stages.values()):
        msg = f'[tool.dev_lab.{_TABLE}.stages] must map each stage to its native module name, not {stages!r}'
        raise ValueError(msg)
    return Native(tuple(p.strip('/') for p in paths), dict(stages))


def _under(rel: str, paths: Iterable[str]) -> bool:
    return any(rel == p or rel.startswith(f'{p}/') for p in paths)


def _is_test(rel: str) -> bool:
    path = PurePosixPath(rel)
    return path.name.startswith('test_') or path.stem.endswith('_test') or 'tests' in path.parts[:-1]


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _callee(call: ast.Call) -> tuple[str | None, str]:
    """``(module, name)`` of a call: ``math.sin(x)`` -> ``('math', 'sin')``, ``range(n)`` -> ``(None, 'range')``."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return (func.value.id if isinstance(func.value, ast.Name) else None), func.attr
    return None, func.id if isinstance(func, ast.Name) else ''


def _numeric_body(body: list[ast.stmt], index: set[str]) -> bool:
    """Whether *body* stores, updates or computes on an element indexed by *index*, or calls per-element math."""

    def indexed(node: ast.AST) -> bool:
        return isinstance(node, ast.Subscript) and bool(_names(node.slice) & index)

    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assign) and any(indexed(t) for t in node.targets):
                return True
            if isinstance(node, ast.AugAssign) and indexed(node.target):
                return True
            if isinstance(node, ast.BinOp) and (indexed(node.left) or indexed(node.right)):
                return True
            if isinstance(node, ast.Call) and _callee(node)[0] in _MATH_MODULES:
                return True
    return False


def _loop_problems(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
            if _callee(node.iter)[1] in _INDEX_ITERATORS and _numeric_body(node.body, _names(node.target)):
                lines.append(node.lineno)
        elif isinstance(node, ast.While):
            counters = {
                n.target.id
                for stmt in node.body
                for n in ast.walk(stmt)
                if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)
            }
            if counters and _numeric_body(node.body, counters):
                lines.append(node.lineno)
    return lines


def _stage_of(rel: str) -> str:
    path = PurePosixPath(rel)
    return path.parent.name if path.name == '__init__.py' else path.stem


def _imports_native(edges: frozenset[str], native: str) -> bool:
    return any(e == native or e.startswith(f'{native}.') for e in edges)


def _file_problems(root: Path, rel: str, spec: Native) -> list[str]:
    source = (root / rel).read_text(encoding='utf-8')
    found: list[str] = []
    orchestration = _under(rel, spec.orchestration)
    if orchestration:
        found += [
            f'{RULE_ID}: {rel}:{line}: a numeric loop over array data under an orchestration-only path'
            for line in _loop_problems(ast.parse(source))
        ]
    edges = importedges.import_edges(
        source, importedges.module_name(root, root / rel), is_package=rel.endswith('__init__.py')
    )
    stage = _stage_of(rel)
    if orchestration and stage in spec.stages and not _imports_native(edges, spec.stages[stage]):
        found.append(
            f'{RULE_ID}: {rel}: a Python module for the native-owned stage `{stage}` that never imports '
            f'{spec.stages[stage]} -- a second implementation, not a wrapper'
        )
    if _is_test(rel):
        for name, native in sorted(spec.stages.items()):
            if not _imports_native(edges, native):
                continue
            top = native.split('.')[0]
            twins = sorted(e for e in edges if e.rsplit('.', 1)[-1] == name and e.split('.')[0] != top)
            if twins:
                found.append(
                    f'{RULE_ID}: {rel}: a test importing the native stage {native} and its Python twin '
                    f'{", ".join(twins)} -- accept against a reference instead'
                )
    return found


def problems(root: Path, spec: Native, files: Iterable[str]) -> list[str]:
    """Every refusal over the ``.py`` *files* (repo-relative POSIX paths) that exist under *root*."""
    found: list[str] = []
    for rel in sorted(f for f in files if f.endswith('.py') and (root / f).is_file()):
        found += _file_problems(root, rel, spec)
    return found


def check(root: Path) -> None:
    """The always-on family check: raise naming every refusal in *root*'s tracked tree (when declared)."""
    from dev_lab.dev.rules import tracked_files  # noqa: PLC0415 -- the registry imports this module's rows

    spec = declared_native(root)
    if spec is None:
        return
    if found := problems(root, spec, tracked_files(root)):
        raise AssertionError('\n'.join([*found, f'door: {DOOR}', _DETAILS]))


def main(argv: list[str] | None = None, *, cwd: Path | None = None) -> int:
    """Judge the given paths (the pre-commit row passes the staged ones), else the tracked tree; exit 1 on a refusal."""
    root = cwd or Path.cwd()
    spec = declared_native(root)
    if spec is None:
        emit(f'{RULE_ID}: [tool.dev_lab.{_TABLE}] is not declared, so this repo is not judged', flush=True)
        return 0
    if argv:
        found = problems(root, spec, argv)
    else:
        from dev_lab.dev.rules import tracked_files  # noqa: PLC0415 -- the registry imports this module's rows

        found = problems(root, spec, tracked_files(root))
    if not found:
        return 0
    emit('\n'.join([*found, f'door: {DOOR}', _DETAILS]), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
