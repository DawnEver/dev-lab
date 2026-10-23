"""STUCK-RUN-CANCEL: ``python -m dev_lab.dev.forge cancel-stuck <sha>`` -- scancel the forge's OWN stuck tasks.

A forge cluster run's array task is STUCK when it runs at full CPU and streams no test line: a hung
solve burns its allocation and its run never settles. Cancelling it was an ad-hoc ``scancel``; this door
bounds it so an agent may run it unattended. A task is cancelled only when EVERY bound holds:

* its job name is the forge's for this commit, ``run-<sha12>-<part>`` (:func:`lab_commons.hpc.run.job_name`),
  AND its Slurm job id is one the part's CURRENT round recorded -- the name carries only 12 hex, so the job
  id is what ties a task to this commit's round (an earlier round's task of the same name is refused);
* it is RUNNING, at :data:`BUSY` or more of its allocated CPUs (cpu time / (elapsed x cpus));
* its items' stream (the per-test lines of :mod:`lab_commons.hpc.pytest_item`) took no new line for longer
  than its LIMIT, read once to judge and AGAIN just before ``scancel``.

THE LIMIT IS MEASURED, ONE SOURCE: ``--factor`` x the longest MEASURED duration of the shard's tests, read
from the forge's learned table (:attr:`lab_commons.compute.learned.Measured.durations`, keyed by node id) --
the numbers every host prices runs from. A shard holding a test never measured cannot be priced, so its
limit is at least ``--bound-minutes``, and the line says ``unmeasured``.

Anything else is listed with the bound it fails and left alone. Exit 0 when nothing was refused, 1 when
some task of the sha was healthy, 2 when the sha or a read is refused.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.learned import learned
from lab_commons.hpc.cluster import Runner, runner_for, scancel
from lab_commons.hpc.grants import Grant, Machine, load_grants
from lab_commons.hpc.run import load_state
from lab_commons.hpc.shell import ROOT
from lab_commons.log import emit

from dev_lab.dev.platformparts import origin_url

__all__ = ['BUSY', 'Limit', 'Task', 'cancel_stuck', 'judge', 'limit_of', 'main', 'parse_duration', 'read_tasks']

#: The CPU fraction at or above which a task counts as busy rather than waiting.
BUSY: Final = 0.9

_SHA: Final = re.compile(r'^[0-9a-f]{40}$')
_PART: Final = r'[A-Za-z0-9_.-]+'
_CLOCK_FIELDS: Final = 3


@dataclass(frozen=True)
class Limit:
    """How long a task may stream nothing, and what that rests on."""

    seconds: float
    basis: str


@dataclass(frozen=True)
class Task:
    """One RUNNING array task as Slurm and its stream describe it."""

    job_id: str  # ``7683032_12``
    name: str
    elapsed_s: float
    cpus: int
    cpu_s: float  # cumulative CPU time
    idle_s: float  # since its stream last took a line
    limit: Limit = Limit(0.0, '')
    refused: str = ''  # a read that cannot tie the task to its round, or measure it
    streams: str = ''  # the quoted stream paths, re-read before a cancel


def parse_duration(text: str) -> float:
    """Seconds of a Slurm duration: ``[D-]HH:MM:SS``, ``MM:SS`` or ``MM:SS.mmm``."""
    days, _, clock = text.strip().rpartition('-')
    parts = [float(p) for p in clock.split(':')]
    while len(parts) < _CLOCK_FIELDS:
        parts.insert(0, 0.0)
    hours, minutes, seconds = parts
    return (float(days) if days else 0.0) * 86400 + hours * 3600 + minutes * 60 + seconds


def limit_of(ids: Sequence[str], durations: Mapping[str, float], *, factor: float, bound_s: float) -> Limit:
    """*factor* x the longest measured of *ids*; at least *bound_s* when any id is unmeasured."""
    measured = [durations[i] for i in ids if i in durations]
    unmeasured = len(ids) - len(measured)
    seconds = factor * max(measured, default=0.0)
    basis = f'{factor:g} x measured {max(measured, default=0.0) / 60:.1f} min'
    if unmeasured:
        seconds = max(seconds, bound_s)
        basis += f'; {unmeasured} test(s) unmeasured, fallback bound {bound_s / 60:.0f} min'
    return Limit(seconds, basis)


def judge(task: Task, sha: str) -> str:
    """``''`` when *task* is a stuck forge task of *sha*; else the bound it fails."""
    if not re.fullmatch(rf'run-{sha[:12]}-{_PART}', task.name):
        return f'{task.job_id} {task.name}: refused -- not a forge task of {sha[:12]}'
    if task.refused:
        return f'{task.job_id} {task.name}: refused -- {task.refused}'
    busy = task.cpu_s / max(task.elapsed_s * max(task.cpus, 1), 1.0)
    if busy < BUSY:
        return f'{task.job_id} {task.name}: healthy -- CPU {busy:.0%} is below {BUSY:.0%}'
    if task.idle_s <= task.limit.seconds:
        ago, bound = task.idle_s / 60, task.limit.seconds / 60
        return (
            f'{task.job_id} {task.name}: healthy -- a test line {ago:.0f} min ago, '
            f'limit {bound:.0f} min ({task.limit.basis})'
        )
    return ''


#: One remote read: the clock, then every RUNNING task of the account.
_QUEUE: Final = "date +%s; squeue -h --me -t RUNNING -o '%i|%j|%M|%C'"


#: Separates the CPU lines from the stream clock in one probe's output.
_SPLIT: Final = '--stream--'


def _cpu_seconds(lines: Sequence[str]) -> float | None:
    """The most CPU any step of the task reports, parsed rather than text-sorted; ``None`` when none did."""
    seen = [parse_duration(line) for line in lines if ':' in line]
    return max(seen) if seen else None


def _newest(text: str) -> float:
    stamps = [float(word) for word in text.split() if word.replace('.', '', 1).isdigit()]
    return max(stamps, default=0.0)


def read_tasks(
    shell: Runner,
    sha: str,
    round_of: Callable[[str], tuple[str, frozenset[str]]],
    limit: Callable[[Sequence[str]], Limit],
) -> list[Task]:
    """Every RUNNING task under *shell*'s account; a task of *sha* also with its CPU, stream age and limit.

    *round_of* maps a part to its CURRENT round: the run directory, whose ``manifest.json`` names each shard's
    items (their node ids and stream), and the Slurm job ids that round submitted. Other jobs are read too
    and kept, so :func:`judge` refuses them by name.
    """
    lines = shell(_QUEUE, None).split()
    now, rows = float(lines[0]), [line.split('|') for line in lines[1:]]
    tasks = []
    for job_id, name, elapsed, cpus in rows:
        found = re.fullmatch(rf'run-{sha[:12]}-({_PART})', name)
        if not found or '_' not in job_id:
            tasks.append(Task(job_id, name, parse_duration(elapsed), int(cpus), 0.0, 0.0))
            continue
        run_dir, job_ids = round_of(found.group(1))
        base = job_id.partition('_')[0]
        if base not in job_ids:
            why = f'job {base} is not one the current round submitted ({", ".join(sorted(job_ids)) or "none"})'
            tasks.append(Task(job_id, name, parse_duration(elapsed), int(cpus), 0.0, 0.0, refused=why))
            continue
        manifest: dict[str, Any] = json.loads(shell(f'cat {shlex.quote(run_dir)}/manifest.json', None))
        start, stop = manifest['shards'][int(job_id.rpartition('_')[2])]
        items = manifest['items'][start:stop]
        streams = ' '.join(sorted({f'{ROOT}/trees/{sha}/{shlex.quote(item["stream"])}' for item in items}))
        probe = (
            f'sstat -n -P -a -j {shlex.quote(job_id)} -o TotalCPU; echo {_SPLIT}; '
            f'stat -c %Y {streams} 2>/dev/null || true'
        )
        cpu_text, _, stream_text = shell(probe, None).partition(_SPLIT)
        cpu_s = _cpu_seconds(cpu_text.split())
        mtime = _newest(stream_text)
        idle_s = now - mtime if mtime else parse_duration(elapsed)
        ids = [node for item in items for node in item.get('ids', ())]
        refused = '' if cpu_s is not None else 'sstat reported no CPU time, so its load cannot be measured'
        tasks.append(
            Task(
                job_id, name, parse_duration(elapsed), int(cpus), cpu_s or 0.0, idle_s, limit(ids),
                refused=refused, streams=streams,
            )
        )  # fmt: skip
    return tasks


def _still_silent(shell: Runner, task: Task) -> bool:
    """Re-read *task*'s stream clock just before a cancel: a line written since the judgement spares it."""
    lines = shell(f'date +%s; stat -c %Y {task.streams} 2>/dev/null || true', None).split()
    now, newest = float(lines[0]), _newest(' '.join(lines[1:]))
    return not newest or now - newest > task.limit.seconds


