"""TREE-HAS-A-LIVE-RUN: a checkout whose run is in progress is not edited, merged into, or re-synced.

THE INCIDENTS (motronics, 2026-10-19). While a JMAG run executed from a checkout -- its interpreter
``<checkout>/.venv/Scripts/python.exe -m motronics case sweep|deck run ...`` -- an agent edited a test file in
that checkout, ran ``git merge`` into it, and ran ``dep --sync`` on a worktree's venv the run was executing
from. ``deck run`` holds no environment seat, so the seat could not refuse the sync: a seat is a promise the
run has to make, and this one forgot.

THE ONE SOURCE OF TRUTH IS THE PROCESS TABLE (:func:`lab_commons.census.processes`), read without the run's
cooperation, and it answers TWO questions, one lock each:

* VENV LOCK (:func:`executing_from`): a process whose executable lies in an environment uses THAT environment,
  so ``dep`` refuses to mutate it. A ``forge serve`` from main's venv locks the venv.
* TREE LOCK (:func:`live_runs`): a process READS a checkout when it is a Python interpreter whose cwd is in it
  (``python -m`` puts the cwd first on ``sys.path``) or when an argument names an existing path in it (a
  ``scratch/*.sh`` chain, ``cases/...``). Measured 2026-10-19: the v3 sweep's interpreter works in its worktree;
  its bash chains name main's ``scratch/`` scripts; two dozen day-old ``tail -F output/...`` processes and
  Claude Code's own node processes sit in the checkout and read none of it. A serve works in its own root
  (:func:`dev_lab.dev.forgeserve.work_root`), so it locks the venv and never the tree.

WHAT IS NOT A RUN, each decided by evidence:

* THIS process and every process whose in-tree ancestor is one of this process's own in-tree ancestors --
  the hook's own launcher, a test's pytest workers. They are the asker, not the run.
* A process younger than :data:`RUN_FLOOR_S`. Claude Code starts every matching hook of a tool call at
  once, each through the checkout's own interpreter; a hook lives for well under a second, a run for
  minutes. A run started within the floor is caught by the next tool call.
* A multiprocessing worker whose parent is gone (:data:`SPAWN_WORKER`). It serves its parent through a pipe,
  so without the parent it can never advance; it only holds the cwd it inherited. Measured 2026-10-24: two
  day-old spawn workers of a dead pid sat in a motronics worktree and refused every mutation there.

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
import re
import shlex
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
    'SPAWN_WORKER',
    'checkout_of',
    'env_in_use',
    'executing_from',
    'in_tree',
    'live_runs',
    'main',
    'occupants',
    'refusal',
]

#: The deny row both halves of the guard render their refusal from (:mod:`dev_lab.dev._deny_liverun_row`).
RULE_ID: Final = str(LIVE_RUN['id'])

#: Top-level directories of a checkout that no run reads: a write there never changes what a run executes.
NOT_THE_TREE: Final = ('output', '.claude', '.venv')

#: The interpreter whose cwd is READ: ``python -m`` puts the cwd first on ``sys.path``. Not node: Claude Code and
#: its MCP servers are node processes sitting in the checkout for the whole session (measured 2026-10-19).
_INTERPRETER: Final = re.compile(r'^python[\w.]*(?:\.exe)?$', re.IGNORECASE)

#: A Git Bash spelling of a drive path, ``/<drive>/x`` -> ``<drive>:/x``.
_DRIVE: Final = re.compile(r'^/([a-zA-Z])/')

#: A process younger than this is a concurrent hook, not a run (seconds).
RUN_FLOOR_S: Final = 5.0

#: The command line multiprocessing gives a spawned or forkserver child: it advances only through its parent.
SPAWN_WORKER: Final = re.compile(r'--multiprocessing-fork|multiprocessing\.(?:spawn|forkserver)\b')

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
    owner = checkout_of(path if _is_dir(Path(path)) else Path(path).parent)
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
        and not (SPAWN_WORKER.search(one.command_line) and one.ppid not in by_pid)
        and (one.age_s is None or one.age_s >= RUN_FLOOR_S)
    )


def _named_paths(one: Process) -> Iterable[Path]:
    """Every existing path *one*'s arguments name (its own executable excluded), relative ones against its cwd."""
    try:
        words = shlex.split(one.command_line, posix=False)[1:]
    except ValueError:
        words = one.command_line.split()[1:]
    for word in words:
        bare = word.strip('"\'')
        text = _DRIVE.sub(lambda drive: f'{drive[1]}:/', bare, count=1) if os.name == 'nt' else bare
        if text.startswith('-') or ('/' not in text and '\\' not in text):
            continue
        path = Path(text) if Path(text).is_absolute() else Path(one.cwd, text) if one.cwd else None
        if path is not None and _exists(path):
            yield path


