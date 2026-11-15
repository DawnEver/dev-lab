"""A SESSION'S BACKGROUND SHELL LIVES FIFTY MINUTES: ``python -m dev_lab.dev.shellreaper [--dry-run | --hook]``.

User demand 2026-11-15: an agent's background shells (``until ...; do sleep; done`` waits, ``forge watch --stream``,
verify runs) had no lifetime; some ran for days and outlived the session that started them. Two halves:

* AT LAUNCH, the deny row ``BACKGROUND-SHELL-IS-BOUNDED`` (:mod:`dev_lab.dev._deny_background_row`) refuses a
  ``run_in_background`` Bash call that does not start with ``timeout <n>``, naming ``timeout 50m <command>``;
* AFTERWARDS, this sweep. Wired at ``SessionStart`` and at every ``Stop`` (:data:`dev_lab.dev.agent_wiring.WIRING`),
  ``--hook`` detaches at most one sweep per :data:`SWEEP_INTERVAL_S` per repo and returns at once; the sweep holds
  a per-repo lock in the git common dir and logs each stop to ``output/logs/<yy>/<mm>/<dd>/reaper/``.

WHAT IS AN AGENT SHELL, read off the one census (:mod:`lab_commons.census`): a shell process (bash, sh, zsh, dash,
PowerShell) whose parent is an agent session (:data:`AGENT`), or which sources the agent harness's shell snapshot
(:data:`HARNESS`) and whose parent does not -- so a shell whose session ENDED is still one, and a nested shell is
part of its root's tree. A user's own terminal is neither; an MCP server is no shell. A foreground tool call is
ended by the harness within minutes, so an agent shell older than its bound is a background one.

ITS BOUND is :data:`DEFAULT_LIFETIME_S`, longer ONLY by the user's grant its line names, verified at its launch
(:func:`dev_lab.dev.shelllife.granted_bound`, user ruling 2026-11-15): an agent-written ``timeout 6h`` alone is
stopped at fifty minutes.

WHAT IS NEVER STOPPED, at any age: a tree holding a box claim (:func:`lab_commons.box.ledger.holdings`; an
unreadable ledger stops nothing), a ``forge serve`` (:data:`dev_lab.dev.stopsignatures.SERVE`), anything the
repo declares in ``[tool.dev_lab.stoprun] spare = [...]``, a shell of unknown age, this process and its ancestors.
The stop itself is stoprun's own tree-kill (:func:`dev_lab.dev.stoprun.stop_subtree`): children first, a recycled
pid skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Final, TextIO

from lab_commons.box.ledger import holdings
from lab_commons.census import Process, processes
from lab_commons.liveness import CreationClock, creation_stamp
from lab_commons.log import emit

from dev_lab.dev._deny_background_row import DEFAULT_LIFETIME_S
from dev_lab.dev.proctable import subtree, unstoppable
from dev_lab.dev.reclaimrun import common_dir, detach_argv, held, repo_main
from dev_lab.dev.shelllife import Grants, granted_bound
from dev_lab.dev.stoprun import stop_subtree
from dev_lab.dev.stopsignatures import SERVE, SignaturesNotDeclared, declared_spares

__all__ = [
    'AGENT',
    'DEFAULT_LIFETIME_S',
    'HARNESS',
    'LOCK_NAME',
    'STAMP_NAME',
    'SWEEP_INTERVAL_S',
    'main',
    'run',
    'shell_roots',
    'sweep',
]

#: At most one sweep per repo this often: a ``Stop`` fires every turn, a sweep is a full process-table read.
SWEEP_INTERVAL_S: Final = 300.0
#: The sweep's lock and the hook's rate stamp, in the git COMMON dir every worktree of the repo shares.
LOCK_NAME: Final = 'dev-lab-shellreaper.lock'
STAMP_NAME: Final = 'dev-lab-shellreaper.stamp'
#: A lock this old belongs to a sweep that died.
_STALE_LOCK_S: Final = 3600.0

#: An agent session: its executable (a replaced binary keeps running as ``claude.exe.old.<n>``) or its package.
AGENT: Final = re.compile(
    r'(?:^|[/\\])claude(?:\.exe)?(?:\.old\.\d+)?$|@anthropic-ai[/\\]claude-code[/\\]', re.IGNORECASE
)
#: The agent harness's tool shell sources a snapshot of the user's shell; nothing else does.
HARNESS: Final = re.compile(r'shell-snapshots[/\\]snapshot-')
_SHELL: Final = re.compile(r'(?:^|[/\\])(?:bash|sh|zsh|dash|powershell|pwsh)(?:\.exe)?$', re.IGNORECASE)


def _agent(proc: Process | None) -> bool:
    return proc is not None and bool(AGENT.search(proc.executable) or AGENT.search(proc.command_line))


def _harness_shell(proc: Process | None) -> bool:
    return proc is not None and bool(_SHELL.search(proc.executable)) and bool(HARNESS.search(proc.command_line))


def shell_roots(procs: Iterable[Process]) -> list[Process]:
    """The agent shells that root a tree: a shell under an agent, or a harness shell not under another one."""
    table = {proc.pid: proc for proc in procs}
    roots = []
    for proc in table.values():
        if not _SHELL.search(proc.executable):
            continue
        parent = table.get(proc.ppid)
        if _agent(parent) or (_harness_shell(proc) and not _harness_shell(parent)):
            roots.append(proc)
    return sorted(roots, key=lambda proc: proc.pid)


def _claimed() -> set[int]:
    return {claim.pid for claim in holdings()}


def sweep(
    procs: Iterable[Process],
    *,
    claimed: Callable[[], set[int]] = _claimed,
    spares: tuple[str, ...] = (),
    dry_run: bool = False,
    kill: Callable[[int], None] | None = None,
    born: CreationClock = creation_stamp,
    grants: Grants | None = None,
    now: float | None = None,
) -> list[str]:
    """Stop every agent shell past its bound that holds no seat and is no spare; one line per stop or sparing."""
    snapshot = list(procs)
    table = {proc.pid: (proc.ppid, proc.command_line) for proc in snapshot}
    spared = [SERVE, *(re.compile(sig) for sig in spares)]
    try:
        seats = claimed()
    except (OSError, sqlite3.Error) as exc:
        return [f'nothing stopped: the box ledger could not be read, so a seat cannot be ruled out: {exc}']
    lines: list[str] = []
    for root in shell_roots(snapshot):
        if root.age_s is None:
            continue
        launched = (time.time() if now is None else now) - root.age_s
        bound = granted_bound(root.command_line, launched, **({} if grants is None else {'grants': grants}))
        if root.age_s < bound:
            continue
        tree = subtree(table, root.pid)
        what = f'{root.pid} (age {root.age_s / 60:.0f} min, bound {bound / 60:.0f} min)'
        if held_seats := seats & set(tree):
            lines.append(f'spared {what}: {sorted(held_seats)} holds a box seat')
        elif match := next((sig.pattern for pid in tree for sig in spared if sig.search(table[pid][1])), None):
            lines.append(f'spared {what}: runs {match!r}')
        elif never := unstoppable(root.pid, table):
            lines.append(f'spared {what}: {never}')
        else:
            said = [f'over its bound: {what} {root.command_line[:160]!r}']
            extra = {} if kill is None else {'kill': kill}
            lines += stop_subtree(root.pid, table, None, said, dry_run=dry_run, born=born, **extra)[1]
    return lines


def run(root: Path, *, dry_run: bool = False) -> Path | None:
    """One locked sweep from *root*; the log it wrote, or ``None`` (another sweep holds the lock, or nothing to say)."""
    with held(root, stale_s=_STALE_LOCK_S, name=LOCK_NAME) as mine:
        if not mine:
            return None
        try:
            spares = declared_spares(root)
        except SignaturesNotDeclared as exc:
            lines = [f'nothing stopped: {exc}']
        else:
            lines = sweep(processes(), spares=spares, dry_run=dry_run)
        if not lines:
            return None
        now = datetime.now().astimezone()
        log = root / 'output' / 'logs' / now.strftime('%y/%m/%d') / 'reaper' / f'{now:%H%M%S}-{os.getpid()}.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return log


def _hook(stdin: TextIO) -> None:
    """Detach one sweep of the session's repo unless one started within :data:`SWEEP_INTERVAL_S`."""
    try:
        payload = json.load(stdin)
    except ValueError:
        payload = {}
    cwd = (payload if isinstance(payload, dict) else {}).get('cwd') or Path.cwd()
    root = repo_main(Path(cwd))
    if root is None:
        return
    stamp = common_dir(root) / STAMP_NAME
    if stamp.exists() and time.time() - stamp.stat().st_mtime < SWEEP_INTERVAL_S:
        return
    stamp.touch()
    detach_argv(root, ['-m', 'dev_lab.dev.shellreaper', '--root', str(root)])


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """Stop agent background shells past their bound: inline, ``--dry-run``, or as the ``--hook``. Exits 0."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.shellreaper', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout whose log and spares apply')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='name what would be stopped, stop nothing')
    mode.add_argument('--hook', action='store_true', help='the SessionStart/Stop hook: detach a sweep, return')
    args = parser.parse_args(argv)
    try:
        if args.hook:
            _hook(stdin or sys.stdin)
            return 0
        log = run(args.root, dry_run=args.dry_run)
    except OSError as exc:  # a hook never blocks the session it serves
        emit(f'shell reaper did not run: {exc}')
        return 0
    emit(f'shell reaper log: {log}' if log else 'shell reaper: nothing past its bound, or another sweep holds the lock')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
