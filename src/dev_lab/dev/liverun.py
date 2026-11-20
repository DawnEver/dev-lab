"""TREE-HAS-A-LIVE-RUN: a checkout whose run is in progress is not edited, merged into, or re-synced.

THE INCIDENTS (downstream, 2026-10-19). While a JMAG run executed from a checkout -- its interpreter
``<checkout>/.venv/Scripts/python.exe -m app case sweep|deck run ...`` -- an agent edited a test file in
that checkout, ran ``git merge`` into it, and ran ``dep --sync`` on a worktree's venv the run was executing
from. ``deck run`` holds no environment seat, so the seat could not refuse the sync: a seat is a promise the
run has to make, and this one forgot.

THE ONE SOURCE OF TRUTH IS THE PROCESS TABLE (:func:`lab_commons.census.processes`), read without the run's
cooperation, and it answers TWO questions, one lock each:

* VENV LOCK (:func:`executing_from`): a process whose executable lies in an environment uses THAT environment,
  so ``dep`` refuses to mutate it. A ``forge serve`` from main's venv locks the venv.
* TREE LOCK (:func:`live_runs`): a process READS a checkout when it is a Python interpreter whose cwd is in it
  (``python -m`` puts the cwd first on ``sys.path``) -- unless the interpreter is from elsewhere and its ``-m``
  module is not in the cwd, so nothing of the tree is imported -- or when an operand (never a ``--flag``'s value,
  never a word of a shell's ``-c`` script) names an existing path in it (a ``scratch/*.sh`` chain, ``cases/...``).
  Measured 2026-10-19: the v3 sweep's interpreter works in its worktree; its bash chains name main's
  ``scratch/`` scripts; two dozen day-old ``tail -F output/...`` processes and Claude Code's own node processes
  sit in the checkout and read none of it. A serve works in its own root
  (:func:`dev_lab.dev.worktreeplace.work_root`), so it locks the venv and never the tree.

WHAT IS NOT A RUN, each decided by evidence:

* THIS process and every process whose in-tree ancestor is one of this process's own in-tree ancestors --
  the hook's own launcher, a test's pytest workers. They are the asker, not the run.
* A process younger than :data:`RUN_FLOOR_S`. Claude Code starts every matching hook of a tool call at
  once, each through the checkout's own interpreter; a hook lives for well under a second, a run for
  minutes. A run started within the floor is caught by the next tool call.
* git itself, and every process it started: git executes no code of the tree, and its descendants are hooks of
  a git command, which end with that command. Measured 2026-11-16: another session's commit hook, a python older
  than the floor, refused a merge.
* A shell's ``-c`` script (``timeout 580 bash -c "until [ $(git -C <tree> rev-parse HEAD) ... ]"``, the Bash
  tool's own ``bash -c -l "..."``): it is text, and each command it starts is a process of its own, judged by
  what IT executes -- a ``python -m pytest`` it starts in the tree is still a run. Measured 2026-11-17: a wait
  loop naming a tree in its script locked that tree, so the agent working there could never move the HEAD it
  waited for.
* A multiprocessing worker whose parent is gone (:data:`SPAWN_WORKER`). It serves its parent through a pipe,
  so without the parent it can never advance; it only holds the cwd it inherited. Measured 2026-10-24: two
  day-old spawn workers of a dead pid sat in a downstream worktree and refused every mutation there.

WHAT IS NOT THE TREE: ``output/`` (a run's own logs, a person's log moves) and ``.claude/`` (agent state no
run reads). Everything else under the checkout root is, down to the nearest nested checkout: a worktree
under ``.claude/worktrees/`` is its own tree with its own runs.

The Bash half of the guard is a row of the agent deny engine (``when: 'live-run'``), which calls ``--tree``
only after a mutating command matched; the Edit/Write half is :func:`main`'s ``hook``.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Final, TextIO

from lab_commons import storage
from lab_commons.census import Process, processes
from lab_commons.log import emit

from dev_lab.dev import gitdirs
from dev_lab.dev._deny_liverun_row import LIVE_RUN
from dev_lab.dev.hooks import DENY_RULES, rules_by_id
from dev_lab.dev.venvpath import PYTHON_SLOT, current_os_name, expand_interpreter, running_interpreter
from dev_lab.dev.venvpointer import POINTER, RETIRED_ALIAS

__all__ = [
    'NOT_THE_TREE',
    'RULE_ID',
    'RUN_FLOOR_S',
    'SPAWN_WORKER',
    'WATCH',
    'checkout_of',
    'env_in_use',
    'executing_from',
    'in_tree',
    'is_transient',
    'live_runs',
    'main',
    'occupants',
    'refusal',
]

#: The deny row both halves of the guard render their refusal from (:mod:`dev_lab.dev._deny_liverun_row`).
RULE_ID: Final = str(LIVE_RUN['id'])

#: The storage kinds no run READS from the tree (:data:`lab_commons.storage.KINDS`): ``build`` is not one -- a run
#: may load a native artefact built there.
_UNREAD_KINDS: Final = ('output', 'venvs', 'worktrees', 'vendor_cache', 'temp')

#: Top-level directories of a checkout that no run reads: a write there never changes what a run executes. Derived
#: from the in-tree defaults of :data:`_UNREAD_KINDS` (one spelling of each), plus the retired alias and the pointer.
NOT_THE_TREE: Final = tuple(
    dict.fromkeys(
        [
            *(Path(default).parts[0] for kind in _UNREAD_KINDS if (default := storage.KINDS[kind])),
            RETIRED_ALIAS,
            POINTER,
        ]
    )
)

#: The interpreter whose cwd is READ: ``python -m`` puts the cwd first on ``sys.path``. Not node: Claude Code and
#: its MCP servers are node processes sitting in the checkout for the whole session (measured 2026-10-19).
_INTERPRETER: Final = re.compile(r'^python[\w.]*(?:\.exe)?$', re.IGNORECASE)

#: A Git Bash spelling of a drive path, ``/<drive>/x`` -> ``<drive>:/x``.
_DRIVE: Final = re.compile(r'^/([a-zA-Z])/')

#: The executable that is never a run: it executes no code of the tree, and its descendants are its hooks.
_GIT: Final = re.compile(r'^git(?:\.exe)?$', re.IGNORECASE)

#: A shell: what follows its ``-c`` is a script, TEXT, whose every command is a process of its own.
_SHELL: Final = re.compile(r'^(?:sh|bash|zsh|dash|ksh)(?:\.exe)?$', re.IGNORECASE)

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
    return gitdirs.checkout_of(Path(path))


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

    def hook(one: Process) -> bool:
        seen, at = set(), one.pid
        while at in by_pid and at not in seen:
            seen.add(at)
            if _GIT.match(Path(by_pid[at].executable.replace('\\', '/')).name):
                return True
            at = by_pid[at].ppid
        return False

    return tuple(
        one
        for one in table
        if one.pid != me
        and not hook(one)
        and one.executable
        and inside(one)
        and not kin(one)
        and not (SPAWN_WORKER.search(one.command_line) and one.ppid not in by_pid)
        and (one.age_s is None or one.age_s >= RUN_FLOOR_S)
    )


def _arguments(one: Process) -> list[str]:
    """*one*'s command line split into words, its own executable excluded."""
    return list(_words(one.command_line))


