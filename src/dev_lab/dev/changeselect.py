"""WHICH TESTS A CHANGE REACHES -- answered from edges, every edge kind named; ``verify --changed`` runs them.

A test reaches code in three ways, and each is followed rather than guessed:

1. IMPORT -- the closure of the test's imports (:mod:`dev_lab.dev.importedges`), at any depth, either spelling.
2. PATH LITERAL -- a string constant in the test naming a file that exists (a module loaded by path,
   a fixture file read) is the edge itself.
3. CONFTEST -- a changed ``conftest.py`` selects its whole directory; a changed test selects itself.

What no edge can follow is DECLARED as data, never prose -- ``[tool.dev_lab.verify.select]``:

* ``always`` -- paths run on every change (a test asserting the source TREE rather than a module);
* ``full`` -- files whose change selects the whole suite (default ``pyproject.toml`` and ``uv.lock``:
  they change the environment every test runs in).

A deleted module selects every test whose imports NAME it, since the tree no longer resolves it.
"""

from __future__ import annotations

import ast
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.importedges import closure, edges, imports_of, module_name, python_files

__all__ = ['SelectData', 'Selection', 'changed_paths', 'select', 'select_data']

#: Full-selection files when a repo declares none: the environment's own declaration and lock.
_DEFAULT_FULL: Final[tuple[str, ...]] = ('pyproject.toml', 'uv.lock')

#: Longest string constant read as a candidate path literal; longer ones are prose, not paths.
_PATH_MAX: Final = 260


@dataclass(frozen=True)
class SelectData:
    """A repo's declared remainder: paths always run, and files whose change selects everything."""

    always: tuple[str, ...]
    full: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    """The tests a change reaches (sorted, repo-relative POSIX), or ``full`` with the reasons why."""

    paths: tuple[str, ...]
    full: bool = False
    reasons: tuple[str, ...] = ()


def select_data(root: Path) -> SelectData:
    """``[tool.dev_lab.verify.select]`` of *root*'s pyproject; absent keys take the stated defaults."""
    pyproject = root / 'pyproject.toml'
    table = tomllib.loads(pyproject.read_text(encoding='utf-8')) if pyproject.is_file() else {}
    declared = table.get('tool', {}).get('dev_lab', {}).get('verify', {}).get('select', {})
    return SelectData(always=tuple(declared.get('always', ())), full=tuple(declared.get('full', _DEFAULT_FULL)))


def _is_test(path: Path) -> bool:
    return path.name.startswith('test_') and path.suffix == '.py'


def _literals(path: Path) -> frozenset[str]:
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError:
        return frozenset()
    return frozenset(
        node.value.replace('\\', '/')
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and 0 < len(node.value) < _PATH_MAX
    )


def select(root: Path, changed: list[Path], data: SelectData) -> Selection:
    """The tests under *root* that *changed* (repo-relative) can reach, plus ``data.always``."""
    rels = sorted({path.as_posix() for path in changed})
    reasons = tuple(f'{rel} is declared full-selection' for rel in rels if rel in data.full)
    if reasons:
        return Selection(paths=(), full=True, reasons=reasons)
    files = python_files(root)
    tests = [path for path in files if _is_test(path)]
    graph = edges(root, files)
    changed_modules = {module_name(root, root / rel) for rel in rels if rel.endswith('.py')}
    picked = set(data.always)
    for rel in rels:
        path = root / rel
        if path.name == 'conftest.py':
            picked.add(Path(rel).parent.as_posix())
        elif _is_test(path) and path.exists():
            picked.add(rel)
    for test in tests:
        rel = test.relative_to(root).as_posix()
        reach = closure(graph, {module_name(root, test)})
        named = imports_of(root, test)
        if (
            reach & changed_modules
            or any(name == gone or name.startswith(f'{gone}.') for name in named for gone in changed_modules)
            or _literals(test) & set(rels)
        ):
            picked.add(rel)
    return Selection(paths=tuple(sorted(picked)))


_GIT: Final = shutil.which('git') or 'git'


def changed_paths(root: Path, range_spec: str) -> list[Path]:
    """The repo-relative paths *range_spec* changed (``git diff --name-only``), plus untracked files.

    An empty *range_spec* means the working tree against ``HEAD``. Raises :class:`ValueError` naming the
    range when git refuses it, so the caller's wall says which range and why.
    """
    done = _door.run(
        [_GIT, '-C', str(root), 'diff', '--name-only', '-z', range_spec or 'HEAD', '--'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=120,
    )
    if done.returncode != 0:
        why = f'git diff {range_spec or "HEAD"} failed: {done.stderr.strip()}'
        raise ValueError(why)
    names = set(filter(None, done.stdout.split('\0')))
    if not range_spec:
        extra = _door.run(
            [_GIT, '-C', str(root), 'ls-files', '--others', '--exclude-standard', '-z'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
            timeout=120,
        )
        names.update(filter(None, extra.stdout.split('\0')))
    return [Path(name) for name in sorted(names)]
