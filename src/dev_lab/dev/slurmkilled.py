"""WHICH JOBS SLURM KILLED FOR THEIR ASK, read from ``sacct``: the state, the memory asked and used, the time.

:meth:`dev_lab.dev.forgeslurm.SlurmCluster.killed` runs the query; this module reads its text, so the parse is
testable without a cluster.
"""

from __future__ import annotations

import re
from typing import Final

from dev_lab.dev.forgerunstate import Killed
from dev_lab.dev.forgestuck import parse_duration

__all__ = ['KILLED', 'KILLED_FIELDS', 'killed_jobs']

#: The ``sacct`` states of a job Slurm killed for its ask: memory, or time.
KILLED: Final = ('OUT_OF_MEMORY', 'TIMEOUT')
#: The ``sacct -o`` fields :func:`killed_jobs` reads, in its order.
KILLED_FIELDS: Final = 'JobID,State,ReqMem,MaxRSS,Elapsed,Timelimit'
_SIZE: Final = re.compile(r'([\d.]+)([KMGT]?)')
_MB_PER: Final = {'K': 1 / 1024, '': 1 / 1024 / 1024, 'M': 1, 'G': 1024, 'T': 1024 * 1024}


def _mb(text: str) -> int:
    """``4G``, ``8000M``, ``4300000K`` (or ``4Gn``/``4Gc`` of older Slurm) in MB; empty is 0."""
    match = _SIZE.match(text.strip())
    return round(float(match.group(1)) * _MB_PER[match.group(2)]) if match else 0


def _seconds(text: str) -> int:
    return round(parse_duration(text)) if text.strip() and text.strip()[0].isdigit() else 0


def killed_jobs(sacct: str) -> tuple[Killed, ...]:
    """Each job of ``sacct -n -P -o JobID,State,ReqMem,MaxRSS,Elapsed,Timelimit`` in a :data:`KILLED` state.

    The ask is the job's own row; ``MaxRSS`` is its steps' (``7_0.batch``), the largest; a job is killed when its
    row or a step's state is.
    """
    jobs: dict[str, list[str]] = {}
    used: dict[str, int] = {}
    for line in sacct.splitlines():
        job, state, req, rss, elapsed, limit = (*line.split('|'), '', '', '', '', '')[:6]
        base, dot, _step = job.strip().partition('.')
        state = state.split()[0] if state.strip() else ''
        if not dot:
            jobs[base] = [state, req, elapsed, limit]
            continue
        used[base] = max(used.get(base, 0), _mb(rss))
        if state in KILLED and base in jobs and jobs[base][0] not in KILLED:
            jobs[base][0] = state
    return tuple(
        Killed(job, state, _mb(req), used.get(job, 0), _seconds(limit), _seconds(elapsed))
        for job, (state, req, elapsed, limit) in jobs.items()
        if state in KILLED
    )
