"""AN HPC ACCOUNT'S LAST DAY, read once per tick from ``sacct`` and shown as a table on its host card.

USER RULING 2026-11-03: the usage summary is a compact table on the card the account's ``forge serve`` already
publishes every tick (:mod:`dev_lab.dev.forgehosts`), computed from the ONE ``sacct`` read its standing already
makes (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.standing`). :data:`COMMAND` is that read and :func:`parse` its
one parser: the standing's core-hours per run (:meth:`Day.per_run`, what the schedule's budget binds) and the
card's summary (:meth:`Day.summary`) come from the same rows. Numbers only: no threshold, no alert, no verdict.

THE READ. ``sacct -n -P -S now-24hours -o`` :data:`FIELDS`, parent rows AND their steps: a job's own row carries
its cores, ``CPUTimeRAW`` (allocated core-seconds), ``TotalCPU`` (used, its steps' sum, ``[D-]HH:MM:SS``) and its
ask; a step carries the ``MaxRSS`` and, for a job killed inside a step, the ``OUT_OF_MEMORY`` state.
``cpu_efficiency`` is TotalCPU / CPUTimeRAW over FINISHED jobs only -- a running job's TotalCPU is not yet
accounted, so counting it would read as waste -- and ``None`` when no finished job allocated a core-second.
``forge_share`` is the forge's fraction of the day's core-hours (job names ``run-<sha12>-<part>``).

THE READ DOOR (2026-11-15): ``python -m dev_lab.dev.hpcusage report --json`` prints every declared
``[[hpc.grant]]``'s day as JSON (:func:`report`) for a reader outside dev-lab -- the agents dashboard's collector,
which knows no Slurm and stores what it is handed. Each login (cluster and user) is read ONCE over its own login
hosts: this module's :data:`COMMAND`, its quota (:data:`QUOTA_COMMAND`, as fractions of each ceiling) and, for a
billed grant, its budget's ledger (:mod:`lab_commons.hpc.budget`). A login that cannot be read is listed
``read: false`` with its reason, never dropped. Read only: nothing is stored, sent or scheduled here.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

from lab_commons.hpc.budget import ledger_command, spent_and_committed
from lab_commons.hpc.cluster import Runner, runner_for
from lab_commons.hpc.grants import Grant, load_grants
from lab_commons.log import emit

from dev_lab.dev.diskusage import Usage, parse_mmlsquota, parse_quota
from dev_lab.dev.forgestuck import parse_duration
from dev_lab.dev.slurmkilled import size_mb

__all__ = [
    'COMMAND',
    'FIELDS',
    'QUOTA_COMMAND',
    'REPORT_SCHEMA',
    'STATES',
    'Day',
    'Job',
    'declared',
    'main',
    'parse',
    'quota_use',
    'report',
    'table',
]

#: The ``sacct -o`` fields :func:`parse` reads, in its order.
FIELDS: Final = 'JobID,JobName,State,AllocCPUS,CPUTimeRAW,TotalCPU,ReqMem,MaxRSS'
#: The ONE sacct read of this account's last day, per tick.
COMMAND: Final = f'sacct -n -P -S now-24hours -o {FIELDS}'
#: The states always counted, zero when absent; any other state seen is counted under its own name.
STATES: Final = ('COMPLETED', 'FAILED', 'CANCELLED', 'OUT_OF_MEMORY', 'TIMEOUT', 'RUNNING')
#: States of a job not yet finished: no efficiency is judged of it.
_UNFINISHED: Final = frozenset({'RUNNING', 'PENDING', 'REQUEUED', 'RESIZING', 'SUSPENDED'})
#: A step's state that names why its job ended, outranking the job row's own.
_STEP_WINS: Final = frozenset({'OUT_OF_MEMORY', 'TIMEOUT'})
#: A forge run's job name: ``run-<sha12>-<part>``.
_FORGE_JOB: Final = re.compile(r'run-([0-9a-f]{12})-')
#: How many least-efficient finished jobs the summary carries.
TOP: Final = 5
_FIELD_COUNT: Final = 8


@dataclass
class Job:
    """One job of the day: its own row, plus its steps' largest ``MaxRSS`` and deciding state."""

    job: str
    name: str = ''
    state: str = ''
    cores: int = 0
    alloc_s: int = 0
    used_s: float = 0.0
    req_mb: int = 0
    rss_mb: int | None = None

    @property
    def finished(self) -> bool:
        """Ended, with core-seconds allocated: only such a job's efficiency is judged."""
        return self.state not in _UNFINISHED and self.alloc_s > 0

    @property
    def efficiency(self) -> float:
        """TotalCPU over CPUTimeRAW, at most 1."""
        return min(self.used_s / self.alloc_s, 1.0) if self.alloc_s else 0.0

    @property
    def wasted_s(self) -> float:
        """Allocated core-seconds no CPU used."""
        return self.alloc_s * (1 - self.efficiency)


