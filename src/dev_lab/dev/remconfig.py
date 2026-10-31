"""The family's `.claude/rem.json`: the rem plugin reads it, and every repo's backlog is its issue tracker.

User ruling 2026-10-31 (the four-layer memory plan): a repo's backlog lives in the forge's issues, so rem's
``todo`` is a read-only view and never a second store. The file is family policy, authored here once and
written into each repo by ``hook_install --install`` beside the principles page.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['CONFIG', 'REL', 'render', 'write']

REL: Final = '.claude/rem.json'
CONFIG: Final = {'backlog': 'issues'}


def render() -> str:
    """The committed text of :data:`REL`."""
    return json.dumps(CONFIG) + '\n'


def write(repo: Path) -> bool:
    """Write :data:`REL` under *repo* when it differs from :func:`render`; whether it wrote."""
    path = repo / REL
    text = render()
    if path.is_file() and path.read_text(encoding='utf-8') == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    return True