@functools.lru_cache(maxsize=4096)
def _words(command_line: str) -> tuple[str, ...]:
    """*command_line* split into words past the executable: PURE, so cached.

    MEASURED 2026-11-17: a prune judges every tree against one process snapshot, re-splitting every command line
    per tree -- 48k ``shlex.split`` calls, ~40 s of a 264 s census over 94 trees.
    """
    try:
        return tuple(shlex.split(command_line, posix=False)[1:])
    except ValueError:
        return tuple(command_line.split()[1:])


def _named_paths(one: Process) -> Iterable[Path]:
    """Every existing path *one*'s operands name, relative ones against its cwd.

    An option and the value a ``--long`` option takes are configuration the process reads, not code it executes
    (measured 2026-11-07: ``--settings <checkout>/...`` made a session launcher a run of that checkout). A shell's
    ``-c`` script -- the shell's own or one a wrapper starts (``timeout 580 bash -c ...``) -- is text whose every
    command is a process of its own, judged by what IT executes (measured 2026-11-17: a wait loop whose script
    read ``git -C <tree> rev-parse HEAD`` locked the tree whose HEAD it waited on).
    """
    words = _arguments(one)
    shell = bool(_SHELL.match(Path(one.executable.replace('\\', '/')).name))
    for previous, word in zip(['', *words], words, strict=False):
        bare = word.strip('"\'')
        if shell and bare == '-c':
            return
        shell = shell or bool(_SHELL.match(Path(bare.replace('\\', '/')).name))
        if previous.startswith('--') and '=' not in previous:
            continue
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


