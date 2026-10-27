"""THE SLURM SIDE OF A CLUSTER RUN -- :class:`dev_lab.dev.forgerunstate.Cluster` through this login node's shell.

Everything here runs ON the cluster login node (``lab_commons.hpc``'s own shell, never ``ssh``):
submitting and gathering a run, where its jobs stand (:func:`progress_text`, the phrase its claim
carries), cancelling a run no limit lets start, the outcomes a run CARRIES from the nearest earlier runs of its env --
finished records and the finished shards of superseded ones (:mod:`dev_lab.dev.forgecarry`) -- and the
account's STANDING read locally each tick -- its supply
(cpu, memory, the QOS's remaining submissions over every grant and the machine file's declared tools,
:class:`lab_commons.hpc.provider.SlurmAccount` and the one seat provider, and the home's FILE headroom read by
:func:`dev_lab.dev.diskusage.read_usage`), the last day's core-hours per run from ``sacct``,
and the partitions, quota and storage a host card publishes. An unreadable quota is stated on the card
(``storage: unread``) and leaves files uncapped; a home at its file limit claims nothing and the card says so.

A JOB SLURM KILLED IS READ, NAMED AND LEARNED (:meth:`SlurmCluster.killed`; Ada 2026-10-25, 24 h: 71
``OUT_OF_MEMORY`` jobs and 14 % ``TIMEOUT``, none visible on a PR). ``sacct`` gives each its ask and its use
(``ReqMem``/``MaxRSS``, ``Timelimit``/``Elapsed``); an OOM's ask is recorded grown by
:data:`~lab_commons.compute.learned.OOM_GROWTH` and held to the most any grant gives
(:func:`~lab_commons.hpc.plan.grantable_gb`), so the part's next run asks for more. A TIMEOUT needs nothing
here: the gather already keeps a killed item's floor (:meth:`lab_commons.compute.learned.Measured.killed`).

A FORGE JOB WHOSE RUN IS GONE IS CANCELLED (:meth:`SlurmCluster.strays`; Ada 2026-10-25: 25 % of a day's
core-hours). A run whose ref is gone cancels its own jobs (:func:`dev_lab.dev.forgerun._cancel_orphan`); a job
no run file names at all -- its run lost to another owner, or dropped -- had nobody to cancel it.

A RUNNING FORGE TASK THAT STOPPED PROGRESSING IS CANCELLED (:meth:`SlurmCluster.stalled`; Ada 2026-10-24..26:
eight tasks of long-superseded shas ran 34-41 h at 100 % of a core, each on one hung test, until a human
cancelled them -- RUNNING read as healthy). The bound is the task's OWN manifest: the per-test walls the item
runner kills at (:class:`lab_commons.hpc.builds.ItemWall`), times :data:`STALL_MULTIPLE`. Every task, whatever
its run -- current, draining for a newer tip, or one no run file names -- is judged, every tick.
"""

from __future__ import annotations

import contextlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from lab_commons.box.providers import account_seats
from lab_commons.compute import learned
from lab_commons.compute.presence import cached
from lab_commons.config import config_path
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.allocation import resolve
from lab_commons.hpc.builds import builds_at
from lab_commons.hpc.cluster import Runner, Unreachable, probe, scancel, submitter
from lab_commons.hpc.config import Config
from lab_commons.hpc.grants import Grant, Machine, Session, load_grants
from lab_commons.hpc.needsets import needs_of, vocabulary_at
from lab_commons.hpc.plan import grantable_gb
from lab_commons.hpc.progress import Progress, held_by_a_limit, where
from lab_commons.hpc.provider import SlurmAccount, unmeasured
from lab_commons.hpc.records import held_cells, run_shas
from lab_commons.hpc.run import _STARTED as STARTED  # the one spelling of a started task's squeue states
from lab_commons.hpc.run import NoRoom, cancel_run, job_name, load_state, submit_run, withdraw_pending
from lab_commons.hpc.shell import RunSpec
from lab_commons.hpc.slurm import FORGE_SESSION
from lab_commons.hpc.watch import PENDING, settle
from lab_commons.resources import Engine

from dev_lab.dev.diskusage import Usage, read_usage, storage_text
from dev_lab.dev.forgecarry import carry_from, read_by
from dev_lab.dev.forgeoom import learn_floors, oom_floors, task_items
from dev_lab.dev.forgerecords import read_allocation
from dev_lab.dev.forgerunstate import Cluster, Draining, Killed, Run, Stalled, Standing, Started, Unrecorded
from dev_lab.dev.forgeschedule import USAGE_COMMAND, parse_usage
from dev_lab.dev.forgestuck import parse_duration, remote_path