def _int(text: str) -> int:
    return int(text) if text.strip().isdigit() else 0


def parse(sacct: str) -> Day:
    """``sacct -n -P -o`` :data:`FIELDS` text into the :class:`Day`; a step with no job row is not a job."""
    jobs: dict[str, Job] = {}
    rows: set[str] = set()
    for line in sacct.splitlines():
        if not line.strip():
            continue
        jobid, name, state, cores, alloc, used, req, rss = (*line.split('|'), *[''] * _FIELD_COUNT)[:_FIELD_COUNT]
        base, dot, _step = jobid.strip().partition('.')
        job = jobs.setdefault(base, Job(base))
        state = state.split()[0] if state.strip() else ''
        if not dot:
            rows.add(base)
            job.name, job.req_mb, job.cores, job.alloc_s = name.strip(), size_mb(req), _int(cores), _int(alloc)
            job.used_s = parse_duration(used) if used.strip()[:1].isdigit() else 0.0
            job.state = job.state if job.state in _STEP_WINS else state
            continue
        if rss.strip():
            job.rss_mb = max(job.rss_mb or 0, size_mb(rss))
        if state in _STEP_WINS:
            job.state = state
    return Day(tuple(job for base, job in jobs.items() if base in rows))


@dataclass(frozen=True)
class Day:
    """The account's jobs of the last day, as :func:`parse` read them."""

    jobs: tuple[Job, ...]

    def per_run(self) -> dict[str, float]:
        """Core-hours per forge run's sha12: every part of a sha is that sha's use."""
        used: dict[str, float] = {}
        for job in self.jobs:
            if (match := _FORGE_JOB.match(job.name)) and job.alloc_s:
                used[match.group(1)] = used.get(match.group(1), 0.0) + job.alloc_s / 3600
        return used

    def summary(self) -> dict[str, Any]:
        """The card's numbers: jobs, core-hours, CPU efficiency, states, forge share, worst five, OOM asks."""
        states = dict.fromkeys(STATES, 0)
        for job in self.jobs:
            states[job.state] = states.get(job.state, 0) + 1
        alloc = sum(job.alloc_s for job in self.jobs)
        forge = sum(job.alloc_s for job in self.jobs if _FORGE_JOB.match(job.name))
        finished = [job for job in self.jobs if job.finished]
        finished_alloc = sum(job.alloc_s for job in finished)
        wasted = sum(job.wasted_s for job in finished)
        ranked = sorted(finished, key=lambda job: -job.wasted_s)[:TOP]
        return {
            'jobs': len(self.jobs),
            'core_hours': round(alloc / 3600, 3),
            'cpu_efficiency': round(1 - wasted / finished_alloc, 4) if finished_alloc else None,
            'states': states,
            'forge_share': round(forge / alloc, 4) if alloc else 0.0,
            'top_inefficient': [
                {
                    'job': j.job,
                    'name': j.name,
                    'cores': j.cores,
                    'cpu_eff': round(j.efficiency, 4),
                    'core_h': round(j.alloc_s / 3600, 3),
                }
                for j in ranked
            ],
            'oom': [
                {'job': j.job, 'name': j.name, 'req_mem_mb': j.req_mb, 'max_rss_mb': j.rss_mb}
                for j in self.jobs
                if j.state == 'OUT_OF_MEMORY'
            ],
        }


_MARKDOWN: Final = re.compile(r'([\\`*_{}\[\]()#+!|~])')


def _cell(value: object) -> str:
    """*value* as one Markdown table cell: HTML's characters as entities, Markdown's backslash-escaped, one line."""
    return _MARKDOWN.sub(r'\\\1', html.escape(' '.join(str(value).split()), quote=False))


def _pct(value: object) -> str:
    return f'{float(value) * 100:.0f}%' if isinstance(value, (int, float)) else 'n/a'


def table(summary: object) -> str:
    """The card's Markdown for a :meth:`Day.summary`; ``''`` when there is none."""
    if not isinstance(summary, dict):
        return ''
    states = ', '.join(f'{_cell(k)} {_cell(v)}' for k, v in summary.get('states', {}).items() if v)
    lines = [
        'last 24 h | jobs | core-h | CPU eff | forge share | states',
        '--- | --- | --- | --- | --- | ---',
        (
            f'sacct | {_cell(summary.get("jobs"))} | {_cell(summary.get("core_hours"))} | '
            f'{_pct(summary.get("cpu_efficiency"))} | {_pct(summary.get("forge_share"))} | {states or "none"}'
        ),
    ]
    if top := summary.get('top_inefficient'):
        lines += ['', 'least efficient | name | cores | CPU eff | core-h', '--- | --- | --- | --- | ---']
        lines += [
            f'{_cell(j["job"])} | {_cell(j["name"])} | {_cell(j["cores"])} | {_pct(j["cpu_eff"])} | '
            f'{_cell(j["core_h"])}'
            for j in top
        ]
    if oom := summary.get('oom'):
        lines += ['', 'out of memory | name | asked MB | MaxRSS MB', '--- | --- | --- | ---']
        lines += [
            f'{_cell(j["job"])} | {_cell(j["name"])} | {_cell(j["req_mem_mb"])} | '
            f'{_cell("n/a" if j["max_rss_mb"] is None else j["max_rss_mb"])}'
            for j in oom
        ]
    return '\n'.join(lines)


