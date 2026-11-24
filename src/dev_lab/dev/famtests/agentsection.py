"""AGENTS-SECTION-IS-RENDERED, as the body every consumer runs: the family section of AGENTS.md is the render.

The section between the markers is family policy (:mod:`dev_lab.dev.agentsection`); a hand edit inside it, a
stale copy after the principles or the workflow rules moved, or no section at all reds here with the remedy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.agentsection import AGENTS_REL, held_section, render_section
from dev_lab.dev.famfiles import RENDER_COMMAND

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_agents_section_is_rendered']


def assert_agents_section_is_rendered(*, root: Path) -> None:
    """*root*'s AGENTS.md holds exactly :func:`~dev_lab.dev.agentsection.render_section` between its markers."""
    path = root / AGENTS_REL
    if not path.is_file():
        msg = f'no {AGENTS_REL} in {root}: the one agent entry is missing. Write it, then: {RENDER_COMMAND}'
        raise AssertionError(msg)
    try:
        held = held_section(path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise AssertionError(str(exc)) from exc
    if held is None:
        msg = f'{path} holds no dev-lab family section: the family rules reach no agent here. {RENDER_COMMAND}'
        raise AssertionError(msg)
    if held != render_section():
        msg = f'{path}: the family section was hand-edited or is stale; edit the source, re-render: {RENDER_COMMAND}'
        raise AssertionError(msg)
