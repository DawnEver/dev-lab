"""Run recognition, declared orphan roles and process-tree safety policy. No process stopping."""

from __future__ import annotations

import os
import re
import sqlite3
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from lab_commons.liveness import CreationClock, creation_stamp

from dev_lab.dev.family import declared_table
from dev_lab.dev.liverun import SPAWN_WORKER, WATCH

__all__ = [
    'BUILTIN_ORPHANS',
    'RUN_SIGNATURES',
    'SCRATCH',
    'SERVE',
    'Proc',
    'SignaturesNotDeclared',
    'declared_orphans',
    'declared_signatures',
    'identify',
    'never',
    'ordinary_lifecycle_door',
    'orphan_refusal',
    'orphan_role',
    'orphaned_worker',
    'refusal',
    'subtree',
    'whose',
    'why_stoppable',
]

_TABLE = '[tool.dev_lab.stoprun]'


SERVE: Final = re.compile(r'-m\s+dev_lab.dev\.forge\s+serve\b')


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


SCRATCH: Final = re.compile(r'(?:^|[\s"\'=/\\])scratch[/\\]')


BUILTIN_ORPHANS: Final = (SCRATCH, SPAWN_WORKER)


_INIT: Final = 1


Proc = tuple[int, str]  # (parent pid, command line)


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
        msg = f'{_TABLE} {key} in {manifest} is {value!r}; it must be a list of regex strings'
        raise SignaturesNotDeclared(msg)
    for sig in value:
        try:
            re.compile(sig)
        except re.error as exc:
            msg = f'{_TABLE} signature {sig!r} in {manifest} is not a regex: {exc}'
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


def subtree(table: Mapping[int, Proc], pid: int) -> list[int]:
    """*pid* and every descendant, deepest first (children are stopped before their parent)."""
    order: list[int] = []
    frontier = [pid]
    while frontier:
        current = frontier.pop()
        order.append(current)
        frontier += [p for p, (ppid, *_) in table.items() if ppid == current and p != current and p not in order]
    return order[::-1]


def _ancestors(table: Mapping[int, Proc], pid: int) -> set[int]:
    seen: set[int] = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        pid = table[pid][0]
    return seen


def orphan_role(command: str, orphans: tuple[str, ...]) -> bool:
    """The existing declared orphan roles, shared by ordinary and approved policy checks."""
    return any(sig.search(command) for sig in (*BUILTIN_ORPHANS, *(re.compile(s) for s in orphans)))


def ordinary_lifecycle_door(pid: int) -> str:
    """The existing run lifecycle, never an authorization to bypass it with approved identity."""
    return (
        f'{pid} has an existing lifecycle; use the ordinary '
        f'python -m dev_lab.dev.stoprun --pid {pid} without approved arguments'
    )


def orphan_refusal(
    pid: int,
    table: Mapping[int, Proc],
    orphans: tuple[str, ...],
    claimed: Callable[[], set[int]],
    born: CreationClock,
) -> str | None:
    """Why *pid* is NOT a stoppable orphan, or ``None`` when it is (the module docstring's three conditions)."""
    cmdline = table[pid][1]
    if not orphan_role(cmdline, orphans):
        builtin = ', '.join(repr(sig.pattern) for sig in BUILTIN_ORPHANS)
        return f'no orphan signature either (built-in {builtin} or {_TABLE} orphans)'
    ppid = table[pid][0]
    if ppid > _INIT and ppid in table:  # POSIX reparents an orphan to init: its parent is gone
        parent, child = born(ppid), born(pid)
        if parent is None or child is None or parent <= child:
            return f'its parent {ppid} is alive ({table[ppid][1][:120]!r}) -- stop that run instead'
    try:
        held = claimed() & set(subtree(table, pid))
    except (OSError, sqlite3.Error) as exc:
        return f'the box ledger could not be read, so a claim cannot be ruled out: {exc}'
    if held:
        return f'{sorted(held)} holds a box claim -- release it through the door that took it'
    return None


EXIT: Final = (
    'exit: ask the user to stop it, or -- when it is a run of this repo -- declare its command line as a regex in '
    '`{table} signatures = [...]` of {manifest}'
)


def whose(table: Mapping[int, Proc], pid: int, me: int) -> str:
    """Whether *pid* descends from this session: the nearest ancestor it shares with *me* below the tree's root."""
    mine = [*_chain(table, me)][:-1]  # the topmost process is everyone's root, never a session
    for ancestor in _chain(table, pid):
        if ancestor in mine:
            return f'started from this session (shares ancestor {ancestor}: {table[ancestor][1][:80]!r})'
    return 'not started from this session (no ancestor in common with it)'


def _chain(table: Mapping[int, Proc], pid: int) -> list[int]:
    """*pid*, its parent, and so on up the table (cycles and absent parents end it)."""
    seen: list[int] = []
    while pid in table and pid not in seen and pid > _INIT:
        seen.append(pid)
        pid = table[pid][0]
    return seen


def refusal(table: Mapping[int, Proc], pid: int, why: str, me: int, manifest: str) -> list[str]:
    """The refusal of *pid*: what it is, who started it, whose it is, and the exit."""
    ppid = table[pid][0]
    parent = f'{ppid} {table[ppid][1][:120]!r}' if ppid in table else f'{ppid} (gone)'
    return [
        f'refused: {pid} matches no run signature (built-in or {_TABLE}) and {why}',
        f'what: {table[pid][1][:200]!r}',
        f'parent: {parent}',
        f'whose: {whose(table, pid, me)}',
        EXIT.format(table=_TABLE, manifest=manifest),
    ]


def never(pid: int, table: Mapping[int, Proc]) -> str | None:
    """Why *pid* may never be stopped from here whatever it runs -- this process, gone, or an ancestor."""
    if pid in (os.getpid(), os.getppid()):
        return f'{pid} is this process or its parent'
    if pid not in table:
        return f'no process {pid}'
    if pid in _ancestors(table, os.getpid()):
        return f'{pid} is an ancestor of this process'
    return None
