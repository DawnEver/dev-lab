"""STOP ONE OWN RUN: ``python -m dev_lab.dev.stoprun --pid PID [--repo PATH] [--dry-run]``.

Generalised 2026-10-04 from a consumer's process-tree killer (its ``--pid`` mode) (AUTO-MODE-RUNS-THE-DOORS):
an agent stopping its OWN superseded run was refused as a raw ``taskkill /T /F``. The door replaces the
raw kill with a checked one: it REFUSES unless the pid's command line is a run it can identify
(:data:`RUN_SIGNATURES` -- the family verify, a gate runner, pytest, a ``forge serve`` -- plus any the repo
declares), and then stops that pid's subtree only, children first, never an ancestor or a sibling. Local only.

A ``forge serve`` IS STOPPED SO ITS CLAIM IS RELEASED: its producers are noted as stopped on purpose
(:func:`dev_lab.dev.servelock.note_stopped`) and stopped first, then the serve itself is given
:data:`SERVE_GRACE_S` to release the claim as ``error: stopped`` and exit before it is killed too.

A repo adds its own signatures as DATA, in ONE place -- its ``pyproject.toml`` (the repo of the cwd,
or ``--repo``)::

    [tool.lab_commons.stoprun]
    signatures = ["jcwrap"]   # regexes searched in the pid's own command line, like the built-ins

A declaration that is not a list of valid regex strings raises :class:`SignaturesNotDeclared`.

AN ORPHAN IS STOPPABLE TOO, BY THREE CONDITIONS THAT MUST ALL HOLD (added 2026-10-21: two orphaned JMAG
Designers, a node-side ``JobSystem.exe -s`` and a leftover ``scratch/`` shell watcher matched no run
signature, RAW-PROCESS-KILL forbade ``taskkill``, and the memory they held kept a box from admitting a solve):

* its PARENT IS GONE -- the ppid is absent, is init (POSIX reparents an orphan to pid 1), or is a younger
  process wearing the recycled number;
* NO BOX CLAIM is held by it or a descendant (:func:`lab_commons.box.ledger.holdings`; a Designer a claim
  was handed over to is that claim's, and is released through its own door). An unreadable ledger refuses;
* its command line is a DECLARED vendor tool or a ``scratch/`` script (:data:`SCRATCH`, built in)::

      [tool.lab_commons.stoprun]
      orphans = ["designer.exe.* --process-link", "JobSystem.exe -s "]

A refusal names the condition that failed -- a live parent is named, so the run it belongs to is stopped instead.
``--dry-run`` names the signature that matched.

No new dependency: the process table is :func:`lab_commons.census.processes` (Win32 calls on Windows,
``/proc`` on Linux, ``ps -ww`` on macOS) -- the one census :mod:`dev_lab.dev.liverun` reads too;
:func:`stop` takes the table as an argument so a test can plant one.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import signal
import sqlite3
import sys
import time
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.box.ledger import holdings
from lab_commons.census import processes
from lab_commons.liveness import CreationClock, creation_stamp
from lab_commons.log import emit
from lab_commons.proc import pid_alive

from dev_lab.dev.checkout import git_out
from dev_lab.dev.servelock import note_stopped

__all__ = [
    'RUN_SIGNATURES',
    'SCRATCH',
    'SERVE',
    'SERVE_GRACE_S',
    'Proc',
    'SignaturesNotDeclared',
    'declared_orphans',
    'declared_signatures',
    'identify',
    'main',
    'process_table',
    'repo_root',
    'stop',
    'subtree',
]

_TABLE = '[tool.lab_commons.stoprun]'

#: A ``forge serve``: stopped producers first, then given a grace to release its claim.
SERVE: Final = re.compile(r'-m\s+dev_lab.dev\.forge\s+serve\b')

#: How long a serve whose producers were stopped may take to release its claim and exit, in seconds.
SERVE_GRACE_S: Final = 60.0

#: A command line that is one of these is a run this door may stop. Anything else is refused.
RUN_SIGNATURES: Final = (
    re.compile(r'-m\s+dev_lab.dev\.verify\b'),
    re.compile(r'scripts[/\\]gate[/\\]runner\.py\b'),
    re.compile(r'-m\s+pytest\b'),
    re.compile(r'(?:^|[/\\\s])pytest(?:\.exe)?(?:\s|$)'),
    # A PUSH MUST NEVER BLOCK: a pre-push hook that hangs is a run this door must be able to stop.
    re.compile(r'dev_lab.dev\.githooks run pre-push\b'),
    re.compile(r'scripts[/\\]gate[/\\]prepush_gate\.py\b'),
    SERVE,
)

#: A one-off under a ``scratch/`` directory (the family's home for probes): an orphan of one is stoppable.
SCRATCH: Final = re.compile(r'(?:^|[\s"\'=/\\])scratch[/\\]')

#: The pid POSIX reparents an orphan to; a ppid at or below it names no live creator.
_INIT: Final = 1

Proc = tuple[int, str]  # (parent pid, command line)


def process_table() -> dict[int, Proc]:
    """``{pid: (ppid, cmdline)}`` for every process, from the one census (:mod:`lab_commons.census`)."""
    return {one.pid: (one.ppid, one.command_line) for one in processes()}


class SignaturesNotDeclared(ValueError):
    """``[tool.lab_commons.stoprun] signatures`` is not a list of valid regex strings."""


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
    table = data.get('tool', {}).get('lab_commons', {}).get('stoprun')
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


def repo_root(start: Path) -> Path:
    """The git top level containing *start*, else *start* itself."""
    top = git_out(start, 'rev-parse', '--show-toplevel')
    return Path(top.strip()) if top and top.strip() else start


def identify(cmdline: str, signatures: tuple[str, ...] = ()) -> str | None:
    """The signature *cmdline* matches (built-in first, then declared), or ``None``."""
    for sig in (*RUN_SIGNATURES, *(re.compile(s) for s in signatures)):
        if sig.search(cmdline):
            return sig.pattern
    return None


def subtree(table: Mapping[int, Proc], pid: int) -> list[int]:
    """*pid* and every descendant, deepest first (children are stopped before their parent)."""
    order: list[int] = []
    frontier = [pid]
    while frontier:
        current = frontier.pop()
        order.append(current)
        frontier += [p for p, (ppid, _) in table.items() if ppid == current and p != current and p not in order]
    return order[::-1]


def _ancestors(table: Mapping[int, Proc], pid: int) -> set[int]:
    seen: set[int] = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        pid = table[pid][0]
    return seen


def _claimed() -> set[int]:
    """The pids holding a claim in this machine's box ledger now."""
    return {held.pid for held in holdings()}


