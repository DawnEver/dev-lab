"""THE COMMITTED PRINCIPLES PAGE IS THE RENDER -- a repo's ``.claude/rules/principles.md`` cannot drift.

The page is family policy, authored once in :data:`dev_lab.dev.principles.PRINCIPLES` and written into
each repo by ``hook_install --install``. A hand edit, a stale copy after the tuple grew, or no page at all
reds here, naming the one remedy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.hook_install import INSTALL_COMMAND
from dev_lab.dev.principles import PAGE_REL, render

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_principles_page_is_rendered']


def assert_principles_page_is_rendered(*, root: Path) -> None:
    """*root*'s committed :data:`~dev_lab.dev.principles.PAGE_REL` equals :func:`~dev_lab.dev.principles.render`."""
    page = root / PAGE_REL
    if not page.is_file():
        msg = f'no {PAGE_REL} in {root}: the family principles reach no agent here. Write it: {INSTALL_COMMAND}'
        raise AssertionError(msg)
    if page.read_text(encoding='utf-8') != render():
        msg = f'{page} has drifted from dev_lab.dev.principles.render(); re-render it: {INSTALL_COMMAND}'
        raise AssertionError(msg)
