"""The family's `.claude/rem.json`: the rem plugin reads it, and every repo's backlog is its issue tracker.

User ruling 2026-10-31 (the four-layer memory plan): a repo's backlog lives in the forge's issues, so rem's
``todo`` is a read-only view and never a second store. The file is family policy, authored here once and
written into each repo by :mod:`dev_lab.dev.famfiles` beside the principles page.

GENERATED ONLY WHEN ABSENT OR IDENTICAL. An existing ``.claude/rem.json`` that differs is a repo's deliberate
choice: :func:`dev_lab.dev.famfiles.render_agent_files` never clobbers it, reports it and exits non-zero.
Whoever owns that choice reconciles it by hand.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    pass

__all__ = ['CONFIG', 'REL', 'render']

REL: Final = '.claude/rem.json'
CONFIG: Final = {'backlog': 'issues'}


def render() -> str:
    """The committed text of :data:`REL`."""
    return json.dumps(CONFIG) + '\n'
