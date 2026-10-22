"""AN OS IS A RESOURCE, SO A PLATFORM SKIP IS A TEST NOBODY RUNS: the marker is the one spelling.

An OS is a resource like a tool (:mod:`lab_commons.hpc.needsets`): every host supplies its own OS by
itself (:func:`lab_commons.compute.probe.os_name`, read by the supply and by
:func:`lab_commons.dev.localpart.present_here`), so ``@pytest.mark.windows`` puts a test in a part
(``tests/windows``, ``tests/femm+windows``) that only a Windows host produces. ``skipif(sys.platform !=
'win32')`` does the opposite: the test lands in ``tests/base``, a Linux host produces that part, the
test is skipped there and runs NOWHERE -- green for a path no host executes (XFAIL-NOT-SKIP).

This body reads a consumer's tests off the AST and refuses every ``skipif`` whose condition, and every
``pytest.skip`` guarded by an ``if`` whose test, reads the platform (``sys.platform``, ``os.name``,
``platform.system()``). The refusal names the marker to carry instead and, when the consumer's
``[tool.lab_commons.tests] resources`` lacks that OS, the declaration to add.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from lab_commons.compute.probe import OS_NAMES
from lab_commons.hpc.needsets import read_vocabulary

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ['PLATFORM_READERS', 'PlatformSkip', 'assert_no_platform_skips', 'platform_skips']

#: ``(module, attribute)`` pairs whose read is a platform test.
PLATFORM_READERS: Final = frozenset({('sys', 'platform'), ('os', 'name'), ('platform', 'system')})

_OSES: Final = tuple(sorted(set(OS_NAMES.values())))


class PlatformSkip(AssertionError):
    """A test skips on the platform instead of carrying the OS marker."""


def _reads_platform(node: ast.AST) -> bool:
    return any(
        isinstance(sub, ast.Attribute)
        and isinstance(sub.value, ast.Name)
        and (sub.value.id, sub.attr) in PLATFORM_READERS
        for sub in ast.walk(node)
    )


def _called(func: ast.expr) -> str:
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def _skips(tree: ast.Module) -> Iterator[int]:
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _reads_platform(node.test):
            guarded.update(id(sub) for stmt in node.body for sub in ast.walk(stmt))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called(node.func)
        conditions = [*node.args, *(k.value for k in node.keywords)]
        skipif = name == 'skipif' and any(_reads_platform(one) for one in conditions)
        if skipif or (name == 'skip' and id(node) in guarded):
            yield node.lineno


def platform_skips(source: str) -> tuple[int, ...]:
    """The lines of *source* that skip on the platform, sorted."""
    return tuple(sorted(set(_skips(ast.parse(source)))))


def assert_no_platform_skips(*, tests: Path, pyproject: str, floor: int) -> None:
    """No test under *tests* skips on the platform; it carries the OS marker *pyproject* declares.

    Args:
        tests: the consumer's tests directory.
        pyproject: the consumer's ``pyproject.toml`` TEXT.
        floor: the fewest test files the scan must read; under it the scan read nothing worth trusting.

    Raises:
        PlatformSkip: a platform skip was found, or the scan read under *floor* files.

    """
    files = sorted(tests.rglob('*.py'))
    if len(files) < floor:
        msg = f'read {len(files)} file(s) under {tests}, under the floor of {floor}'
        raise PlatformSkip(msg)
    found = [f'{path}:{line}' for path in files for line in platform_skips(path.read_text(encoding='utf-8'))]
    if found:
        declared = set(read_vocabulary(pyproject).resources)
        missing = [name for name in _OSES if name not in declared]
        add = f' and declare {missing} in [tool.lab_commons.tests] resources' if missing else ''
        sites = '\n'.join(f'  {site}' for site in found)
        msg = (
            f'{len(found)} platform skip(s): a skipped test runs on NO host, because its part is produced on '
            f'another OS. Replace each with @pytest.mark.<os> (one of {list(_OSES)}){add}:\n{sites}'
        )
        raise PlatformSkip(msg)