__all__ = ['KILLED', 'STALL_MULTIPLE', 'SlurmCluster', 'killed_jobs', 'progress_text', 'slurm_cluster', 'standing_of']

#: The ``sacct`` states of a job Slurm killed for its ask: memory, or time.
KILLED: Final = ('OUT_OF_MEMORY', 'TIMEOUT')
#: A forge job's name (:func:`lab_commons.hpc.run.job_name`, and the schema-1 ``run-<sha12>``).
_FORGE_JOB: Final = re.compile(r'run-[0-9a-f]{12}(-.+)?')
_KILLED_FIELDS: Final = 'JobID,State,ReqMem,MaxRSS,Elapsed,Timelimit'
#: How many times its per-test walls a RUNNING task may go before it is STALLED: its round's stream silent past
#: this times its LONGEST wall, or the task running past this times the SUM of its walls. The item runner
#: (:mod:`lab_commons.hpc.pytest_item`) writes a line at every test's start and end and kills any test at its
#: wall, collection included, so a runner that works never comes near ONE times either; the second factor is
#: headroom for the poll, the kill, a pytest relaunch and two clocks, never a second chance for the test.
STALL_MULTIPLE: Final = 2.0
#: Every RUNNING task of the account: its id, name, elapsed time and work dir (the round's run dir), and the clock.
_RUNNING: Final = "date +%s; squeue -h --me -t RUNNING -o '%i|%j|%M|%Z'"
_SIZE: Final = re.compile(r'([\d.]+)([KMGT]?)')
_MB_PER: Final = {'K': 1 / 1024, '': 1 / 1024 / 1024, 'M': 1, 'G': 1024, 'T': 1024 * 1024}


def stall_of(items: list[dict[str, Any]], *, idle_s: float, elapsed_s: float) -> str:
    """Why a task running *items* is stalled -- ``''`` when it is not, or when any of its ids declares no wall.

    *idle_s* is how long its round's stream has taken no line, *elapsed_s* how long it has run.
    """
    walls = [item.get('walls', {}).get(node) for item in items for node in item.get('ids', ())]
    if not walls or None in walls:
        return ''
    longest, total = max(walls), sum(walls)
    if idle_s > STALL_MULTIPLE * longest:
        return (
            f'its stream took no line for {idle_s / 60:.0f} min, past {STALL_MULTIPLE:g} x its longest test wall '
            f'({longest / 60:.0f} min)'
        )
    if elapsed_s > STALL_MULTIPLE * total:
        ran, bound = elapsed_s / 60, total / 60
        return f"it ran {ran:.0f} min, past {STALL_MULTIPLE:g} x the sum of its tests' walls ({bound:.0f} min)"
    return ''


def _last_started(text: str, items: set[object]) -> str:
    """The id the last ``start`` line of one of *items* names; ``''`` when none started."""
    last = ''
    for raw in text.splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            line = json.loads(raw)
            if isinstance(line, dict) and line.get('item') in items and 'start' in line:
                last = str(line['start'])
    return last


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


def progress_text(where_: Progress) -> str:
    """The phrase a status description carries: ``queued 3/93``, ``running 40/93 done 12/93``, ``gathering``."""
    if where_.finished:
        return 'gathering'
    if where_.running == 0 and where_.done == 0:
        return f'queued {where_.pending}/{where_.shards}'
    return f'running {where_.running}/{where_.shards} done {where_.done}/{where_.shards}'


def _home_quota() -> Usage | None:
    return read_usage(Path.home(), cluster=True)


