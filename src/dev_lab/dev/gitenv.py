"""The environment a git call against ANOTHER repository runs in: the caller's repository unnamed.

A git hook runs with ``GIT_DIR`` (and the other repository locators) naming the repository being pushed. They
override ``git -C <dir>``, so ``git -C <throwaway> init --bare`` started from a hook re-initialised the CALLER'S
shared ``.git`` as bare (``core.bare=true``) and every linked worktree then failed with "must be run in a work
tree" (2026-11-10, two family repos, through the pre-push lock-lag read). Every git call aimed at a scratch,
cache or throwaway repository runs in :func:`unlocated`.
"""

from __future__ import annotations

import os
from typing import Final

__all__ = ['REPOSITORY_LOCATORS', 'unlocated']

#: ``git rev-parse --local-env-vars`` (git 2.4x): every variable that points git at one repository.
REPOSITORY_LOCATORS: Final = frozenset({
    'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT',
    'GIT_OBJECT_DIRECTORY', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE',
    'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS', 'GIT_REPLACE_REF_BASE', 'GIT_PREFIX', 'GIT_SHALLOW_FILE',
    'GIT_COMMON_DIR',
})  # fmt: skip


def unlocated() -> dict[str, str]:
    """The current process environment without :data:`REPOSITORY_LOCATORS`."""
    return {name: value for name, value in os.environ.items() if name not in REPOSITORY_LOCATORS}
