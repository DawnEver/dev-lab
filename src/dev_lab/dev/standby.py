"""STANDBY-IS-RESTING (v1 ruling D218, 2026-11-28): a session's posted standby is a valid resting state.

A long-lived session that is blocked, or whose queue is empty, posts ``standby: <cause> -- waiting on <whom>`` on
its task issue and stops. A Stop hook that reads that stop as unfinished work pushes the session to invent work or
loop. So the family forge door records a standby comment it posts for this session (:func:`dev_lab.dev.walls.standby`),
and the ``walls stop`` hook lets a session stop while its latest standby is newer than its checkout's last commit.

:data:`MARKER` is the ONE spelling lanes and hooks share: a comment line that starts with it is a standby.
"""

from __future__ import annotations

from typing import Final

__all__ = ['MARKER', 'RULE', 'posted']

RULE: Final = 'STANDBY-IS-RESTING'
#: The family standby marker: a comment line starting with it (after indentation) declares the session at rest.
MARKER: Final = 'standby:'


def posted(body: str) -> bool:
    """Whether comment *body* declares a standby: one of its lines starts with :data:`MARKER`."""
    return any(line.lstrip().startswith(MARKER) for line in body.splitlines())
