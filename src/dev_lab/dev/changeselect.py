"""WHICH TESTS A CHANGE REACHES -- ``verify --changed [RANGE]`` runs exactly those.

ONE REACH, NOT TWO. Whether a change can alter a test's outcome is already answered by
:mod:`dev_lab.dev.footprint` -- the static footprint the forge carries an outcome across commits by: the test
file, its ``conftest.py``/``__init__.py`` chain, the transitive closure of its in-repo imports, pytest's own
configuration, and EVERYTHING for a module that reads the repo by path unless ``[tool.dev_lab.carry]`` declares
what it reads. Selection is that same relation read the other way, so a repo declares its remainder once
(``[tool.dev_lab.carry] everywhere`` / ``reads``), never a second table for selection.

The footprints are read off the WORKING TREE (:meth:`~dev_lab.dev.footprint.Footprints.working`), so an
uncommitted edit and a new test file are selected; the changed paths come from ``git diff --name-only`` against
*RANGE* (default ``HEAD``) plus untracked files.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.footprint import Footprints

__all__ = ['changed_paths', 'select']

_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 120


def select(footprints: Footprints, changed: list[str]) -> tuple[str, ...]:
    """The test files whose footprint *changed* (repo-relative POSIX paths) reaches, sorted."""
    return tuple(sorted(test for test in footprints.tests() if footprints.reaches(test, changed)))


def changed_paths(root: Path, range_spec: str) -> list[str]:
    """The repo-relative POSIX paths *range_spec* changed (``git diff --name-only``), plus untracked files.

    An empty *range_spec* means the working tree against ``HEAD``.

    Raises:
        ValueError: git refuses the range; the message names it and git's answer.

    """
    done = _door.run(
        [_GIT, '-C', str(root), 'diff', '--name-only', '-z', range_spec or 'HEAD', '--'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_GIT_TIMEOUT_S,
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
            timeout=_GIT_TIMEOUT_S,
        )
        names.update(filter(None, extra.stdout.split('\0')))
    return sorted(names)
