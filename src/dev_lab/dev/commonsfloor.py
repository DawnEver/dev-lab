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

A STALE VENV IS A THIRD CASE (2026-11-22). A ``git pull`` moves a checkout's code and lock ahead of its venv: the
lock already carries the lab-commons the code needs, the venv still holds the older one, and ``from lab_commons
import extras`` dies as a bare ``ImportError: cannot import name``. Relocking is not the door there -- the lock is
right; ``uv sync --frozen`` in the checkout is. :func:`importing` tells the two apart by comparing the installed
lab-commons with the one the checkout's ``uv.lock`` pins, and ``entry=True`` (a ``python -m`` entry point) turns
the refusal into its message on stderr and exit 2 instead of a traceback.

IMPORTS ONLY THE STANDARD LIBRARY, so it loads against any lab-commons.
"""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path

__all__ = ['CommonsBelowFloor', 'heal', 'importing', 'locked_commons']

RULE = 'COMMONS-BELOW-FLOOR'


class CommonsBelowFloor(ImportError):
    """A kit's lab-commons lacks a module this dev-lab imports; the message names the heal."""


def heal(root: Path) -> str:
    """The command that relocks lab-commons into *root*'s own environment, run from a healthy dev-lab kit."""
    return f'<a healthy dev-lab python> -m dev_lab.dev.dep --lock-upgrade {root} --upgrade-package lab-commons'


def locked_commons(checkout: Path) -> str | None:
    """The lab-commons version *checkout*'s ``uv.lock`` pins, or ``None`` when it has no readable lock or pin."""
    try:
        lock = tomllib.loads((checkout / 'uv.lock').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return next((str(row.get('version')) for row in lock.get('package', []) if row.get('name') == 'lab-commons'), None)


def _installed_commons() -> str | None:
    try:
        return metadata.version('lab-commons')
    except metadata.PackageNotFoundError:
        return None


def _own_checkout() -> Path | None:
    """The source checkout this dev-lab runs from (editable install), else ``None`` (a built kit has no lock)."""
    return next((up for up in Path(__file__).resolve().parents if (up / 'uv.lock').is_file()), None)


def _refusal(name: str, root: Path | None) -> str:
    checkout, installed = _own_checkout(), _installed_commons()
    locked = locked_commons(checkout) if checkout else None
    if locked and installed != locked:
        return (
            f"{RULE}: {checkout}'s venv holds lab_commons {installed}, older than its code needs ({name} missing; "
            f'its uv.lock pins {locked}): run `uv sync --frozen` in {checkout}, then this again'
        )
    return (
        f'{RULE}: this kit ({sys.executable}) has a lab-commons without {name}, which this dev-lab imports: its '
        f"lock moved dev-lab without lab-commons. Heal it from another checkout's dev-lab interpreter:\n"
        f'{heal(root or Path.cwd())}'
    )


@contextmanager
def importing(root: Path | None = None, *, entry: bool = False) -> Iterator[None]:
    """Run imports; a lab_commons module or name missing is re-raised as :class:`CommonsBelowFloor` naming its door.

    With *entry* (the module runs as ``__main__``) the refusal is printed and the process exits 2, no traceback.
    """
    try:
        yield
    except ImportError as missing:
        name = missing.name or ''
        if name != 'lab_commons' and not name.startswith('lab_commons.'):
            raise
        what = name if isinstance(missing, ModuleNotFoundError) else f'{name} ({missing})'
        msg = _refusal(what, root)
        if entry:
            # lab_commons (and so its emit) is what is below the floor here: the bytes go to fd 2 in UTF-8, chosen here
            os.write(2, f'{msg}\n'.encode())
            raise SystemExit(2) from missing
        raise CommonsBelowFloor(msg, name=name) from missing
