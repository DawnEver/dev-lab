"""THE SLURM SIDE OF A CLUSTER RUN -- :class:`lab_commons.dev.forgerunstate.Cluster` through this login node's shell.

Everything here runs ON the cluster login node (``lab_commons.hpc``'s own shell, never ``ssh``):
submitting and gathering a run, where its jobs stand (:func:`progress_text`, the phrase its claim
carries), cancelling a run no limit lets start, the outcomes a run CARRIES from the nearest earlier runs of its env --
finished records and the finished shards of superseded ones (:mod:`lab_commons.dev.forgecarry`) -- and the
account's STANDING read locally each tick -- its supply
(cpu, memory, the QOS's remaining submissions over every grant and the machine file's declared tools,
:func:`lab_commons.compute.probe.account`, and the home's FILE headroom read by
:func:`lab_commons.dev.diskusage.read_usage`), the last day's core-hours per run from ``sacct``,
and the partitions, quota and storage a host card publishes. An unreadable quota is stated on the card
(``storage: unread``) and leaves files uncapped; a home at its file limit claims nothing and the card says so.
"""

from __future__ import annotations

import math
import shlex
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lab_commons.box import declared_seats
from lab_commons.compute import learned
from lab_commons.compute import probe as supply_probe
from lab_commons.compute.model import Resources, Supply
from lab_commons.config import config_path
from lab_commons.dev.diskusage import Usage, read_usage, storage_text
from lab_commons.dev.forgecarry import carry_from, read_by
from lab_commons.dev.forgerecords import read_named
from lab_commons.dev.forgerunstate import Cluster, Run, Standing, Unrecorded
from lab_commons.dev.forgeschedule import USAGE_COMMAND, parse_usage
from lab_commons.dev.forgework import ForgeCallFailed, client_for
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.allocation import RECORD, session_for
from lab_commons.hpc.builds import builds_at
from lab_commons.hpc.cluster import Runner, Unreachable, probe, submitter
from lab_commons.hpc.config import Config
from lab_commons.hpc.grants import Grant, Machine, Session, load_grants
from lab_commons.hpc.needsets import needs_of, vocabulary_at
from lab_commons.hpc.progress import Progress, held_by_a_limit, where
from lab_commons.hpc.records import held_cells, run_shas
from lab_commons.hpc.run import NoRoom, job_name, load_state, submit_run
from lab_commons.hpc.shell import RunSpec
from lab_commons.hpc.slurm import FORGE_SESSION
from lab_commons.hpc.watch import PENDING, settle

__all__ = ['SlurmCluster', 'progress_text', 'slurm_cluster', 'standing_of']


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
        finished shards stand as they are (:func:`lab_commons.dev.forgecarry.carry_from`).

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

    def progress(self, run: Run) -> str:
        """Where the run's current job is, from the cluster's run state and one ``squeue``."""
        return progress_text(where(run.sha, run.platform, self.machine, self.connect, policy=self.config.policy))

    def started(self, run: Run) -> bool:
        """Whether any task of *run* started: a retry round exists (round 0 ran), or a task runs or ended."""
        state, _ = load_state(run.sha, run.platform, self.machine, self._runners())
        if 'record' in state or len(state['rounds']) > 1:
            return True
        at = where(run.sha, run.platform, self.machine, self.connect, policy=self.config.policy)
        return at.finished or at.running > 0 or at.done > 0

    def cancel(self, run: Run) -> list[str]:
        """``scancel`` every recorded round of *run* and any job of its name Slurm still holds."""
        ids = sorted({*self.submitted(run), *run.job_ids, *self.orphans(run)})
        if ids:
            self.connect(self.machine.grants[0])(f'scancel {shlex.join(ids)}', None)
        return ids

    def standing(self) -> Standing:
        """Probe EVERY grant locally into one supply; the last day's use and the first grant's partitions and quota."""
        read = []
        for grant in self.machine.grants:
            snapshot = probe(self.connect(grant), grant.slurm_account)
            read.append((snapshot, snapshot.quota.default_qos))
        usage = self.quota()
        left = usage.files_left if usage is not None else None
        supply = supply_probe.account(
            self.scope, read, seats=declared_seats(), files=math.inf if left is None else left
        )
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


def with_allocation(machine: Machine, read: Callable[[], bytes | None]) -> Machine:
    """*machine* with its session's share from the one allocation record (:mod:`lab_commons.hpc.allocation`).

    A forge that cannot be read leaves the share derived -- the default, never a guessed override.
    """
    if machine.session is None:
        return machine
    try:
        held = read()
    except (ForgeCallFailed, OSError, ValueError):
        held = None
    text = None if held is None else held.decode('utf-8')
    return replace(machine, session=session_for(machine.session.name, text, now=datetime.now(UTC)))


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
    resolved = with_allocation(machine, lambda: read_named(client_for(root), RECORD))
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
        return slurm, Standing(Supply('slurm', Resources())), str(why)
