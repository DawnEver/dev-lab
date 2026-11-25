"""The address a verify verdict names: the measured targets by content, plus every tracked file as it is on disk.

Split out of :mod:`dev_lab.dev.verifysteps` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module runs
the steps; this one says WHICH tree they ran on.
"""

from __future__ import annotations

import hashlib
import shutil
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.content import ABSENT, content_address, file_digest

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['MEASURED_TARGETS', 'tree_address']

#: What the tree address covers, for EVERY repo in the family. A fixed tuple rather than a
#: per-repo list: :func:`~dev_lab.dev.content.content_address` records a target that is not
#: there as ``absent``, so a repo without one of these addresses differently instead of needing a
#: branch here -- and a repo that ACQUIRES one changes its address, which is correct.
MEASURED_TARGETS: Final[tuple[str, ...]] = ('src', 'tests', 'pyproject.toml')

_GIT: Final = shutil.which('git') or 'git'


def _git_z(root: Path, *args: str) -> tuple[str, ...] | None:
    """NUL-separated output of ``git -C root <args>``; ``None`` when *root* is not a git work tree."""
    done = _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=120
    )
    return tuple(part for part in done.stdout.split('\0') if part) if done.returncode == 0 else None


def tree_address(root: Path) -> str:
    """The address a verdict names: :data:`MEASURED_TARGETS` by content, plus every TRACKED file as it is on disk.

    2026-11-13: a cited FAIL was reused for "the same tree" while a tracked file outside the targets held unstaged
    edits. The tracked half is the index (``git ls-files -s``: path and blob sha, content-addressed) with each file
    the working tree differs from it on (``git diff --name-only``, the stat-cached check) hashed from its bytes, or
    ``absent`` -- so every tracked byte is covered without reading every tracked file. Outside git: the targets only.
    """
    base = content_address(root, MEASURED_TARGETS)
    index = _git_z(root, 'ls-files', '-s', '-z')
    changed = _git_z(root, 'diff', '--name-only', '-z')
    if index is None or changed is None:
        return base
    digest = hashlib.sha256('\n'.join(index).encode('utf-8'))
    for rel in sorted(changed):
        path = root / rel
        digest.update(f'\n{rel}\0{file_digest(path) if path.is_file() else ABSENT}'.encode())
    return f'{base}+tracked:{digest.hexdigest()[:16]}'
