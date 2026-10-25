"""What merging one commit into another WOULD do, read from git objects alone -- no checkout, no index.

ONE READING, THREE CALLERS. The integration tick asks it of every child branch against the
integration branch, ``forge sync`` asks it before it touches the owner's tree, and ``integrate promote``
asks whether the trunk can fast-forward. Each question is a pure read of the object store:

* :func:`trial` -- ``git merge-tree --write-tree`` (git >= 2.38): how far *head* is behind *base*,
  and whether their merge is clean or which files conflict. Nothing is written but loose objects.
* :func:`contains` -- whether *tip* is already an ancestor of *target* (merged, or promotable).
* :func:`merged_at` -- the first commit of *target* whose history brought *tip* in.

FETCH-FREE, the caller's half: every ref named here must already be in the local object store.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['Trial', 'contains', 'merged_at', 'rev', 'shares_unmerged', 'trial']

#: ``git merge-tree --write-tree`` exits 1 for a merge with conflicts; anything else non-zero is an error.
_CONFLICTED: Final = 1


@dataclass(frozen=True)
class Trial:
    """*head* against *base*: commits of *base* it lacks, and the files their merge would conflict in."""

    behind: int
    conflicts: tuple[str, ...]
    #: The merged tree git wrote (conflict markers included when not clean).
    tree: str = ''

    @property
    def clean(self) -> bool:
        """Whether the merge would complete without a conflict."""
        return not self.conflicts


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )


def rev(root: Path, ref: str) -> str | None:
    """The commit *ref* names in *root*, or ``None`` when it names none."""
    done = _git(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}')
    return done.stdout.strip() if done.returncode == 0 else None


def trial(root: Path, base: str, head: str) -> Trial:
    """Merge *base* into *head* in the object store only; raises when git cannot answer at all."""
    behind = _git(root, 'rev-list', '--count', f'{head}..{base}')
    if behind.returncode != 0:
        msg = f'cannot compare {head} with {base} in {root}: {behind.stderr.strip()}'
        raise ValueError(msg)
    done = _git(root, 'merge-tree', '--write-tree', '--name-only', '--no-messages', head, base)
    if done.returncode not in {0, _CONFLICTED}:
        msg = f'git merge-tree could not merge {base} into {head}: {done.stderr.strip()}'
        raise ValueError(msg)
    lines = done.stdout.splitlines()
    files = tuple(line for line in lines[1:] if line.strip())
    conflicts = files if done.returncode == _CONFLICTED else ()
    return Trial(behind=int(behind.stdout.strip()), conflicts=conflicts, tree=lines[0].strip() if lines else '')


def contains(root: Path, target: str, tip: str) -> bool:
    """Whether *tip* is an ancestor of (or equal to) *target*."""
    return _git(root, 'merge-base', '--is-ancestor', tip, target).returncode == 0


def shares_unmerged(root: Path, head: str, other: str, tip: str) -> bool:
    """Whether *head* holds a commit of *other* that *tip* does not: *head* is STACKED on *other*.

    Read off the merge bases, so it holds however far either side moved after the cut. The one owner of
    the stack question: the PR advice (:mod:`dev_lab.dev.pradmit`) and the forge's auto-sync ask it.
    """
    bases = _git(root, 'merge-base', '--all', head, other).stdout.split()
    return any(not contains(root, tip, base) for base in bases)


def merged_at(root: Path, target: str, tip: str) -> str | None:
    """The oldest commit on *target*'s first-parent line that holds *tip* -- its merge, or *tip* itself."""
    if not contains(root, target, tip):
        return None
    line = _git(root, 'rev-list', '--first-parent', target).stdout.split()
    if (found := rev(root, tip)) in line:
        return found
    after = _git(root, 'rev-list', '--first-parent', '--ancestry-path', '--reverse', f'{tip}..{target}').stdout.split()
    return after[0] if after else None
