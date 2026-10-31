"""The family's `.claude/rem.json`: the rem plugin reads it, and every repo's backlog is its issue tracker.

User ruling 2026-10-31 (the four-layer memory plan): a repo's backlog lives in the forge's issues, so rem's
``todo`` is a read-only view and never a second store. The file is family policy, authored here once and
written into each repo by ``hook_install --install`` beside the principles page.

GENERATED ONLY WHEN ABSENT OR IDENTICAL. An existing ``.claude/rem.json`` that differs is a repo's deliberate
choice: :func:`write` never clobbers it -- it raises :class:`RemConfigConflictError` naming both texts, and
``hook_install --install`` reports it and exits non-zero. Whoever owns that choice reconciles it by hand.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['CONFIG', 'REL', 'RemConfigConflictError', 'render', 'write']

REL: Final = '.claude/rem.json'
CONFIG: Final = {'backlog': 'issues'}


class RemConfigConflictError(RuntimeError):
    """The repo's committed rem.json differs from the family render; nothing was written."""


def render() -> str:
    """The committed text of :data:`REL`."""
    return json.dumps(CONFIG) + '\n'


def write(repo: Path) -> bool:
    """Write :data:`REL` under *repo* when absent; whether it wrote. A differing file is refused, never overwritten."""
    path = repo / REL
    text = render()
    if path.is_file():
        held = path.read_text(encoding='utf-8')
        if held == text:
            return False
        msg = f'{path} holds {held.strip()!r}, not the family {text.strip()!r}; left untouched -- reconcile it by hand'
        raise RemConfigConflictError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    return True