def _round_of(sha: str, grant: Grant, shell: Runner) -> Callable[[str], tuple[str, frozenset[str]]]:
    machine = Machine(session=None, grants=(grant,))

    def current(part: str) -> tuple[str, frozenset[str]]:
        last = load_state(sha, part, machine, {grant.account: shell})[0]['rounds'][-1]
        return last['run_dir'], frozenset(str(job) for job in last.get('job_ids', ()))

    return current


def cancel_stuck(
    sha: str,
    grants: Sequence[Grant],
    connect: Callable[[Grant], Runner],
    *,
    limit: Callable[[Sequence[str]], Limit],
    say: Callable[[str], None],
    round_of: Callable[[str, Grant, Runner], Callable[[str], tuple[str, frozenset[str]]]] = _round_of,
) -> int:
    """Cancel every stuck forge task of *sha* across *grants*; 1 when any task of the sha was left alone.

    A grant whose read fails is reported and the others are still judged, so one account cannot hide the rest;
    any such failure makes the exit 2.
    """
    if not _SHA.fullmatch(sha):
        say(f'cancel-stuck: refused -- {sha!r} is not a full 40-hex commit sha')
        return 2
    left, failed = 0, 0
    for grant in grants:
        try:
            shell = connect(grant)
            tasks = read_tasks(shell, sha, round_of(sha, grant, shell), limit)
            stuck = [t for t in tasks if not judge(t, sha)]
            for task in tasks:
                if (why := judge(task, sha)) and task.name.startswith(f'run-{sha[:12]}-'):
                    left += 1
                    say(why)
            spared = [t for t in stuck if not _still_silent(shell, t)]
            for task in spared:
                left += 1
                say(f'{task.job_id} {task.name}: healthy -- a test line arrived while it was being judged')
            stuck = [t for t in stuck if t not in spared]
            if stuck:
                scancel(shell, [t.job_id for t in stuck])
                for task in stuck:
                    say(f'{grant.name}: cancelled stuck {task.job_id} {task.name} ({task.limit.basis})')
        except (RuntimeError, OSError, ValueError, KeyError, IndexError) as why:
            failed += 1
            say(f'{grant.name}: refused -- {why}')
    return 2 if failed else 1 if left else 0


def main(argv: Sequence[str] | None = None) -> int:
    """``forge cancel-stuck <sha> [--factor N] [--bound-minutes M]``, run in the repo's checkout."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge cancel-stuck', description=main.__doc__)
    parser.add_argument('sha')
    parser.add_argument('--factor', type=float, default=3.0, help='how many measured walls without a line is stuck')
    parser.add_argument('--bound-minutes', type=float, default=60.0, help='the floor for a shard with unmeasured tests')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.bound_minutes <= 0 or args.factor < 1:
        emit('cancel-stuck: refused -- the bound must be positive and the factor at least 1', err=True)
        return 2
    try:
        durations = learned(origin_url(Path.cwd())).get('durations', {})
        return cancel_stuck(
            args.sha,
            load_grants().grants,
            runner_for,
            limit=lambda ids: limit_of(ids, durations, factor=args.factor, bound_s=args.bound_minutes * 60),
            say=emit,
        )
    except (RuntimeError, OSError, ValueError, KeyError) as failed:
        emit(f'cancel-stuck: {failed}', err=True)
        return 2
