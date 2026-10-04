"""STOP ONE OWN RUN: ``python -m lab_commons.dev.stoprun --pid PID [--repo PATH] [--dry-run]``.

Generalised 2026-10-04 from a consumer's process-tree killer (its ``--pid`` mode) (AUTO-MODE-RUNS-THE-DOORS):
an agent stopping its OWN superseded run was refused as a raw ``taskkill /T /F``. The door replaces the
raw kill with a checked one: it REFUSES unless the pid's command line is a run it can identify
(:data:`RUN_SIGNATURES` -- the family verify, a gate runner, pytest -- plus any the repo declares),
and then stops that pid's subtree only, children first, never an ancestor or a sibling. Local only.

A repo adds its own signatures as DATA, in ONE place -- its ``pyproject.toml`` (the repo of the cwd,
or ``--repo``)::

    [tool.lab_commons.stoprun]
    signatures = ["jcwrap"]   # regexes searched in the pid's own command line, like the built-ins

A declaration that is not a list of valid regex strings raises :class:`SignaturesNotDeclared`.
``--dry-run`` names the signature that matched.

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
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from lab_commons.dev.checkout import git_out
from lab_commons.log import emit

__all__ = [
    'RUN_SIGNATURES',
    'Proc',
    'SignaturesNotDeclared',
    'declared_signatures',
    'identify',
    'main',
    'process_table',
    'repo_root',
    'stop',
    'subtree',
]

_TABLE = '[tool.lab_commons.stoprun]'

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


class SignaturesNotDeclared(ValueError):
    """``[tool.lab_commons.stoprun] signatures`` is not a list of valid regex strings."""


def declared_signatures(root: Path) -> tuple[str, ...]:
    """The extra signatures *root*'s ``pyproject.toml`` declares; ``()`` when it declares none.

    Raises:
        SignaturesNotDeclared: the manifest is unreadable, or the value is not a list of regex strings.

    """
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
    value = table.get('signatures', []) if isinstance(table, dict) else table
    if not isinstance(value, list) or not all(isinstance(s, str) and s for s in value):
        msg = f'{_TABLE} signatures in {manifest} is {value!r}; it must be a list of regex strings'
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
    signatures: tuple[str, ...] = (),
) -> tuple[int, list[str]]:
    """Stop *pid*'s subtree if it is an identifiable run. ``(exit code, lines)``; 3 means refused."""
    if pid in (os.getpid(), os.getppid()):
        return 3, [f'refused: {pid} is this process or its parent']
    if pid not in table:
        return 3, [f'refused: no process {pid}']
    if pid in _ancestors(table, os.getpid()):
        return 3, [f'refused: {pid} is an ancestor of this process']
    matched = identify(table[pid][1], signatures)
    if matched is None:
        return 3, [f'refused: {pid} matches no run signature (built-in or {_TABLE}): {table[pid][1][:200]!r}']
    lines = [f'matched signature {matched!r}']
    for member in subtree(table, pid):
        lines.append(f'{"would stop" if dry_run else "stopped"} {member}  {table[member][1][:120]}')
        if not dry_run:
            kill(member)
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    """Stop one identifiable gate/verify run and its subtree. Exit 3 when refused."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.stoprun', description=main.__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--repo', type=Path, default=None, help='repo whose pyproject declares signatures')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    signatures = declared_signatures(args.repo or repo_root(Path.cwd()))
    code, lines = stop(args.pid, process_table(), dry_run=args.dry_run, signatures=signatures)
    for line in lines:
        emit(f'[stoprun] {line}', err=bool(code))
    return code


if __name__ == '__main__':
    sys.exit(main())
