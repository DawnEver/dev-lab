"""DECLARED-LAYOUT, as the assertion every consumer's architecture suite runs over its own checkout.

The repo-shaped facts arrive as arguments with no default: *root*, and the FLOOR on the top-level directories
the walk read (FLOOR-ON-EVERY-SCAN) with its headroom -- a walk of an empty or wrong root reads nothing and
would otherwise report it clean. The table, the predicate and the refusal text are :mod:`dev_lab.dev.layout`'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev import floors
from dev_lab.dev.layout import RULE_ID, declared_layout, layout_violations

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_layout_holds']


def assert_layout_holds(*, root: Path, floor: int, headroom: int) -> None:
    """Every top-level directory of *root* is declared, and no file sits under a directory forbidding its suffix.

    Raises:
        dev_lab.dev.layout.LayoutNotDeclared: *root* declares no ``[layout]`` in ``layout.toml``.
        dev_lab.dev.floors.FloorUnmet: the walk read fewer top-level directories than *floor*.
        dev_lab.dev.floors.SlackFloor: the floor has been outgrown past *headroom*.
        AssertionError: a violation, every one named.

    """
    read, found = layout_violations(root, declared_layout(root))
    what = f'{RULE_ID} top-level directory'
    floors.assert_floor(read, floor=floor, what=what)
    floors.assert_floor_still_binds(read, floor=floor, headroom=headroom, what=what)
    if found:
        listed = '\n'.join(f'  {one}' for one in found)
        msg = (
            f'{len(found)} {RULE_ID} violation(s) in {root.as_posix()}. Move each file to its home, or declare '
            f'its own row in [layout] of layout.toml in a reviewed commit:\n{listed}'
        )
        raise AssertionError(msg)
