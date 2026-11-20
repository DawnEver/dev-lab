"""COMMONS-BELOW-FLOOR: a kit whose lab-commons lacks a module dev-lab imports is refused by name, with its heal.

THE INCIDENT (2026-11-20). dev-lab 5e4e0334 imports ``lab_commons.storage`` at load. A consumer relocked dev-lab
alone (``--upgrade-package dev-lab``) while dev-lab's declared floor on lab-commons predated that module, so the lock
kept an older lab-commons and the frozen sync built a kit whose own dependency door died on a bare ``ImportError``
-- the one door that relocks lab-commons could not run to heal it.

TWO HALVES. The CAUSE is closed in ``pyproject.toml``: dev-lab's lab-commons floor names the first lab-commons
carrying every module it imports, so a lock that moves dev-lab must move lab-commons with it. THIS module is the
WALL for a kit that is already mismatched: :func:`importing` turns the missing ``lab_commons`` submodule into
:class:`CommonsBelowFloor`, whose message names the heal -- the same door run from ANY healthy dev-lab interpreter
(another checkout's), which relocks lab-commons into this checkout's own environment.

IMPORTS ONLY THE STANDARD LIBRARY, so it loads against any lab-commons.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = ['CommonsBelowFloor', 'heal', 'importing']

RULE = 'COMMONS-BELOW-FLOOR'


class CommonsBelowFloor(ImportError):
    """A kit's lab-commons lacks a module this dev-lab imports; the message names the heal."""


def heal(root: Path) -> str:
    """The command that relocks lab-commons into *root*'s own environment, run from a healthy dev-lab kit."""
    return f'<a healthy dev-lab python> -m dev_lab.dev.dep --lock-upgrade {root} --upgrade-package lab-commons'


@contextmanager
def importing(root: Path | None = None) -> Iterator[None]:
    """Run imports; a missing ``lab_commons.*`` module is re-raised as :class:`CommonsBelowFloor` naming its heal."""
    try:
        yield
    except ModuleNotFoundError as missing:
        name = missing.name or ''
        if not name.startswith('lab_commons.'):
            raise
        where = root or Path.cwd()
        msg = (
            f'{RULE}: this kit ({sys.executable}) has a lab-commons without {name}, which this dev-lab imports: its '
            f"lock moved dev-lab without lab-commons. Heal it from another checkout's dev-lab interpreter:\n"
            f'{heal(where)}'
        )
        raise CommonsBelowFloor(msg, name=name) from missing
