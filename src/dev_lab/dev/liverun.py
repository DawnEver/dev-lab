"""TREE-HAS-A-LIVE-RUN: a checkout whose run is in progress is not edited, merged into, or re-synced.

THE INCIDENTS (motronics, 2026-10-19). While a JMAG run executed from a checkout -- its interpreter
``<checkout>/.venv/Scripts/python.exe -m motronics case sweep|deck run ...`` -- an agent edited a test file in
that checkout, ran ``git merge`` into it, and ran ``dep --sync`` on a worktree's venv the run was executing
from. ``deck run`` holds no environment seat, so the seat could not refuse the sync: a seat is a promise the
run has to make, and this one forgot.

THE ONE SOURCE OF TRUTH IS THE PROCESS TABLE, not a ledger a run must remember to join. A run IS a process
whose executable lies inside the checkout -- its own ``.venv`` interpreter, or a binary built there -- read by
:func:`lab_commons.census.processes` without the run's cooperation (a Windows venv launcher stays alive for
its child's whole life, so the launcher's image names the venv). Not the cwd: Windows does not expose
another process's cwd cheaply, and on POSIX every idle shell -- the agent's own included -- sits in one.

WHAT IS NOT A RUN, each decided by evidence:

* THIS process and every process whose in-tree ancestor is one of this process's own in-tree ancestors --
  the hook's own launcher, a test's pytest workers. They are the asker, not the run.
* A process younger than :data:`RUN_FLOOR_S`. Claude Code starts every matching hook of a tool call at
  once, each through the checkout's own interpreter; a hook lives for well under a second, a run for
  minutes. A run started within the floor is caught by the next tool call.

WHAT IS NOT THE TREE: ``output/`` (a run's own logs, a person's log moves) and ``.claude/`` (agent state no
run reads). Everything else under the checkout root is, down to the nearest nested checkout: a worktree
under ``.claude/worktrees/`` is its own tree with its own runs.

The Bash half of the guard is a row of the agent deny engine (``when: 'live-run'``), which calls ``--tree``
only after a mutating command matched; the Edit/Write half is :func:`main`'s ``hook``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Final, TextIO

from lab_commons.census import Process, processes
from lab_commons.log import emit

from dev_lab.dev._deny_liverun_row import LIVE_RUN
from dev_lab.dev.hooks import DENY_RULES, rules_by_id

__all__ = [
    'NOT_THE_TREE',
    'RULE_ID',
    'RUN_FLOOR_S',
    'checkout_of',
    'executing_from',
    'in_tree',
    'live_runs',
    'main',
    'refusal',
]

#: The deny row both halves of the guard render their refusal from (:mod:`dev_lab.dev._deny_liverun_row`).
RULE_ID: Final = str(LIVE_RUN['id'])

#: Top-level directories of a checkout that no run reads: a write there never changes what a run executes.
NOT_THE_TREE: Final = ('output', '.claude')

#: A process younger than this is a concurrent hook, not a run (seconds).
RUN_FLOOR_S: Final = 5.0

type Census = Callable[[], Iterable[Process]]

_FILE_TOOLS: Final = {
    'Edit': 'file_path',
    'Write': 'file_path',
    'MultiEdit': 'file_path',
    'NotebookEdit': 'notebook_path',
}


def _key(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).absolute()))


def checkout_of(path: Path | str) -> Path | None:
    """The nearest directory at or above *path* holding a ``.git`` (a worktree's is a file); ``None`` outside one."""
    at = Path(os.path.normpath(Path(path).absolute()))
    for candidate in (at, *at.parents):
        if (candidate / '.git').exists():
            return candidate
    return None


def in_tree(path: Path | str, root: Path | str) -> bool:
    """Whether a write to *path* changes what a run of checkout *root* executes."""
    owner = checkout_of(Path(path).parent if not Path(path).is_dir() else path)
    if owner is None or _key(owner) != _key(root):
        return False
    relative = Path(os.path.relpath(Path(path).absolute(), Path(root).absolute()))
    return not relative.parts or relative.parts[0] not in NOT_THE_TREE


def _under(path: str, prefix: str) -> bool:
    child, base = _key(path), _key(prefix)
    return child == base or child.startswith(base.rstrip(os.sep) + os.sep)


def _others(table: Sequence[Process], inside: Callable[[Process], bool], me: int) -> tuple[Process, ...]:
    """The processes of *table* that *inside* claims, minus the asker's own family and every hook-young one."""
    by_pid = {one.pid: one for one in table}
    lineage, at = set(), me
    while at in by_pid and at not in lineage:
        lineage.add(at)
        at = by_pid[at].ppid
    family = {pid for pid in lineage if inside(by_pid[pid])}

    def kin(one: Process) -> bool:
        seen, at = set(), one.pid
        while at in by_pid and at not in seen:
            if at in family:
                return True
            seen.add(at)
            at = by_pid[at].ppid
        return False

    return tuple(
        one
        for one in table
        if one.pid != me
        and one.executable
        and inside(one)
        and not kin(one)
        and (one.age_s is None or one.age_s >= RUN_FLOOR_S)
    )


def live_runs(root: Path | str, *, census: Census = processes, me: int | None = None) -> tuple[Process, ...]:
    """Every run executing from checkout *root*: its image lies in *root* and in no checkout nested below it."""

    def inside(one: Process) -> bool:
        if not one.executable or not _under(one.executable, str(root)):
            return False
        owner = checkout_of(Path(one.executable).parent)
        return owner is not None and _key(owner) == _key(root)

    return _others(tuple(census()), inside, os.getpid() if me is None else me)


def executing_from(prefix: Path | str, *, census: Census = processes, me: int | None = None) -> tuple[Process, ...]:
    """Every process executing from the environment at *prefix* -- seat holder or not."""
    return _others(tuple(census()), lambda one: _under(one.executable, str(prefix)), os.getpid() if me is None else me)


def describe(runs: Iterable[Process]) -> str:
    """One line per run: its pid and its command line, which is what the reader stops or waits for."""
    return '\n'.join(f'  live run: pid {one.pid}: {one.command_line or one.executable}' for one in runs)


def refusal(root: Path | str, runs: Sequence[Process]) -> str:
    """The deny text: the row's own hazard and remedy, then the runs it saw."""
    rule = rules_by_id(DENY_RULES)[RULE_ID]
    return f'{rule.reason()}\n  tree: {Path(root).as_posix()}\n{describe(runs)}'


def _hook(stdin: TextIO, census: Census) -> int:
    try:
        payload = json.load(stdin)
    except ValueError:
        return 0
    tool = payload.get('tool_name') if isinstance(payload, dict) else None
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    key = _FILE_TOOLS.get(str(tool))
    target = tool_input.get(key) if key and isinstance(tool_input, dict) else None
    if not isinstance(target, str) or not target:
        return 0
    path = Path(payload.get('cwd') or '.', target)
    root = checkout_of(path.parent)
    if root is None or not in_tree(path, root):
        return 0
    runs = live_runs(root, census=census)
    if runs:
        decision = {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': refusal(root, runs),
        }
        emit(json.dumps({'hookSpecificOutput': decision}))
    return 0


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None, census: Census = processes) -> int:
    """``hook`` judges a PreToolUse payload (Edit/Write/MultiEdit/NotebookEdit); ``--tree DIR`` exits 1 naming runs."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.liverun', description=__doc__.splitlines()[0])
    parser.add_argument('mode', nargs='?', choices=('hook',))
    parser.add_argument('--tree', type=Path)
    args = parser.parse_args(argv)
    if args.mode == 'hook':
        return _hook(stdin or sys.stdin, census)
    if args.tree is None:
        parser.error('give `hook` or --tree DIR')
    root = checkout_of(args.tree)
    runs = live_runs(root, census=census) if root is not None else ()
    if runs:
        emit(refusal(root, runs))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
