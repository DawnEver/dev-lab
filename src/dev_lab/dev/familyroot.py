"""Where a checkout's family lives: its MAIN checkout and the directory holding the family's checkouts side by side.

A LEAF THAT IMPORTS NO PEER SIBLING SUBPACKAGE (measured 2026-11-20). The dependency door (:mod:`dev_lab.dev.dep`)
reads :func:`family_root` to resolve a local sibling source. It used to import it from
:mod:`dev_lab.dev.worktreeplace`, which imports :mod:`lab_commons.storage` at load. A kit whose lock moved dev-lab
ahead of lab-commons then died importing ``lab_commons.storage`` -- inside the one door that relocks lab-commons
to heal it. These two answers read only git, so they live here, and the door's import path stays importable
against any lab-commons.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import lab_commons.launch as _door

__all__ = ['family_root', 'main_checkout']

_GIT = shutil.which('git') or 'git'


def main_checkout(root: Path) -> Path:
    """The MAIN checkout of the repository *root* belongs to -- itself, unless *root* is a linked worktree.

    THE CONSEQUENCE OF THIS RULE, CLOSED AT THE SOURCE. A linked worktree lives at
    ``<main>/.claude/worktrees/<name>``, so ``<checkout>/..`` is no longer where the family's other repos
    are. Every sibling lookup goes through :func:`family_root`, which reads git's COMMON directory --
    shared by every worktree of one repo -- rather than the checkout path.

    Raises:
        RuntimeError: when git cannot answer -- a guessed root would read the wrong siblings silently.

    """
    done = _door.run(
        [_GIT, '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        msg = f'git rev-parse --git-common-dir failed in {root}: {done.stderr.strip()}'
        raise RuntimeError(msg)
    return Path(done.stdout.strip()).parent


def family_root(root: Path) -> Path:
    """The directory holding the family's checkouts side by side: the MAIN checkout's parent."""
    return main_checkout(root).parent