#: The account's quota, read where its login lands: GPFS first, else Linux ``quota -w``.
QUOTA_COMMAND: Final = (
    '/usr/lpp/mmfs/bin/mmlsquota 2>/dev/null || mmlsquota 2>/dev/null || quota -w 2>/dev/null || true'
)
#: The :func:`report` shape's version: a reader refuses one it does not know.
REPORT_SCHEMA: Final = 1
#: A reason is one line of at most this many characters.
_WHY: Final = 160
#: What :func:`report` carries of a :meth:`Day.summary`: numbers only, never a job's name.
_REPORTED: Final = ('jobs', 'core_hours', 'cpu_efficiency', 'states', 'forge_share')


def quota_use(usage: Usage | None) -> dict[str, float | None] | None:
    """The account's quota as fractions used -- ``bytes`` and ``files`` (``None`` unread); ``None`` when unread."""
    if usage is None:
        return None
    files = usage.files / usage.files_limit if usage.files is not None and usage.files_limit else None
    return {
        'bytes': round(usage.used / usage.limit, 4) if usage.limit else None,
        'files': None if files is None else round(files, 4),
    }


def _budget(run: Runner, grant: Grant, today: date) -> dict[str, Any] | None:
    """A billed grant's budget: spent and committed core-hours against its total, and how much of its window is gone."""
    budget = grant.budget
    if not grant.billed or budget is None:
        return None
    since, until = date.fromisoformat(budget.since), date.fromisoformat(budget.until)
    spent, committed = spent_and_committed(run(ledger_command(grant, today=today), None))
    return {
        'core_hours': budget.core_hours,
        'spent': round(spent, 1),
        'committed': round(committed, 1),
        'since': budget.since,
        'until': budget.until,
        'window': round(min(max((today - since).days / (until - since).days, 0.0), 1.0), 4),
    }


def _read(grants: Sequence[Grant], today: date, connect: Callable[[Grant], Runner]) -> dict[str, Any]:
    """One login's day: *grants* share its cluster and user; the first names it, the first billed one its budget."""
    first = grants[0]
    head = {'cluster': first.cluster_name, 'account': first.user, 'slurm_account': first.slurm_account}
    head['role'] = first.role
    try:
        run = connect(first)
        summary = parse(run(COMMAND, None)).summary()
        quota = run(QUOTA_COMMAND, None)
        billed = next((g for g in grants if g.billed and g.budget is not None), None)
        return {
            **head,
            'read': True,
            **{key: summary[key] for key in _REPORTED},
            'quota': quota_use(parse_mmlsquota(quota) or parse_quota(quota)),
            'budget': None if billed is None else _budget(run, billed, today),
        }
    except (OSError, RuntimeError, ValueError) as why:  # unreachable, refused by role, a session it does not hold
        return {**head, 'read': False, 'why': ' '.join(str(why).split())[:_WHY] or type(why).__name__}


def report(grants: Sequence[Grant], *, today: date, connect: Callable[[Grant], Runner] = runner_for) -> dict[str, Any]:
    """Every login of *grants* read once (:func:`_read`), in declaration order, under :data:`REPORT_SCHEMA`."""
    logins: dict[tuple[str, str], list[Grant]] = {}
    for grant in grants:
        logins.setdefault((grant.cluster_name, grant.user), []).append(grant)
    return {
        'schema': REPORT_SCHEMA,
        'window_hours': 24,
        'grants': [_read(group, today, connect) for group in logins.values()],
    }


def declared() -> Sequence[Grant]:
    """The declared ``[[hpc.grant]]`` tables of this machine."""
    return load_grants().grants


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.hpcusage report --json``: every declared grant's day; exit 2 when none can be read."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcusage', description=(__doc__ or '').splitlines()[0])
    sub = parser.add_subparsers(dest='verb', required=True)
    verb = sub.add_parser('report', help="every declared grant's last day, quota and budget")
    verb.add_argument('--json', action='store_true', required=True, help='the report as one JSON object')
    parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        grants = declared()
    except (OSError, RuntimeError, ValueError) as why:
        sys.stderr.write(f'hpcusage: no [[hpc.grant]] read from the machine file ({why}); declare them there\n')
        return 2
    out = report(grants, today=datetime.now(UTC).date(), connect=runner_for)
    emit(json.dumps(out, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
