"""STUCK-RUN-CANCEL: ``python -m dev_lab.dev.forge cancel-stuck <sha>`` -- scancel the forge's OWN stuck tasks.

A forge cluster run's array task is STUCK when it runs at full CPU and appends no result line: a hung
solve burns its allocation and its run never settles. Cancelling it was an ad-hoc ``scancel``; this door
bounds it so an agent may run it unattended. A task is cancelled only when EVERY bound holds:

* its job name is the forge's for this commit, ``run-<sha12>-<part>`` (:func:`lab_commons.hpc.run.job_name`),
  and the sha given is a full 40-hex commit -- a prefix could name another commit's run;
* it is RUNNING, at :data:`BUSY` or more of its allocated CPUs (cpu time / (elapsed x cpus));
* its run's one results file (:data:`lab_commons.hpc.worker.RESULTS`) took no new line for longer than its
  BOUND: ``--factor`` x ``--wall-minutes`` (the measured item wall) when given, else ``--bound-minutes``.

Anything else is listed with the bound it fails and left alone; a task that fails a bound is never
cancelled. Exit 0 when nothing was refused, 1 when some task was healthy, 2 when the sha or a read is refused.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from lab_commons.hpc.cluster import Runner, runner_for, scancel
from lab_commons.hpc.grants import Grant, Machine, load_grants
from lab_commons.hpc.run import load_state
from lab_commons.hpc.worker import RESULTS
from lab_commons.log import emit

__all__ = ['BUSY', 'Task', 'judge', 'main', 'parse_duration', 'read_tasks']

#: The CPU fraction at or above which a task counts as busy rather than waiting.
BUSY: Final = 0.9

_CLOCK_FIELDS: Final = 3
_SHA: Final = re.compile(r'^[0-9a-f]{40}$')
_PART: Final = r'[A-Za-z0-9_.-]+'


@dataclass(frozen=True)
class Task:
    """One RUNNING array task as Slurm and its results file describe it."""

    job_id: str  # ``7683032_12``
    name: str
    elapsed_s: float
    cpus: int
    cpu_s: float  # cumulative CPU time
    idle_s: float  # since the run's results file last took a line


def parse_duration(text: str) -> float:
    """Seconds of a Slurm duration: ``[D-]HH:MM:SS``, ``MM:SS`` or ``MM:SS.mmm``."""
    days, _, clock = text.strip().rpartition('-')
    parts = [float(p) for p in clock.split(':')]
    while len(parts) < _CLOCK_FIELDS:
        parts.insert(0, 0.0)
    hours, minutes, seconds = parts
    return (float(days) if days else 0.0) * 86400 + hours * 3600 + minutes * 60 + seconds


def judge(task: Task, sha: str, *, bound_s: float) -> str:
    """``''`` when *task* is a stuck forge task of *sha*; else the bound it fails."""
    if not re.fullmatch(rf'run-{sha[:12]}-{_PART}', task.name):
        return f'{task.job_id} {task.name}: refused -- not a forge task of {sha[:12]}'
    busy = task.cpu_s / max(task.elapsed_s * max(task.cpus, 1), 1.0)
    if busy < BUSY:
        return f'{task.job_id} {task.name}: healthy -- CPU {busy:.0%} is below {BUSY:.0%}'
    if task.idle_s <= bound_s:
        ago, bound = task.idle_s / 60, bound_s / 60
        return f'{task.job_id} {task.name}: healthy -- a result line {ago:.0f} min ago, bound {bound:.0f} min'
    return ''


#: One remote read: the clock, then every RUNNING task of the account.
_QUEUE: Final = "date +%s; squeue -h --me -t RUNNING -o '%i|%j|%M|%C'"


def read_tasks(shell: Runner, sha: str, run_dir: Callable[[str], str]) -> list[Task]:
    """Every RUNNING task under *shell*'s account; a task of *sha* also with its CPU time and result-line age.

    *run_dir* maps a part to its current round's run directory. Other jobs are read too and kept, so
    :func:`judge` refuses them by name rather than not seeing them.
    """
    lines = shell(_QUEUE, None).split()
    now, rows = float(lines[0]), [line.split('|') for line in lines[1:]]
    tasks = []
    for job_id, name, elapsed, cpus in rows:
        cpu_s, idle_s = 0.0, 0.0
        if found := re.fullmatch(rf'run-{sha[:12]}-({_PART})', name):
            results = shlex.quote(f'{run_dir(found.group(1))}/{RESULTS}')
            probe = (
                f'sstat -n -P -a -j {shlex.quote(job_id)} -o TotalCPU | sort | tail -1; '
                f'stat -c %Y {results} 2>/dev/null || echo 0'
            )
            total, mtime = [*shell(probe, None).split(), '0', '0'][:2]
            cpu_s = parse_duration(total) if ':' in total else 0.0
            idle_s = now - float(mtime) if float(mtime) else parse_duration(elapsed)
        tasks.append(Task(job_id, name, parse_duration(elapsed), int(cpus), cpu_s, idle_s))
    return tasks


def _run_dir(sha: str, grant: Grant, shell: Runner) -> Callable[[str], str]:
    machine = Machine(session=None, grants=(grant,))
    return lambda part: load_state(sha, part, machine, {grant.account: shell})[0]['rounds'][-1]['run_dir']


def cancel_stuck(
    sha: str,
    grants: Sequence[Grant],
    connect: Callable[[Grant], Runner],
    *,
    bound_s: float,
    say: Callable[[str], None],
    run_dir: Callable[[str, Grant, Runner], Callable[[str], str]] = _run_dir,
) -> int:
    """Cancel every stuck forge task of *sha* across *grants*; 1 when any task read was left alone."""
    if not _SHA.fullmatch(sha):
        say(f'cancel-stuck: refused -- {sha!r} is not a full 40-hex commit sha')
        return 2
    left = 0
    for grant in grants:
        shell = connect(grant)
        tasks = read_tasks(shell, sha, run_dir(sha, grant, shell))
        stuck = [t.job_id for t in tasks if not judge(t, sha, bound_s=bound_s)]
        for task in tasks:
            if (why := judge(task, sha, bound_s=bound_s)) and task.name.startswith(f'run-{sha[:12]}-'):
                left += 1
                say(why)
        if stuck:
            scancel(shell, stuck)
            say(f'{grant.name}: cancelled stuck {" ".join(stuck)}')
    return 1 if left else 0


def main(argv: Sequence[str] | None = None) -> int:
    """``forge cancel-stuck <sha> [--bound-minutes M | --wall-minutes W --factor N]``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge cancel-stuck', description=main.__doc__)
    parser.add_argument('sha')
    parser.add_argument('--bound-minutes', type=float, default=60.0, help='declared idle bound (no wall measured)')
    parser.add_argument('--wall-minutes', type=float, help='the measured item wall of this part')
    parser.add_argument('--factor', type=float, default=3.0, help='how many walls without a result is stuck')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.bound_minutes <= 0 or args.factor < 1 or (args.wall_minutes is not None and args.wall_minutes <= 0):
        emit('cancel-stuck: refused -- a bound must be positive and the factor at least 1', err=True)
        return 2
    bound = args.factor * args.wall_minutes if args.wall_minutes else args.bound_minutes
    grants = load_grants().grants
    try:
        return cancel_stuck(args.sha, grants, runner_for, bound_s=bound * 60, say=emit)
    except (RuntimeError, OSError, ValueError) as failed:
        emit(f'cancel-stuck: {failed}', err=True)
        return 2