@dataclass(frozen=True)
class SlurmCluster:
    """:class:`Cluster` through ``lab_commons.hpc`` and this login node's own shell (:func:`slurm_cluster`)."""

    root: Path
    machine: Machine
    config: Config
    connect: Callable[[Grant], Runner]
    quota: Callable[[], Usage | None] = _home_quota

    def _runners(self) -> dict[tuple[str, str], Runner]:
        return {grant.account: self.connect(grant) for grant in self.machine.grants}

    def submitted(self, run: Run) -> list[str]:
        """The job ids of every round ``hpc`` recorded for *run*'s sha; ``[]`` when it recorded none."""
        try:
            state, _ = load_state(run.sha, run.platform, self.machine, self._runners())
        except Unreachable:  # no host answered: nothing is known, which is never "nothing submitted"
            raise
        except RuntimeError:  # no state.json: nothing was submitted, or it died before writing one
            return []
        return [job for one in state['rounds'] for job in one['job_ids']]

    def orphans(self, run: Run) -> list[str]:
        """Jobs Slurm holds under this account with *run*'s job name (``run-<sha12>-<part>``), one id per array.

        An upgraded run's jobs may bear an older name too (:attr:`Run.job_aliases`); squeue is asked for every one.

        ``%F`` is the array's own job id: ``%i`` spells a pending array as ``7683032_[12-68%1]``, which
        ``scancel`` refuses, and that refusal crashed every tick of a host holding one (Ada, 2026-10-14).
        """
        shell = self.connect(self.machine.grants[0])
        names = ','.join((job_name(run.sha, run.platform), *run.job_aliases))
        return sorted(set(shell(f'squeue -h --me -n {names} -o %F', None).split()))

    def submit(self, run: Run) -> list[str]:
        """Fetch, build, collect, plan and submit round 0 (:func:`lab_commons.hpc.run.submit_run`)."""
        spec = RunSpec(
            sha=run.sha,
            repo_url=run.repo_url,
            collect=run.collect,
            vocabulary=vocabulary_at(self.root, run.sha),
            part=run.platform,
            pack_from=self.root,
            builds=builds_at(self.root, run.sha, python=''),
        )
        state = submit_run(
            spec,
            self.machine,
            self.connect,
            cost=self.config.cost,
            policy=self.config.policy,
            history=learned.learned(run.repo_url),
            carry=lambda env: self.carry(run.sha, env, run.platform),
        )
        return [job for one in state['rounds'] for job in one['job_ids']]

    def carry(self, sha: str, env: str, part: str) -> dict[str, tuple[dict[str, Any], str, str]]:
        """The cells *sha*'s run of *part* takes from its own earlier run and the nearest earlier runs of that part.

        Its own earlier run is one stopped before it ended -- released retryable and claimed again -- whose
        finished shards stand as they are (:func:`dev_lab.dev.forgecarry.carry_from`).

        A run of another part ran other ids; a run of another env is never read -- the env is the one
        dependency no footprint holds.
        """
        runners = self._runners()
        held = {}
        shas = run_shas(self.machine, runners, part)
        for ancestor in read_by(self.root, sha, shas):
            state, shell = load_state(ancestor, part, self.machine, runners)
            if state.get('env') == env and state.get('platform') == part:
                held[ancestor] = held_cells(state, shell)
        return carry_from(self.root, sha, held)

    def tree(self, run: Run) -> Path:
        """``~/ci/trees/<sha>`` in this account's home (:attr:`lab_commons.hpc.shell.RunSpec.tree`)."""
        return Path(f'~/ci/trees/{run.sha}').expanduser()

    def gather(self, run: Run) -> Path | None:
        """One :func:`lab_commons.hpc.watch.settle` without waiting: the record it wrote, or ``None`` while pending.

        A run whose job pends on an ACCOUNT limit with nothing running past the stall bound
        (:func:`lab_commons.hpc.progress.held_by_a_limit`) is given back: its ask is learned so this host stops
        admitting the part at the old size, its jobs are cancelled, and :class:`NoRoom` releases the claim RETRYABLE.
        """
        output = Path(run.output)
        if settle([run.sha], self.machine, self.connect, self.config, output, part=run.platform, sleep=None) == PENDING:
            policy = self.config.policy
            why = held_by_a_limit(where(run.sha, run.platform, self.machine, self.connect, policy=policy), policy)
            if why:
                state, _ = load_state(run.sha, run.platform, self.machine, self._runners())
                ask_gb = state['rounds'][-1]['mem_mb'] / 1024
                learned.record_ask(run.repo_url, learned.SLURM, needs_of(run.platform), ask_gb, safety=policy.safety)
                self.cancel(run)
                raise NoRoom(why)
            return None
        records = sorted(output.glob(f'run-{run.sha}-{run.platform}-*.json.gz'), key=lambda path: path.stat().st_mtime)
        if not records:
            msg = f'the run of {run.sha[:12]} ended without a record in {output}; its lines above say why'
            raise Unrecorded(msg)
        return records[-1]

    def killed(self, run: Run, record: Path | None = None) -> tuple[Killed, ...]:
        """*run*'s jobs Slurm killed for memory or time (:func:`killed_jobs`); an OOM's ask is learned grown.

        Grown by :data:`~lab_commons.compute.learned.OOM_GROWTH`, held to the most any grant gives, never
        lowering a known ask (:func:`~lab_commons.compute.learned.record_ask`): one learned store, read by the next
        run's admission and plan. Each file an OOM task ran is floored at its ask (:mod:`dev_lab.dev.forgeoom`),
        in the learned table and in *record*, the run record every host folds.
        """
        state, shell = load_state(run.sha, run.platform, self.machine, self._runners())
        ids = [str(job) for one in state['rounds'] for job in one['job_ids']]
        if not ids:
            return ()
        found = killed_jobs(shell(f'sacct -n -P -j {",".join(ids)} -o {_KILLED_FIELDS}', None))
        oom = [one.asked_mb for one in found if one.state == 'OUT_OF_MEMORY']
        if oom:
            grants = self.machine.grants
            ceiling = grantable_gb([(g, probe(self.connect(g), g.slurm_account)) for g in grants])
            ask_gb = max(oom) / 1024 * learned.OOM_GROWTH
            ask_gb = ask_gb if ceiling is None else min(ask_gb, ceiling)
            learned.record_ask(
                run.repo_url, learned.SLURM, needs_of(run.platform), ask_gb, safety=self.config.policy.safety
            )
            learn_floors(run.repo_url, oom_floors(found, task_items(state, shell, [one.job for one in found])), record)
        return found

    def progress(self, run: Run) -> str:
        """Where the run's current job is, from the cluster's run state and one ``squeue``."""
        return progress_text(where(run.sha, run.platform, self.machine, self.connect, policy=self.config.policy))

    def cancel(self, run: Run) -> list[str]:
        """``scancel`` every recorded round of *run* and any job of its name Slurm still holds."""
        return cancel_run(run.sha, run.platform, self.machine, self.connect, also=run.job_ids, aliases=run.job_aliases)

    def strays(self, held: Callable[[], set[str]]) -> list[str]:
        """Cancel this account's forge jobs whose name *held* does not return; the ids cancelled, one per array.

        Squeue is read BEFORE *held*: a run file is saved before its sbatch (``submitting``), so a job seen
        here whose name is not held has no run left -- never one submitted between the two reads.
        """
        shell = self.connect(self.machine.grants[0])
        jobs = [line.partition('|') for line in shell("squeue -h --me -o '%F|%j'", None).splitlines()]
        names = held()
        stray = sorted({job for job, _, name in jobs if _FORGE_JOB.fullmatch(name) and name not in names})
        if stray:
            scancel(shell, stray)
        return stray

    def stalled(self) -> list[Stalled]:
        """Cancel every RUNNING forge task past its stall bound (:func:`stall_of`); those cancelled, in queue order.

        A task's run dir is its Slurm work dir, so its manifest -- its items, their walls and stream -- is read
        from the task itself, never from a run file that may be gone. A task of a manifest without walls is
        never judged: nothing says what its tests may take.
        """
        shell = self.connect(self.machine.grants[0])
        lines = shell(_RUNNING, None).splitlines()
        now, manifests, found = float(lines[0]), {}, []
        for row in lines[1:]:
            job_id, name, elapsed, run_dir = row.split('|', 3)
            index = job_id.partition('_')[2]
            if not _FORGE_JOB.fullmatch(name) or not index.isdigit():
                continue
            if run_dir not in manifests:
                manifests[run_dir] = json.loads(shell(f'cat {remote_path(run_dir)}/manifest.json', None))
            start, stop = manifests[run_dir]['shards'][int(index)]
            items = manifests[run_dir]['items'][start:stop]
            tree = run_dir.rsplit('/', 2)[0]  # <tree>/.lab-hpc/<run>
            streams = ' '.join(sorted({remote_path(f'{tree}/{item["stream"]}') for item in items}))
            stamps = [float(w) for w in shell(f'stat -c %Y {streams} 2>/dev/null || true', None).split() if w.isdigit()]
            elapsed_s = parse_duration(elapsed)
            idle_s = now - max(stamps) if stamps else elapsed_s
            if why := stall_of(items, idle_s=idle_s, elapsed_s=elapsed_s):
                started = shell(f'grep -hF \'"start"\' {streams} 2>/dev/null || true', None)
                last = _last_started(started, {item.get('item') for item in items})
                found.append(Stalled(job_id, name, tree.rsplit('/', 1)[-1], last, why))
        if found:
            scancel(shell, [one.job_id for one in found])
        return found

    def withdraw(self, run: Run) -> list[str]:
        """Withdraw *run*'s pending tasks, keep its started ones; the ids still started."""
        return withdraw_pending(
            run.sha, run.platform, self.machine, self.connect, also=run.job_ids, aliases=run.job_aliases
        )

    def started_tasks(self, run: Run) -> Draining:
        """*run*'s started tasks, each priced as the packer priced it: its items' estimate times ``policy.safety``.

        The estimate is :meth:`lab_commons.compute.learned.Measured.estimate` over the learned table -- durations,
        floors, overheads, an unmeasured file at ``cost.seconds`` -- and ``policy.safety`` is the margin the plan
        turns it into a ``--time`` with (:func:`lab_commons.hpc.plan.plan`): one source, no new constant. A task
        of no round's manifest is priced at the prior alone. Start and now are both the cluster's clock.
        """
        state, shell = load_state(run.sha, run.platform, self.machine, self._runners())
        names = ','.join((job_name(run.sha, run.platform), *run.job_aliases))
        lines = shell(f"date +%s; squeue -h --me -n {names} -t {STARTED} -o '%i|%M'", None).split()
        now = float(lines[0])
        measured = learned.Measured.of(learned.learned(run.repo_url))
        cost, safety = self.config.cost, self.config.policy.safety
        manifests: dict[str, dict[str, Any]] = {}
        tasks = []
        for row in lines[1:]:
            job_id, _, elapsed = row.partition('|')
            base, _, index = job_id.partition('_')
            ids: list[list[str]] = []
            for one in state['rounds']:
                if base in {str(job) for job in one.get('job_ids', ())} and index.isdigit():
                    run_dir = one['run_dir']
                    if run_dir not in manifests:
                        manifests[run_dir] = json.loads(shell(f'cat {remote_path(run_dir)}/manifest.json', None))
                    start, stop = manifests[run_dir]['shards'][int(index)]
                    ids = [list(item.get('ids', ())) for item in manifests[run_dir]['items'][start:stop]]
            seconds = sum(measured.estimate(ids, cost)[0]) if ids else cost.seconds
            tasks.append(Started(job_id, now - parse_duration(elapsed), seconds * safety))
        return Draining(now, tuple(tasks))

    def cancel_tasks(self, run: Run, ids: list[str]) -> list[str]:
        """``scancel`` exactly these tasks of *run*, under the account holding its run state."""
        if ids:
            scancel(load_state(run.sha, run.platform, self.machine, self._runners())[1], ids)
        return list(ids)

    def standing(self) -> Standing:
        """Probe EVERY grant locally into one supply; the last day's use and the first grant's partitions and quota."""
        read = []
        for grant in self.machine.grants:
            snapshot = probe(self.connect(grant), grant.slurm_account)
            read.append((snapshot, snapshot.quota.default_qos))
        usage = self.quota()
        left = usage.files_left if usage is not None else None
        account = SlurmAccount(read, files=math.inf if left is None else left)
        supply = Engine({self.scope: [account, account_seats(cached())]}).available(self.scope)
        snapshot, qos = read[0]
        shell = self.connect(self.machine.grants[0])
        facts: dict[str, object] = {
            'quota_cpus': snapshot.quota.cpus,
            'qos': qos,
            'partitions': {name: part.max_minutes for name, part in snapshot.partitions.items() if part.up},
            'storage': storage_text(usage),
            'untagged': sum(s.usage[''].tasks for s, _ in read if '' in s.usage),  # hpc.slurm.stream_of
        }
        return Standing(supply, parse_usage(shell(USAGE_COMMAND, None)), facts)

    @property
    def scope(self) -> str:
        """What this account's supply is named: ``slurm:<user>``."""
        return f'slurm:{self.machine.grants[0].user}'


