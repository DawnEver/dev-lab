"""THE FAMILY PYTHON, as the body every consumer runs: what its manifest declares and its workflows render is ours.

User ruling 2026-11-27 (dev-lab #1045): one interpreter, declared once in :mod:`dev_lab.dev.pythontoolchain`. The
judgment is that module's :func:`~dev_lab.dev.pythontoolchain.drift` -- ``[project] requires-python`` and ``[tool.ruff]
target-version`` are the family's, and every ``uv sync`` a rendered workflow runs names the family interpreter --
so this body adds a remedy and nothing else. A consumer calls::

    from dev_lab.dev.famtests.pythontoolchain import assert_the_family_python

    def test_this_repo_runs_the_family_python() -> None:
        assert_the_family_python(root=ROOT)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.pythontoolchain import VERSION, drift

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['ForeignPython', 'assert_the_family_python']


class ForeignPython(AssertionError):
    """The repo declares or renders a Python other than the family's."""


def assert_the_family_python(*, root: Path) -> None:
    """Raise :class:`ForeignPython` naming every place *root* leaves the family Python, each with its door."""
    if problems := drift(root):
        lines = [f'the family Python is {VERSION} (dev_lab.dev.pythontoolchain.VERSION); {root} leaves it:', *problems]
        raise ForeignPython('\n  '.join(lines))
