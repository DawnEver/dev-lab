"""The family's ONE answer to "what does *head*'s range start from" -- every range-reading check asks here.

A range check (``merge-audit``, ``memory-adds``, ``env-pending-shrinks``, ``zero-core-change``) judges *head*
since its merge base with the integration branch. Git answers ``merge-base`` with exit 1 when the two share no
ancestor, and the answer depends on what the integration side HOLDS:

* EMPTY TREE (a trunk founded as an empty root commit, before any lane landed): nothing on that side can be lost,
  so the range is the whole head history measured from the empty tree (:data:`EMPTY_TREE`).
* CONTENT: the histories are truly unrelated; :class:`NoMergeBaseError` refuses by name with :data:`DOOR`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['DOOR', 'EMPTY_TREE', 'NoMergeBaseError', 'log_range', 'merge_bases', 'range_base']

#: Git's well-known empty tree: a diff from it reports every path as added.
EMPTY_TREE: Final = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
RULE_ID: Final = 'NO-MERGE-BASE'
DOOR: Final = (
    'merge the integration branch into the lane with `git merge --allow-unrelated-histories origin/<integration>` '
    'and land that merge through a PR, or start the lane from the integration branch'
)
_NO_COMMON_ANCESTOR: Final = 1


class NoMergeBaseError(RuntimeError):
    """The commits share no ancestor and the other side holds content, or git could not answer at all."""


def _git(root: Path, *args: str) -> tuple[int, str, str]:
    done = _door.run(['git', '-C', str(root), *args], capture_output=True, check=False, timeout=120)
    return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace').strip()


def _empty(root: Path, rev: str) -> bool:
    code, out, _ = _git(root, 'rev-parse', '--verify', '-q', f'{rev}^{{tree}}')
    return code == 0 and out.strip() == EMPTY_TREE


def merge_bases(root: Path, *commits: str) -> tuple[str, ...]:
    """Every merge base of *commits* (``git merge-base --all``); ``()`` when one side is an EMPTY tree.

    Raises:
        NoMergeBaseError: no common ancestor while every side holds content (the message names :data:`DOOR`),
            or git failed outright.

    """
    code, out, err = _git(root, 'merge-base', '--all', *commits)
    if code == 0:
        return tuple(out.split())
    if code == _NO_COMMON_ANCESTOR and not err:
        if any(_empty(root, c) for c in commits):
            return ()
        shown = ', '.join(c[:12] for c in commits)
        msg = f'{RULE_ID}: {shown} share no ancestor and each holds content, so no range can be judged -- {DOOR}'
        raise NoMergeBaseError(msg)
    msg = f'{RULE_ID}: git merge-base --all {" ".join(commits)} failed: {err}'
    raise NoMergeBaseError(msg)


def range_base(root: Path, base: str, head: str) -> str:
    """What *head*'s range starts from: its (first) merge base with *base*, or :data:`EMPTY_TREE` (module doc)."""
    found = merge_bases(root, base, head)
    return found[0] if found else EMPTY_TREE


def log_range(since: str, head: str) -> list[str]:
    """``git log`` arguments for the commits of *head* after *since*; from the empty tree that is all of them."""
    return [head] if since == EMPTY_TREE else [f'{since}..{head}']