def slurm_cluster(root: Path, seat: ClusterAccount | None) -> SlurmCluster:
    """The cluster of *seat*, through the grants of its account only (another user's home is not this one's)."""
    if seat is None:
        msg = 'this box is not on a cluster (no sbatch); a cluster run advances only on its login node'
        raise ValueError(msg)
    machine = load_grants()
    if machine.session is None:  # an explicit $LC_HPC_SESSION wins; else the forge names its own stream
        machine = replace(machine, session=Session(FORGE_SESSION))
    grants = tuple(grant for grant in machine.grants if grant.user == seat.account)
    if not grants:
        msg = (
            f'no [[hpc.grant]] in {config_path()} has user = "{seat.account}" (the Slurm user this runs as); '
            'add one naming its slurm_account and share so a cluster part can be planned'
        )
        raise ValueError(msg)
    resolved = resolve(machine, lambda: read_allocation(root))
    return SlurmCluster(root, Machine(session=resolved.session, grants=grants), Config(), submitter())


def standing_of(build: Callable[[], Cluster]) -> tuple[Cluster | None, Standing | None, str]:
    """The Slurm side and its standing read locally, or why there is none (not on a cluster, no grant)."""
    try:
        slurm = build()
    except (RuntimeError, ValueError) as why:
        return None, None, str(why)
    try:
        return slurm, slurm.standing(), ''
    except (RuntimeError, OSError, ValueError) as why:  # Slurm did not answer: an empty supply claims nothing
        return slurm, Standing(unmeasured('slurm')), str(why)