def _module_outside_cwd(one: Process) -> bool:
    """Whether *one* runs ``-m <module>`` whose top-level package is not in its cwd, so it resolves elsewhere."""
    words = [word.strip('"\'') for word in _arguments(one)]
    if '-m' not in words[:-1]:
        return False
    top = words[words.index('-m') + 1].split('.')[0]
    return not (_exists(Path(one.cwd, f'{top}.py')) or _is_dir(Path(one.cwd, top)))


def reads_tree(one: Process, root: Path | str) -> bool:
    """Whether *one* READS checkout *root*: an interpreter executing from it, or an argument naming a path in it.

    An interpreter working in the tree executes it when ``python -m`` resolves its module from the cwd, or when
    the interpreter is the tree's own (its site-packages install the tree). An interpreter from elsewhere whose
    ``-m`` module is not in the cwd imports nothing of the tree (measured 2026-11-07: a session launcher whose
    cwd was the checkout refused every ``git worktree add`` there).
    """
    name = Path(one.executable.replace('\\', '/')).name
    if (
        _INTERPRETER.match(name)
        and one.cwd
        and in_tree(one.cwd, root)
        and (_under(one.executable, str(root)) or not _module_outside_cwd(one))
    ):
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
    return _others(tuple(census()), lambda one: _occupies(one, root), os.getpid() if me is None else me)


def _occupies(one: Process, root: Path | str) -> bool:
    """Whether *one* works in, executes from, or reads checkout *root*."""
    return (bool(one.cwd) and _under(one.cwd, str(root))) or _under(one.executable, str(root)) or reads_tree(one, root)


def removal_holders(root: Path | str, *, census: Census = processes, me: int | None = None) -> tuple[Process, ...]:
    """REMOVAL LOCK: every process but the asker that works in, executes from or reads *root* -- its family INCLUDED.

    :func:`occupants` forgives the asker's own lineage and every hook-young process, which an edit may. A removal
    may not (incident 2026-10-31): the sweep ran under ai-lab's ``runtime`` session, whose venv python was its own
    ancestor, judged that tree free, and deleted every tracked file before the held interpreter refused.
    """
    mine = os.getpid() if me is None else me
    table = tuple(census())
    asker = _launch_chain(table, mine)
    return tuple(one for one in table if one.pid not in asker and one.executable and _occupies(one, root))


def _launch_chain(table: Sequence[Process], me: int) -> set[int]:
    """The asker and every ancestor handing on its very same arguments (dev-lab#791).

    A venv launcher re-spawns the base interpreter with them, so ``worktrees --remove`` refused itself as
    ``live run: pid N (dev_lab.dev.worktrees)``. Any other ancestor -- a session, a shell -- still holds the tree.
    """
    by_pid = {one.pid: one for one in table}
    chain, at = {me}, me
    words = _arguments(by_pid[me]) if me in by_pid else None
    while words is not None and (parent := by_pid.get(by_pid[at].ppid)) and parent.pid not in chain:
        if _arguments(parent) != words:
            break
        chain.add(parent.pid)
        at = parent.pid
    return chain


#: A holder that is a whole agent SESSION, not a run: an ai-lab session wrapper or the Claude CLI itself.
_SESSION: Final = re.compile(r'-m\s+ai_lab\.session\b|(?:^|[\\/\s"])claude(?:\.exe)?(?:"|\s|$)')
_MODULE: Final = re.compile(r'\s-m\s+([\w.]+)')

#: A ``forge watch``: a READER of the forge, yet its interpreter holds its venv's files open, so it still locks the
#: venv. Its state lives on the forge, so stopping and re-arming it loses nothing: the refusal names both doors.
WATCH: Final = re.compile(r'-m\s+dev_lab.dev\.forge\s+watch\b')


#: An sshhold HOLDER (:mod:`dev_lab.dev._sshholder`): it carries no run signature, so ``stoprun`` refuses it; the
#: session's own ``close`` verb ends it. Group 1 is the held destination.
_SSH_HOLDER: Final = re.compile(r'-m\s+dev_lab\.dev\._sshholder\s+(\S+)')


def ssh_holder_dest(one: Process) -> str | None:
    """The destination *one* holds when it is an sshhold holder, else ``None``."""
    found = _SSH_HOLDER.search(one.command_line or '')
    return found[1] if found else None


#: A hook process: a ``dev_lab`` module started by a session hook (``agent_launcher.js``), alive for one tool call.
_HOOK: Final = re.compile(r'agent_launcher\.js|-m\s+dev_lab\.[\w.]+\s+hook\b')


