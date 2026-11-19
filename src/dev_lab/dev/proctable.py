"""THE PROCESS TABLE THE STOP DOORS READ: ``{pid: (ppid, command line)}`` and its tree walks.

Split from :mod:`dev_lab.dev.stoprun` (2026-11-15, module-size band): the table, a subtree children
first, the ancestor chain, whose session a pid descends from, and the pids no door may ever stop.
Both the recognised-run door and the approved-controller door (:mod:`dev_lab.dev.stopapproved`) read it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Final

from lab_commons.census import processes

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['INIT', 'Proc', 'ancestors', 'chain', 'process_table', 'subtree', 'unstoppable', 'whose']

#: The pid POSIX reparents an orphan to; a ppid at or below it names no live creator.
INIT: Final = 1

Proc = tuple[int, str]  # (parent pid, command line)


def process_table() -> dict[int, Proc]:
    """``{pid: (ppid, cmdline)}`` for every process, from the one census (:mod:`lab_commons.census`)."""
    return {one.pid: (one.ppid, one.command_line) for one in processes()}


def subtree(table: Mapping[int, Proc], pid: int) -> list[int]:
    """*pid* and every descendant, deepest first (children are stopped before their parent)."""
    order: list[int] = []
    frontier = [pid]
    while frontier:
        current = frontier.pop()
        order.append(current)
        frontier += [p for p, (ppid, *_) in table.items() if ppid == current and p != current and p not in order]
    return order[::-1]


def ancestors(table: Mapping[int, Proc], pid: int) -> set[int]:
    """*pid* and every ancestor the table names (a cycle or an absent parent ends it)."""
    seen: set[int] = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        pid = table[pid][0]
    return seen


def whose(table: Mapping[int, Proc], pid: int, me: int) -> str:
    """Whether *pid* descends from this session: the nearest ancestor it shares with *me* below the tree's root."""
    mine = [*chain(table, me)][:-1]  # the topmost process is everyone's root, never a session
    for ancestor in chain(table, pid):
        if ancestor in mine:
            return f'started from this session (shares ancestor {ancestor}: {table[ancestor][1][:80]!r})'
    return 'not started from this session (no ancestor in common with it)'


def chain(table: Mapping[int, Proc], pid: int) -> list[int]:
    """*pid*, its parent, and so on up the table (cycles and absent parents end it)."""
    seen: list[int] = []
    while pid in table and pid not in seen and pid > INIT:
        seen.append(pid)
        pid = table[pid][0]
    return seen


def unstoppable(pid: int, table: Mapping[int, Proc]) -> str | None:
    """Why *pid* may never be stopped from here whatever it runs -- this process, gone, or an ancestor."""
    if pid in (os.getpid(), os.getppid()):
        return f'{pid} is this process or its parent'
    if pid not in table:
        return f'no process {pid}'
    if pid in ancestors(table, os.getpid()):
        return f'{pid} is an ancestor of this process'
    return None
