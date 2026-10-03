"""WORKTREES-STAY-INSIDE: every checkout of a repository lives under ``<toplevel>/.claude/worktrees/``.

THE DEFECT, MEASURED 2026-10-03. Eight linked worktrees across the family had been created as
SIBLINGS of their repositories (``<parent>/<repo>-wt-cf``, ``<parent>/<repo>-placement`` ...). A
tree outside its repository is outside every scan that repo runs over itself, outside its
``.gitignore``, and outside the place the next agent looks; the user ruled the same day that creating one is forbidden family-wide.

ONE FACT, THREE MECHANISMS, AND THIS MODULE IS THE FACT. :data:`WORKTREES_REL` is the only spelling
of the location. The agent deny row ``WORKTREES-STAY-INSIDE`` (:mod:`lab_commons.dev._deny_rows`)
PREVENTS a misplaced ``git worktree add|move`` / ``git clone`` and derives its path regex from it;
:mod:`lab_commons.dev.famtests.worktreeplace` DETECTS a misplaced tree that got past the guard, by
reading :func:`misplaced_worktrees`; and the family ``.gitignore`` base ignores it.

WHAT THE GUARD CANNOT SEE AND THIS CAN. A deny pattern reads TEXT: it can insist the target path ends
in ``.claude/worktrees/<name>``, but not that the ``.claude`` belongs to the repository in question.
That residue -- an absolute path into some other directory's ``.claude/worktrees`` -- is exactly what
``git worktree list`` answers, so the detection half is not a duplicate of the prevention half.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    'WORKTREES_REL',
    'Misplaced',
    'is_inside',
    'listed_worktrees',
    'misplaced_worktrees',
    'remedy',
]

#: Where every linked worktree of a repository lives, relative to that repository's MAIN toplevel.
#: The single source: the deny row's path regex and the gitignore base line are both derived from it.
WORKTREES_REL: Final = '.claude/worktrees'

_GIT = shutil.which('git') or 'git'


@dataclass(frozen=True, slots=True)
class Misplaced:
    """One linked worktree outside ``<main>/.claude/worktrees/``, and where it should go."""

    path: Path
    main: Path

    @property
    def move_to(self) -> Path:
        """The allowed destination: the same leaf name, inside the repository."""
        return self.main / WORKTREES_REL / self.path.name


def _norm(path: Path) -> str:
    """A comparable spelling: resolved, forward slashes, case-folded where the filesystem folds case."""
    return os.path.normcase(str(path.resolve())).replace('\\', '/').rstrip('/')


def is_inside(path: Path, main: Path) -> bool:
    """Does *path* lie strictly inside ``<main>/.claude/worktrees/``? PURE apart from ``resolve``."""
    base = _norm(main / WORKTREES_REL)
    return _norm(path).startswith(base + '/')


def listed_worktrees(root: Path) -> tuple[Path, ...]:
    """Every worktree git records for the repository at *root*, MAIN FIRST, as ``git worktree list`` says.

    Raises:
        RuntimeError: when git cannot answer -- an unread list must never read as a clean one.

    """
    done = subprocess.run(
        [_GIT, '-C', str(root), 'worktree', 'list', '--porcelain'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        msg = f'git worktree list failed in {root}: {done.stderr.strip()}'
        raise RuntimeError(msg)
    return tuple(Path(line[len('worktree ') :]) for line in done.stdout.splitlines() if line.startswith('worktree '))


def misplaced_worktrees(root: Path) -> tuple[Misplaced, ...]:
    """The linked worktrees of *root*'s repository that are NOT inside its ``.claude/worktrees/``.

    The main checkout is the first entry git lists and is excepted -- it IS the repository. Asked from
    inside a linked worktree the answer is the same, because git lists the same set from every tree.
    """
    listed = listed_worktrees(root)
    if not listed:
        msg = f'git listed no worktree at all for {root}, not even the main checkout'
        raise RuntimeError(msg)
    main, *linked = listed
    return tuple(Misplaced(path, main) for path in linked if not is_inside(path, main))


def remedy(found: Misplaced) -> str:
    """The exact command that puts *found* where the rule says, REFUSAL-NAMES-THE-REMEDY."""
    return f'git -C "{found.main.as_posix()}" worktree move "{found.path.as_posix()}" "{found.move_to.as_posix()}"'
