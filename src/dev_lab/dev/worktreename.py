"""WORKTREE-NAMES-ITS-TASK: a worktree is named for what it does under its task, never by a hash.

User ruling 2026-11-22: a worktree's name must have a physical meaning and be related to its task; an agent
appending a string of hash is strictly forbidden. A tree named ``agent-a1b2c3d4`` tells the next reader nothing:
not what it is for, not whose it is, not whether it may go.

ONE FACT, TWO MECHANISMS, AND THIS MODULE IS THE FACT. :data:`HASH_LIKE_LEAF` is the one spelling of a hash-like
name, in the regex subset JavaScript and Python read identically. The agent deny row of the same ID
(:mod:`dev_lab.dev._deny_worktree_row`) PREVENTS ``git worktree add|move`` to such a name;
:func:`dev_lab.dev.famtests.worktreeplace.assert_every_worktree_names_its_task` DETECTS one that got past it --
a tree a harness made itself (the deny engine reads shell commands only), or one made before the row shipped.

WHAT IS HASH-LIKE, and why it is this narrow: ``agent-<6+ hex>`` (the shape a harness mints), or a name that is,
or ends after ``-``/``_``/``.`` in, six or more hex characters holding BOTH a digit and a letter. A date
(``-20261122``), an issue number (``-123456``) and a word spelled in hex letters (``facade``, ``decade``) carry
meaning and pass; a hash with no letter or no digit (about 4% of 7-character ones) passes too, which is the
price of never refusing a date.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev.worktreeplace import WORKTREES_REL, home, listed_worktrees

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['DOOR', 'HASH_LIKE_LEAF', 'RULE', 'hash_like', 'hash_named', 'remedy']

RULE: Final = 'WORKTREE-NAMES-ITS-TASK'

#: Six or more hex characters with a digit AND a letter among them: a hash, not a date, a number or a word.
_HASH: Final = r'(?=[0-9a-fA-F]*[0-9])(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{6,}'
#: A hash-like worktree directory name, as a regex source with no anchors: the caller anchors both ends.
HASH_LIKE_LEAF: Final = r'(?:[aA][gG][eE][nN][tT]-[0-9a-fA-F]{6,}|(?:[\w.-]*[-_.])?' + _HASH + r')'

#: The door every refusal names: the tree is named for its feature, as its branch already is.
DOOR: Final = (
    f'Name it for what it does under its task: git worktree add -b pr/<task>/<feature> {WORKTREES_REL}/<feature> <sha>'
)

_WHOLE: Final = re.compile(HASH_LIKE_LEAF)


def hash_like(name: str) -> bool:
    """Is *name* a hash-like worktree directory name (:data:`HASH_LIKE_LEAF`)? PURE."""
    return _WHOLE.fullmatch(name) is not None


def hash_named(root: Path) -> tuple[Path, ...]:
    """The linked worktrees of *root*'s repository whose directory name is hash-like; the main checkout is excepted.

    Raises:
        RuntimeError: when git cannot answer (:func:`dev_lab.dev.worktreeplace.listed_worktrees`).

    """
    return tuple(path for path in listed_worktrees(root)[1:] if hash_like(path.name))


def remedy(found: Path, main: Path) -> str:
    """The command that renames *found*, with the name left for whoever knows its task."""
    return f'git -C "{main.as_posix()}" worktree move "{found.as_posix()}" "{home(main).as_posix()}/<feature>"'
