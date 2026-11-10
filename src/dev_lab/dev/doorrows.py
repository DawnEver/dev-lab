"""The permission rows a door renders: one LITERAL interpreter row per platform layout, never a glob.

Split out of :mod:`dev_lab.dev.agentpolicy` (2026-11-10, MODULE-SIZE-ALARM): the table says WHICH doors exist;
this module says how one door's argv is SPELLED as a ``permissions.allow`` row, which the allow adoption also
needs for rows that are not doors.
"""

from __future__ import annotations

from typing import Final

from dev_lab.dev.venvpath import VENV_INTERPRETER_GLOB, VENV_LAYOUTS

__all__ = ['INTERPRETERS', 'allow_rows', 'literal_rows']

#: The checkout's own interpreter, one LITERAL per platform layout -- the only interpreter spelling a door row
#: carries. NOT :data:`dev_lab.dev.venvpath.VENV_INTERPRETER_GLOB` (``.venv/*/python*``): in a permission glob
#: the ``*`` after ``python`` also matches ``.exe -c <code>``, so ``.venv/*/python* -m <door> *`` admits
#: arbitrary code run AHEAD of the door (measured 2026-11-07, ``fnmatch``). Two literal rows admit only the door.
INTERPRETERS: Final = tuple('/'.join(VENV_LAYOUTS[name]) for name in sorted(VENV_LAYOUTS))


def literal_rows(entry: str) -> tuple[str, ...]:
    """*entry* with the interpreter glob rendered as one row per :data:`INTERPRETERS`; else *entry* alone."""
    if VENV_INTERPRETER_GLOB not in entry:
        return (entry,)
    return tuple(entry.replace(VENV_INTERPRETER_GLOB, head) for head in INTERPRETERS)


def allow_rows(argv: tuple[str, ...]) -> tuple[str, ...]:
    """The ``permissions.allow`` rows of a door *argv*: per interpreter layout; a git door also as ``git -C *``."""
    runner, *rest = argv
    tail = ' '.join(rest)
    if runner == 'python':
        return tuple(f'Bash({head} {tail} *)' for head in INTERPRETERS)
    if runner == 'git':
        return (f'Bash(git {tail} *)', f'Bash(git -C * {tail} *)')
    return (f'Bash({runner} {tail} *)',)