def is_transient(one: Process) -> bool:
    """Whether *one* holds an environment only in passing: an agent session or a hook it launched.

    Neither is a verdict, and neither is the refused agent's to stop -- so the door is a new environment published
    beside theirs (``dep --bootstrap ROOT``), never closing them (dev-lab #632: an upgrade never closes a session).
    """
    return is_session(one) or bool(_HOOK.search(one.command_line or ''))


def is_watch(one: Process) -> bool:
    """Whether *one* is a ``forge watch``."""
    return bool(WATCH.search(one.command_line or ''))


def is_session(one: Process) -> bool:
    """Whether *one* is an agent session: worked around by another agent, never stopped by it."""
    return bool(_SESSION.search(one.command_line or one.executable or ''))


def label(one: Process) -> str:
    """A short name for *one*: ``a Claude session``, else the module it runs (``app``), else its program."""
    if is_session(one):
        return 'a Claude session'
    if is_watch(one):
        return 'a forge watch'
    words = (one.command_line or one.executable or '?').split()
    program = Path(one.executable or words[0]).stem
    module = _MODULE.search(one.command_line or '')
    return module[1] if module else program


def describe(runs: Iterable[Process]) -> str:
    """One line per holder: its pid and short label -- what the reader waits for, never its full command line."""
    return '\n'.join(f'  live run: pid {one.pid} ({label(one)})' for one in runs)


def refusal(root: Path | str, runs: Sequence[Process]) -> str:
    """The deny text in three lines: who holds *root*, the one exit, the details pointer.

    A SESSION holder is worked around in another worktree, never offered to ``stoprun``: it is another
    agent's live work, not a run the refused agent owns. An sshhold holder is offered ``sshhold close``, the
    door that ends it (``stoprun`` refuses a process with no run signature).
    """
    rule = rules_by_id(DENY_RULES)[RULE_ID]
    first, more = runs[0], len(runs) - 1
    who = f'pid {first.pid} ({label(first)})' + (f' and {more} more' if more else '')
    clause = (
        f'{RULE_ID}: {Path(root).as_posix()} is in use by {who}; changing it or its environment now corrupts that work.'
    )
    stoppable = next((one for one in runs if not is_session(one)), None)
    if stoppable is None:
        exit_text = (
            'Work in another worktree: git worktree add --detach .claude/worktrees/<name> <sha> '
            '(a session is not yours to stop).'
        )
    else:
        dest = ssh_holder_dest(stoppable)
        door = (
            f'end your own held session: {PYTHON_SLOT} -m dev_lab.dev.sshhold close {dest}'
            if dest
            else f'stop your own run: {PYTHON_SLOT} -m dev_lab.dev.stoprun --pid {stoppable.pid}'
        )
        exit_text = expand_interpreter(
            f'Work in another worktree (git worktree add --detach .claude/worktrees/<name> <sha>), wait, or {door}.',
            Path(root),
            os_name=current_os_name(),
        )
    return f'{clause}\n{exit_text}\n{rule.details}'


def env_in_use(name: str, prefix: str, users: Sequence[Process]) -> str:
    """H1 WITHOUT A SEAT: a process executes from the environment, so moving it moves the files under that run.

    When every holder is a ``forge watch`` the exit is stop, change, re-arm -- the watch's own command line.
    """
    if users and all(is_transient(one) for one in users):
        return (
            f'{name}: {prefix} is held only by agent sessions or their hooks:\n{describe(users)}\n'
            'Run dep --bootstrap ROOT instead: it publishes a new environment beside this one and the next '
            'launch takes it; nothing else is required.'
        )
    if users and all(is_watch(one) for one in users):
        stops = '; '.join(f'{running_interpreter()} -m dev_lab.dev.stoprun --pid {one.pid}' for one in users)
        rearm = '\n'.join(f'  {one.command_line}' for one in users)
        return (
            f'{name}: {prefix} is the environment of a live forge watch (its interpreter holds the files a change '
            f'replaces):\n{describe(users)}\nStop it ({stops}), '
            "run this change, then re-arm it -- from another checkout's interpreter, so it never holds this one:"
            f'\n{rearm}'
        )
    return (
        f'{name}: {prefix} is the environment of a live process that holds no seat (2026-10-19: a `deck run` '
        f'held none and was re-synced under):\n{describe(users)}\nWait for it, stop it yourself '
        f'({running_interpreter()} -m dev_lab.dev.stoprun --pid <pid>), or change the environment of another '
        'worktree.'
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
    # A dir no run of its checkout reads -- above all a worktree not yet created under .claude/ -- is judged by nobody.
    runs = live_runs(root, census=census) if root is not None and in_tree(args.tree, root) else ()
    if runs:
        emit(refusal(root, runs))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
