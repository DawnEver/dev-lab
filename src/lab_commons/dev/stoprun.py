"""STOP ONE OWN GATE/VERIFY RUN: ``python -m lab_commons.dev.stoprun --pid PID [--dry-run]``.

Generalised 2026-10-04 from a consumer's process-tree killer (its ``--pid`` mode) (AUTO-MODE-RUNS-THE-DOORS):
an agent stopping its OWN superseded run was refused as a raw ``taskkill /T /F``. The door replaces the
raw kill with a checked one: it REFUSES unless the pid's command line is a run it can identify
(:data:`RUN_SIGNATURES` -- the family verify, a gate runner, pytest), and then stops that pid's
subtree only, children first. Local only.

No new dependency: the process table is read with ``Get-CimInstance Win32_Process`` on Windows and
``ps -A -o pid=,ppid=,args=`` elsewhere; :func:`stop` takes the table as an argument so a test can
plant one.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import Final

from lab_commons.log import emit

__all__ = ['RUN_SIGNATURES', 'Proc', 'identify', 'main', 'process_table', 'stop', 'subtree']

#: A command line that is one of these is a run this door may stop. Anything else is refused.
RUN_SIGNATURES: Final = (
    re.compile(r'-m\s+lab_commons\.dev\.verify\b'),
    re.compile(r'scripts[/\\]gate[/\\]runner\.py\b'),
    re.compile(r'-m\s+pytest\b'),
    re.compile(r'(?:^|[/\\\s])pytest(?:\.exe)?(?:\s|$)'),
)

Proc = tuple[int, str]  # (parent pid, command line)


def process_table() -> dict[int, Proc]:
    """``{pid: (ppid, cmdline)}`` for every process, from the platform's own table."""
    if os.name == 'nt':
        script = (
            'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine '
            '| ConvertTo-Json -Compress'
        )
        shell = shutil.which('powershell') or 'powershell'
        done = subprocess.run(
            [shell, '-NoProfile', '-Command', script],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            timeout=60,
        )
        rows = json.loads(done.stdout or '[]')
        rows = rows if isinstance(rows, list) else [rows]
        return {int(r['ProcessId']): (int(r['ParentProcessId'] or 0), r['CommandLine'] or '') for r in rows}
    done = subprocess.run(
        [shutil.which('ps') or 'ps', '-A', '-o', 'pid=,ppid=,args='],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        timeout=60,
    )
    table: dict[int, Proc] = {}
    for line in done.stdout.splitlines():
        pid, ppid, *args = [*line.split(None, 2), '', ''][:3]
        if pid.isdigit() and ppid.isdigit():
            table[int(pid)] = (int(ppid), args[0])
    return table


def identify(cmdline: str) -> bool:
    """Whether *cmdline* is a gate/verify run this door may stop."""
    return any(sig.search(cmdline) for sig in RUN_SIGNATURES)


def subtree(table: Mapping[int, Proc], pid: int) -> list[int]:
    """*pid* and every descendant, deepest first (children are stopped before their parent)."""
    order: list[int] = []
    frontier = [pid]
    while frontier:
        current = frontier.pop()
        order.append(current)
        frontier += [p for p, (ppid, _) in table.items() if ppid == current and p != current and p not in order]
    return order[::-1]


def _kill(pid: int) -> None:
    if os.name == 'nt':
        subprocess.run(
            [shutil.which('taskkill') or 'taskkill', '/PID', str(pid), '/F'],
            capture_output=True,
            check=False,
            timeout=60,
        )
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)


def stop(
    pid: int,
    table: Mapping[int, Proc],
    *,
    dry_run: bool,
    kill: Callable[[int], None] = _kill,
) -> tuple[int, list[str]]:
    """Stop *pid*'s subtree if it is an identifiable run. ``(exit code, lines)``; 3 means refused."""
    if pid in (os.getpid(), os.getppid()):
        return 3, [f'refused: {pid} is this process or its parent']
    if pid not in table:
        return 3, [f'refused: no process {pid}']
    if not identify(table[pid][1]):
        return 3, [f'refused: {pid} is not a gate/verify run: {table[pid][1][:200]!r}']
    lines = []
    for member in subtree(table, pid):
        lines.append(f'{"would stop" if dry_run else "stopped"} {member}  {table[member][1][:120]}')
        if not dry_run:
            kill(member)
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    """Stop one identifiable gate/verify run and its subtree. Exit 3 when refused."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.stoprun', description=main.__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    code, lines = stop(args.pid, process_table(), dry_run=args.dry_run)
    for line in lines:
        emit(f'[stoprun] {line}', err=bool(code))
    return code


if __name__ == '__main__':
    sys.exit(main())
