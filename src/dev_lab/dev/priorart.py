"""PRIOR-ART-FIRST, the write half: a NEW product module named like an existing one must cite it.

WHY. New code that duplicates a capability the tree already holds is the cheapest defect to prevent and the
dearest to merge away: two modules of one name in two packages are, more often than not, one concept written
twice by two sessions that never searched. The rule says "search ``src/`` and memory before new code"; this is
the part of it that can say NO -- the moment a NEW ``.py`` file under the product source root is written, every
tracked module there with the same name is its prior art, and the write is refused unless the new file's own
text cites each of them (its path or its dotted module name), saying how it differs or why it is a sibling.

Called by the ``codeplace`` ``PreToolUse`` hook on ``Write``; an EDIT of an existing file is never new code.
Names every package carries by convention (:data:`CONVENTIONAL_STEMS`) are no collision.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev import gitdirs

__all__ = ['CONVENTIONAL_STEMS', 'RULE', 'prior_art', 'refuse_new_module', 'uncited']

#: The rule this refuses for.
RULE: Final = 'PRIOR-ART-FIRST'
#: Module names every package may carry: a package marker, an entry point, a test fixture file.
CONVENTIONAL_STEMS: Final = frozenset({'__init__', '__main__', 'conftest'})
_GIT_TIMEOUT_S: Final = 30


def prior_art(rel: str, tracked: Iterable[str], source_root: str) -> tuple[str, ...]:
    """The tracked modules under *source_root* named like repo-relative POSIX *rel*, sorted; ``()`` if none.

    Only a ``.py`` file under *source_root* whose stem is not conventional is judged at all.
    """
    path = PurePosixPath(rel)
    if path.suffix != '.py' or not rel.startswith(source_root) or path.stem in CONVENTIONAL_STEMS:
        return ()
    return tuple(
        sorted(
            one
            for one in tracked
            if one != rel and one.startswith(source_root) and PurePosixPath(one).name == path.name
        )
    )


def _dotted(rel: str, source_root: str) -> str:
    """``src/pkg/mod.py`` -> ``pkg.mod``: how Python code cites a module."""
    return PurePosixPath(rel[len(source_root) :]).with_suffix('').as_posix().replace('/', '.')


def uncited(found: Iterable[str], text: str, source_root: str) -> tuple[str, ...]:
    """The modules of *found* that *text* names neither by path nor by dotted module name."""
    return tuple(one for one in found if one not in text and _dotted(one, source_root) not in text)


def _tracked(root: Path, source_root: str) -> tuple[str, ...]:
    git = shutil.which('git')
    if git is None:
        return ()
    done = _door.run(
        [git, '-C', str(root), 'ls-files', '-z', '--', source_root],
        capture_output=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    return (
        tuple(filter(None, done.stdout.decode('utf-8', 'surrogateescape').split('\0'))) if not done.returncode else ()
    )


def refuse_new_module(path: Path, content: str, source_root: str) -> str | None:
    """The refusal for writing NEW module *path* with *content*, or ``None`` when it cites every prior art.

    A path that already exists, or that lies in no checkout, is not new code in a tree this can read.
    """
    target = Path(path).resolve()
    if target.exists():
        return None
    root = gitdirs.checkout_of(target.parent)
    if root is None:
        return None
    rel = target.relative_to(root).as_posix()
    missing = uncited(prior_art(rel, _tracked(root, source_root), source_root), content, source_root)
    if not missing:
        return None
    return (
        f'{RULE}: {rel} is a NEW module, and the tree already holds a module of that name: {list(missing)}. '
        f'Read it first: extend it if it is the same concept; if it is not, name the new module for what differs. '
        f'A genuine sibling cites each one in its own docstring (its path or dotted name, and how it differs), '
        f'and is then written.'
    )
