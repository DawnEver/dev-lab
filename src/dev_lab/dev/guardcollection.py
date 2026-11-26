"""A GUARD THAT COLLECTS NOTHING REFUSES NOTHING -- the zero-collection control (dev-lab#599, first slice).

:func:`dev_lab.dev.rules.unresolved` asks whether a rule's test mechanism is a TRACKED FILE. A tracked file can still
judge nothing: it defines no test, pytest cannot import it (a collection error is a file with no verdict), a
module-level ``pytestmark`` or ``pytest.skip(allow_module_level=True)`` skips it whole, or every test in it is
wrapped in ``skip``/``xfail``. Each reads exactly like an enforced rule. Two readings, each blind where the other
sees:

* ACTUAL COLLECTION (:func:`collected`) -- ``pytest --collect-only -q`` over the mechanism files, counted per file.
  It sees an import failure, an empty file and a conftest that deselects; it cannot see a skip or an xfail, which
  pytest collects and then does not run.
* LAUNDERING (:func:`laundered`) -- the file's AST: a module-wide skip or xfail, or every test function marked so.

:func:`zero_collection` joins the two into one refusal per mechanism, named with the rule ID. It is pure over its
facts, so the planted control drives THIS function.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from typing import TYPE_CHECKING, Final

from lab_commons.launch import run

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = ['LAUNDERING', 'collected', 'is_test_file', 'laundered', 'zero_collection']

#: The pytest marks that collect a test and then do not run it as a verdict.
LAUNDERING: Final = frozenset({'skip', 'skipif', 'xfail'})

_NODE: Final = re.compile(r'^(?P<path>[^:\s]+\.py)::')


def is_test_file(path: str) -> bool:
    """Whether *path* is a pytest test file by name; a mechanism that is CODE (a hook, a famtest body) is not one.

    Measured 2026-11-26 on dev-lab's registry: 101 mechanism files, 7 of them source modules (``hook_install.py``,
    ``famtests/alwayson.py``, ...) declared with the same ``TestPath`` as a test. They refuse by running, not by
    being collected, so collection cannot judge them.
    """
    name = path.rsplit('/', 1)[-1]
    return name.endswith('.py') and (name.startswith('test_') or name.endswith('_test.py'))


def collected(root: Path, paths: Iterable[str], *, python: str = sys.executable) -> Counter[str]:
    """How many test items pytest ACTUALLY collects from each of *paths* (repo-relative), run in *root*."""
    chosen = sorted(set(paths))
    if not chosen:
        return Counter()
    answer = run(
        [python, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', '--continue-on-collection-errors',
         *chosen],
        cwd=root, capture_output=True, text=True, encoding='utf-8', check=False, timeout=1800,
    )  # fmt: skip
    counts: Counter[str] = Counter()
    for line in answer.stdout.splitlines():
        if match := _NODE.match(line.strip()):
            counts[match['path'].replace('\\', '/')] += 1
    return counts


def _mark(node: ast.expr) -> str:
    """The mark name of ``pytest.mark.<name>`` or ``pytest.mark.<name>(...)``; ``''`` for anything else."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Attribute) and target.value.attr == 'mark':
        return target.attr
    return ''


def _module_wide(tree: ast.Module) -> str:
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'pytestmark' for t in stmt.targets):
            marks = stmt.value.elts if isinstance(stmt.value, (ast.List, ast.Tuple)) else [stmt.value]
            if found := sorted({_mark(m) for m in marks} & LAUNDERING):
                return f'its module-level pytestmark is {found[0]}'
        call = stmt.value if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) else None
        skips = call is not None and isinstance(call.func, ast.Attribute) and call.func.attr == 'skip'
        if skips and any(kw.arg == 'allow_module_level' for kw in call.keywords):
            return 'it skips itself at module level'
    return ''


def laundered(text: str) -> str:
    """Why the test file *text* runs no verdict although it collects, or ``''``: module-wide or every test."""
    try:
        tree = ast.parse(text)
    except SyntaxError as broken:
        return f'it does not parse ({broken.msg}, line {broken.lineno})'
    if why := _module_wide(tree):
        return why
    tests = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test')
    ]
    if tests and all({_mark(d) for d in node.decorator_list} & LAUNDERING for node in tests):
        return f'every one of its {len(tests)} test(s) is marked skip or xfail'
    return ''


def zero_collection(
    mechanisms: Mapping[str, Iterable[str]], *, counts: Mapping[str, int], texts: Mapping[str, str]
) -> tuple[str, ...]:
    """One refusal per rule mechanism (``rule id -> test paths``) that collects nothing or runs no verdict.

    *counts* is :func:`collected`'s reading and *texts* each path's source; a path with no text is not tracked,
    which :func:`dev_lab.dev.rules.unresolved` already says, so it is not said twice; a code mechanism
    (:func:`is_test_file` false) is not collection's to judge.
    """
    out: list[str] = []
    for rule_id, paths in sorted(mechanisms.items()):
        for path in paths:
            if path not in texts or not is_test_file(path):
                continue
            if not counts.get(path, 0):
                out.append(f'{rule_id}: {path} collects no test (empty, or pytest cannot import it)')
            elif why := laundered(texts[path]):
                out.append(f'{rule_id}: {path} collects but runs no verdict: {why}')
    return tuple(out)
