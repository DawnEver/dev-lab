"""A TEST RUNS JS ON THE LOCKED ENGINE, NEVER ON THE HOST'S ``node``: :mod:`dev_lab.dev.jsrun` is the one spelling.

``shutil.which('node')`` or a ``'node'`` argv in a test is an UNDECLARED HOST DEPENDENCY: the lock
never states it, so the test reds on any host without Node -- the cluster verdict host among them,
which must not install one (user ruling 2026-10-28). This body reads a consumer's tests off the AST
and refuses every ``which('node')`` and every string literal that IS ``node`` or starts ``node `` as
the first element of a LAUNCHER call's argv (:data:`LAUNCHERS`; a list/tuple first item, or a whole
command string). A ``'node'`` elsewhere -- a label, a later argv item, ``line.startswith('node ')`` -- is
not a launch and stays green.

THE ENGINE IS DEV-ONLY (user ruling 2026-10-28), and :func:`assert_engine_is_dev_only` is that half:
a consumer's ``[project.dependencies]`` and every extra it does not name as a dev extra must carry
neither an engine distribution (:data:`dev_lab.dev.jsrun.ENGINE_DISTRIBUTIONS`) nor ``dev-lab[test]``.
``[dependency-groups]`` are dev by definition and are not read.
"""

from __future__ import annotations

import ast
import re
import tomllib
from typing import TYPE_CHECKING, Final

from dev_lab.dev.jsrun import ENGINE_DISTRIBUTIONS, JS_EXTRA

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator
    from pathlib import Path

__all__ = [
    'LAUNCHERS',
    'EngineNotDevOnly',
    'HostNode',
    'assert_engine_is_dev_only',
    'assert_no_host_node',
    'engine_leaks',
    'host_node_uses',
]

#: The callables whose first argument is an argv: ``subprocess``'s, ``os``'s, ``asyncio``'s and the door's.
LAUNCHERS: Final = frozenset(
    {
        'run',
        'Popen',
        'popen',
        'call',
        'check_call',
        'check_output',
        'system',
        'create_subprocess_exec',
        'create_subprocess_shell',
        'spawnv',
        'spawnvp',
        'execv',
        'execvp',
    }
)

#: A PEP 508 requirement's name and its optional ``[extras]``.
_REQUIREMENT: Final = re.compile(r'^\s*([A-Za-z0-9._-]+)\s*(?:\[([^\]]*)\])?')


class EngineNotDevOnly(AssertionError):
    """The JS engine reaches a runtime dependency or a non-dev extra."""


class HostNode(AssertionError):
    """A test launches the host's ``node`` instead of :func:`dev_lab.dev.jsrun.run_js`."""


def _is_node(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value == 'node' or node.value.startswith('node '))
    )


def _called(func: ast.expr) -> str:
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _uses(tree: ast.Module) -> Iterator[int]:
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        first = node.args[0]
        head = first.elts[0] if isinstance(first, (ast.List, ast.Tuple)) and first.elts else first
        called = _called(node.func)
        if (called in LAUNCHERS and _is_node(head)) or (called == 'which' and _is_node(first)):
            yield node.lineno


def host_node_uses(source: str) -> tuple[int, ...]:
    """The lines of *source* that reach the host's ``node``, sorted."""
    return tuple(sorted(set(_uses(ast.parse(source)))))


def assert_no_host_node(*, tests: Path, floor: int) -> None:
    """No test under *tests* launches the host's ``node``.

    Args:
        tests: the consumer's tests directory.
        floor: the fewest test files the scan must read; under it the scan read nothing worth trusting.

    Raises:
        HostNode: a host Node use was found, or the scan read under *floor* files.

    """
    files = sorted(tests.rglob('*.py'))
    if len(files) < floor:
        msg = f'read {len(files)} file(s) under {tests}, under the floor of {floor}'
        raise HostNode(msg)
    found = [f'{path}:{line}' for path in files for line in host_node_uses(path.read_text(encoding='utf-8'))]
    if found:
        sites = '\n'.join(f'  {site}' for site in found)
        msg = (
            f'{len(found)} host Node use(s): the lock never declares a host `node`, so the test reds on a '
            'host without one. Run the program with dev_lab.dev.jsrun.run_js(program, *flags), the locked '
            f'engine:\n{sites}'
        )
        raise HostNode(msg)


def _carries_engine(requirement: str) -> bool:
    match = _REQUIREMENT.match(requirement)
    if match is None:
        return False
    name = match.group(1).lower().replace('_', '-')
    extras = {e.strip() for e in (match.group(2) or '').split(',')}
    return name in ENGINE_DISTRIBUTIONS or (name == 'dev-lab' and JS_EXTRA in extras)


def engine_leaks(pyproject: str, *, dev_extras: Collection[str]) -> tuple[str, ...]:
    """Each ``<table>: <requirement>`` in *pyproject* that ships the engine outside *dev_extras*."""
    project = tomllib.loads(pyproject).get('project', {})
    tables = {'dependencies': project.get('dependencies', [])} | {
        f'optional-dependencies.{name}': reqs
        for name, reqs in project.get('optional-dependencies', {}).items()
        if name not in dev_extras
    }
    return tuple(f'{table}: {req}' for table, reqs in tables.items() for req in reqs if _carries_engine(req))


def assert_engine_is_dev_only(*, pyproject: str, dev_extras: Collection[str]) -> None:
    """The JS engine is in no runtime dependency and no extra outside *dev_extras*.

    Args:
        pyproject: the consumer's ``pyproject.toml`` TEXT.
        dev_extras: the extras the consumer declares as development-only; no default, it is a repo fact.

    Raises:
        EngineNotDevOnly: a runtime table carries the engine.

    """
    leaks = engine_leaks(pyproject, dev_extras=dev_extras)
    if leaks:
        sites = '\n'.join(f'  {leak}' for leak in leaks)
        msg = (
            f'the JS engine is test/dev tooling only, yet {len(leaks)} runtime requirement(s) ship it: move each '
            f'to a dev extra (as dev-lab[{JS_EXTRA}]) so a product install never carries Node:\n{sites}'
        )
        raise EngineNotDevOnly(msg)