def _exists(path: Path) -> bool:
    """``Path.exists`` that answers ``False`` where stat RAISES: a busy named pipe (WinError 231, 2026-10-21)."""
    try:
        return path.exists()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    """``Path.is_dir`` answering ``False`` where stat RAISES, as :func:`_exists` does: an existing pipe can be busy."""
    try:
        return path.is_dir()
    except OSError:
        return False


def reads_tree(one: Process, root: Path | str) -> bool:
    """Whether *one* READS checkout *root*: an interpreter working in it, or an argument naming a path in it."""
    name = Path(one.executable.replace('\\', '/')).name
    if _INTERPRETER.match(name) and one.cwd and in_tree(one.cwd, root):
        return True
    return any(in_tree(path, root) for path in _named_paths(one))


def live_runs(root: Path | str, *, census: Census = processes, me: int | None = None) -> tuple[Process, ...]:
    """TREE LOCK: every run READING checkout *root* (:func:`reads_tree`) -- never one that only uses its venv."""
    return _others(tuple(census()), lambda one: reads_tree(one, root), os.getpid() if me is None else me)


def executing_from(prefix: Path | str, *, census: Census = processes, me: int | None = None) -> tuple[Process, ...]:
    """VENV LOCK: every process executing from the environment at *prefix* -- seat holder or not."""
    return _others(tuple(census()), lambda one: _under(one.executable, str(prefix)), os.getpid() if me is None else me)


def occupants(root: Path | str, *, census: Census = processes, me: int | None = None) -> tuple[Process, ...]:
    """WHOLE-TREE LOCK: every process working in, executing from, or reading checkout *root* -- ``output/`` included.

    A tree about to be archived and removed is stricter than one about to be edited: a session's node process
    sitting in it (another agent's worktree) and a ``tail`` of its ``output/`` are its occupants too.
    """

    def inside(one: Process) -> bool:
        return (
            (bool(one.cwd) and _under(one.cwd, str(root))) or _under(one.executable, str(root)) or reads_tree(one, root)
        )

    return _others(tuple(census()), inside, os.getpid() if me is None else me)


def describe(runs: Iterable[Process]) -> str:
    """One line per run: its pid and its command line, which is what the reader stops or waits for."""
    return '\n'.join(f'  live run: pid {one.pid}: {one.command_line or one.executable}' for one in runs)


def refusal(root: Path | str, runs: Sequence[Process]) -> str:
    """The deny text: the row's own hazard and remedy, then the runs it saw."""
    rule = rules_by_id(DENY_RULES)[RULE_ID]
    return f'{rule.reason()}\n  tree: {Path(root).as_posix()}\n{describe(runs)}'


def env_in_use(name: str, prefix: str, users: Sequence[Process]) -> str:
    """H1 WITHOUT A SEAT: a process executes from the environment, so moving it moves the files under that run."""
    return (
        f'{name}: {prefix} is the environment of a live process that holds no seat (2026-10-19: a `deck run` '
        f'held none and was re-synced under):\n{describe(users)}\nWait for it, stop it '
        f'(python -m dev_lab.dev.stoprun --pid <pid>), or change the environment of another worktree.'
    )


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
