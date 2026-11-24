"""WHAT THE STOP DOOR RECOGNIZES: the built-in run signatures, a repo's declared ones, and proven orphans.

Split from :mod:`dev_lab.dev.stoprun` (2026-11-15, module-size band). The declarations are DATA in the
repo's ``pyproject.toml`` (``[tool.dev_lab.stoprun] signatures`` / ``orphans``); a value that is not a
list of valid regex strings raises :class:`SignaturesNotDeclared`. An orphaned multiprocessing worker
is PROVEN from the table (:func:`orphaned_worker`), never recognized from its command line's shape.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, Final

from lab_commons.liveness import CreationClock, creation_stamp

from dev_lab.dev.family import declared_table
from dev_lab.dev.liverun import SPAWN_WORKER, WATCH

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from dev_lab.dev.proctable import Proc

__all__ = [
    'BUILTIN_ORPHANS',
    'RUN_SIGNATURES',
    'SCRATCH',
    'SERVE',
    'TABLE',
    'SignaturesNotDeclared',
    'declared_orphans',
    'declared_signatures',
    'declared_spares',
    'identify',
    'orphan_role',
    'orphaned_worker',
    'why_stoppable',
]

TABLE = '[tool.dev_lab.stoprun]'

#: A ``forge serve``: stopped producers first, then given a grace to release its claim.
SERVE: Final = re.compile(r'-m\s+dev_lab.dev\.forge\s+serve\b')

#: A command line that is one of these is a run this door may stop. Anything else is refused.
RUN_SIGNATURES: Final = (
    re.compile(r'-m\s+dev_lab.dev\.verify\b'),
    re.compile(r'scripts[/\\]gate[/\\]runner\.py\b'),
    re.compile(r'-m\s+pytest\b'),
    re.compile(r'(?:^|[/\\\s])pytest(?:\.exe)?(?:\s|$)'),
    # A PUSH MUST NEVER BLOCK: a pre-push hook that hangs is a run this door must be able to stop.
    re.compile(r'dev_lab.dev\.githooks run pre-push\b'),
    re.compile(r'scripts[/\\]gate[/\\]prepush_gate\.py\b'),
    # ...and the retry wrapper around it is what the agent holds: one network verb, never anything else (2026-11-13).
    re.compile(r'(?:^|[/\\\s])with-retry\.sh\s+(?:push|fetch|pull|clone|ls-remote)\b'),
    SERVE,
    WATCH,  # its owner's reader, stopped to free its venv and re-armed (liverun.env_in_use)
)

#: A one-off under a ``scratch/`` directory (the family's home for probes): an orphan of one is stoppable.
SCRATCH: Final = re.compile(r'(?:^|[\s"\'=/\\])scratch[/\\]')

#: The orphan signatures every repo has: a ``scratch/`` one-off, and a multiprocessing spawn/forkserver
#: worker -- liverun's own rule (:data:`dev_lab.dev.liverun.SPAWN_WORKER`), so the two doors never disagree.
BUILTIN_ORPHANS: Final = (SCRATCH, SPAWN_WORKER)

#: A multiprocessing worker's own statement of the process it serves.
_WORKER_PARENT: Final = re.compile(r'\bspawn_main\(parent_pid=(\d+)')


class SignaturesNotDeclared(ValueError):
    """``[tool.dev_lab.stoprun] signatures`` is not a list of valid regex strings."""


def declared_signatures(root: Path) -> tuple[str, ...]:
    """The extra signatures *root*'s ``pyproject.toml`` declares; ``()`` when it declares none.

    Raises:
        SignaturesNotDeclared: the manifest is unreadable, or the value is not a list of regex strings.

    """
    return _declared(root, 'signatures')


def declared_orphans(root: Path) -> tuple[str, ...]:
    """The vendor tools *root* declares stoppable once ORPHANED (``orphans``); ``()`` when none.

    Raises:
        SignaturesNotDeclared: the manifest is unreadable, or the value is not a list of regex strings.

    """
    return _declared(root, 'orphans')


def declared_spares(root: Path) -> tuple[str, ...]:
    """The runs *root* declares the shell reaper never stops, at any age (``spare``); ``()`` when none.

    Raises:
        SignaturesNotDeclared: the manifest is unreadable, or the value is not a list of regex strings.

    """
    return _declared(root, 'spare')


def _declared(root: Path, key: str) -> tuple[str, ...]:
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    try:
        data = tomllib.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f'{manifest} is not a readable TOML manifest: {exc}'
        raise SignaturesNotDeclared(msg) from exc
    table = declared_table(data, 'stoprun')
    if table is None:
        return ()
    value = table.get(key, []) if isinstance(table, dict) else table
    if not isinstance(value, list) or not all(isinstance(s, str) and s for s in value):
        msg = f'{TABLE} {key} in {manifest} is {value!r}; it must be a list of regex strings'
        raise SignaturesNotDeclared(msg)
    for sig in value:
        try:
            re.compile(sig)
        except re.error as exc:
            msg = f'{TABLE} signature {sig!r} in {manifest} is not a regex: {exc}'
            raise SignaturesNotDeclared(msg) from exc
    return tuple(value)


def identify(cmdline: str, signatures: tuple[str, ...] = ()) -> str | None:
    """The signature *cmdline* matches (built-in first, then declared), or ``None``."""
    for sig in (*RUN_SIGNATURES, *(re.compile(s) for s in signatures)):
        if sig.search(cmdline):
            return sig.pattern
    return None


def orphaned_worker(table: Mapping[int, Proc], pid: int, born: CreationClock = creation_stamp) -> int | None:
    """The parent pid *pid* names and has lost, or ``None`` when it is no orphaned worker.

    Lost means absent from *table*, or present but provably created AFTER *pid* (a reused pid); an
    unreadable creation stamp proves nothing, so the worker stays refused.
    """
    named = _WORKER_PARENT.search(table[pid][1]) if pid in table else None
    if named is None:
        return None
    parent = int(named.group(1))
    if parent not in table:
        return parent
    theirs, mine = born(parent), born(pid)
    return parent if theirs is not None and mine is not None and theirs > mine else None


def why_stoppable(table: Mapping[int, Proc], pid: int, signatures: tuple[str, ...], born: CreationClock) -> str | None:
    """What makes *pid* stoppable: the signature it matches, or the parent it names and has lost."""
    matched = identify(table[pid][1], signatures)
    if matched is None and (lost := orphaned_worker(table, pid, born)) is not None:
        return f'orphaned worker of {lost}'
    return matched


def orphan_role(command: str, orphans: tuple[str, ...]) -> bool:
    """The existing declared orphan roles, shared by ordinary and approved policy checks."""
    return any(sig.search(command) for sig in (*BUILTIN_ORPHANS, *(re.compile(s) for s in orphans)))