def _orphan_refusal(
    pid: int,
    table: Mapping[int, Proc],
    orphans: tuple[str, ...],
    claimed: Callable[[], set[int]],
    born: CreationClock,
) -> str | None:
    """Why *pid* is NOT a stoppable orphan, or ``None`` when it is (the module docstring's three conditions)."""
    cmdline = table[pid][1]
    if not any(sig.search(cmdline) for sig in (SCRATCH, *(re.compile(s) for s in orphans))):
        return f'no orphan signature either (built-in {SCRATCH.pattern!r} or {_TABLE} orphans)'
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


def _kill(pid: int) -> None:
    if os.name == 'nt':
        _door.run(
            [shutil.which('taskkill') or 'taskkill', '/PID', str(pid), '/F'],
            capture_output=True,
            check=False,
            timeout=60,
        )
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)


def _gone(pid: int, seconds: float) -> bool:
    """Whether *pid* exits within *seconds*."""
    deadline = time.monotonic() + seconds
    while pid_alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)
    return True


def _never(pid: int, table: Mapping[int, Proc]) -> str | None:
    """Why *pid* may never be stopped from here whatever it runs -- this process, gone, or an ancestor."""
    if pid in (os.getpid(), os.getppid()):
        return f'{pid} is this process or its parent'
    if pid not in table:
        return f'no process {pid}'
    if pid in _ancestors(table, os.getpid()):
        return f'{pid} is an ancestor of this process'
    return None


def stop(
    pid: int,
    table: Mapping[int, Proc],
    *,
    dry_run: bool,
    kill: Callable[[int], None] = _kill,
    signatures: tuple[str, ...] = (),
    gone: Callable[[int, float], bool] = _gone,
    notes: Path | None = None,
    orphans: tuple[str, ...] = (),
    claimed: Callable[[], set[int]] = _claimed,
    born: CreationClock = creation_stamp,
) -> tuple[int, list[str]]:
    """Stop *pid*'s subtree if it is an identifiable run or a stoppable orphan. ``(exit code, lines)``; 3 refused."""
    if never := _never(pid, table):
        return 3, [f'refused: {never}']
    matched = identify(table[pid][1], signatures)
    if matched is None:
        if why := _orphan_refusal(pid, table, orphans, claimed, born):
            said = f'refused: {pid} matches no run signature (built-in or {_TABLE}) and {why}'
            return 3, [f'{said}: {table[pid][1][:200]!r}']
        lines = [f'an orphan: its parent is gone and it holds no box claim: {table[pid][1][:120]!r}']
    else:
        lines = [f'matched signature {matched!r}']
    serve = matched == SERVE.pattern
    # Each member's creation stamp as the snapshot saw it: a pid recycled during the serve grace is not ours.
    stamps = {member: born(member) for member in subtree(table, pid)} if not dry_run else {}
    if serve and not dry_run:
        for child in (p for p, (ppid, _) in table.items() if ppid == pid and p != pid):
            note_stopped(child, root=notes)
    for member in subtree(table, pid):
        if serve and member == pid and not dry_run and gone(pid, SERVE_GRACE_S):
            lines.append(f'serve {pid} released its claim and exited')
            continue
        if not dry_run and born(member) != stamps[member]:
            lines.append(f'skipped {member}: its pid now names another process (creation stamp moved)')
            continue
        lines.append(f'{"would stop" if dry_run else "stopped"} {member}  {table[member][1][:120]}')
        if not dry_run:
            kill(member)
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    """Stop one identifiable run, or one orphan, and its subtree. Exit 3 when refused."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.stoprun', description=main.__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--repo', type=Path, default=None, help='repo whose pyproject declares signatures')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    root = args.repo or repo_root(Path.cwd())
    code, lines = stop(
        args.pid,
        process_table(),
        dry_run=args.dry_run,
        signatures=declared_signatures(root),
        orphans=declared_orphans(root),
    )
    for line in lines:
        emit(f'[stoprun] {line}', err=bool(code))
    return code


if __name__ == '__main__':
    sys.exit(main())
