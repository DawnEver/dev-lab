"""THE SLURM SIDE OF A CLUSTER RUN -- :class:`lab_commons.dev.forgerun.Cluster` through this login node's shell.

Everything here runs ON the cluster login node (``lab_commons.hpc``'s own shell, never ``ssh``):
submitting and gathering a run, where its jobs stand (:func:`progress_text`, the phrase its claim
carries), cancelling a superseded run, and the account's STANDING read locally each tick -- headroom
(free cores of the grant, the QOS's remaining submissions), the last day's core-hours per run from
``sacct``, and the partitions and quota a host card publishes.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lab_commons.config import config_path
from lab_commons.dev.forgerun import Cluster, Run, Standing
from lab_commons.dev.forgeschedule import USAGE_COMMAND, Headroom, parse_usage
from lab_commons.hpc import learned
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.builds import builds_at
from lab_commons.hpc.cluster import Runner, probe, submitter
from lab_commons.hpc.config import Config
from lab_commons.hpc.grants import Grant, Machine, load_grants, workstation
from lab_commons.hpc.plan import headroom
from lab_commons.hpc.platforms import table_at
from lab_commons.hpc.progress import Progress, where
from lab_commons.hpc.run import load_state, submit_run
from lab_commons.hpc.shell import RunSpec
from lab_commons.hpc.watch import PENDING, settle

__all__ = ['SlurmCluster', 'progress_text', 'slurm_cluster', 'standing_of']


def progress_text(where_: Progress) -> str:
    """The phrase a status description carries: ``queued 3/93``, ``running 40/93 done 12/93``, ``gathering``."""
    if where_.finished:
        return 'gathering'
    if where_.running == 0 and where_.done == 0:
        return f'queued {where_.pending}/{where_.shards}'
    return f'running {where_.running}/{where_.shards} done {where_.done}/{where_.shards}'


@dataclass(frozen=True)
class SlurmCluster:
    """:class:`Cluster` through ``lab_commons.hpc`` and this login node's own shell (:func:`slurm_cluster`)."""

    root: Path
    machine: Machine
    config: Config
    connect: Callable[[Grant], Runner]

    def _runners(self) -> dict[tuple[str, str], Runner]:
        return {grant.account: self.connect(grant) for grant in self.machine.grants}

    def submitted(self, run: Run) -> list[str]:
        """The job ids of every round ``hpc`` recorded for *run*'s sha; ``[]`` when it recorded none."""
        try:
            state, _ = load_state(run.sha, self.machine, self._runners())
        except RuntimeError:  # no state.json: nothing was submitted, or it died before writing one
            return []
        return [one['job_id'] for one in state['rounds']]

    def orphans(self, run: Run) -> list[str]:
        """Jobs Slurm holds under this account with *run*'s job name (``run-<sha12>``)."""
        shell = self.connect(self.machine.grants[0])
        return shell(f'squeue -h --me -n run-{run.sha[:12]} -o %i', None).split()

    def submit(self, run: Run) -> list[str]:
        """Fetch, build, collect, plan and submit round 0 (:func:`lab_commons.hpc.run.submit_run`)."""
        spec = RunSpec(
            sha=run.sha,
            repo_url=run.repo_url,
            collect=run.collect,
            table=table_at(self.root, run.sha),
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
        )
        return [one['job_id'] for one in state['rounds']]

    def tree(self, run: Run) -> Path:
        """``~/ci/trees/<sha>`` in this account's home (:attr:`lab_commons.hpc.shell.RunSpec.tree`)."""
        return Path(f'~/ci/trees/{run.sha}').expanduser()

    def gather(self, run: Run) -> Path | None:
        """One :func:`lab_commons.hpc.watch.settle` without waiting: the record it wrote, or ``None`` while pending."""
        output = Path(run.output)
        if settle([run.sha], self.machine, self.connect, self.config, output, sleep=None) == PENDING:
            return None
        records = sorted(output.glob(f'run-{run.sha}-{run.platform}-*.json.gz'), key=lambda path: path.stat().st_mtime)
        if not records:
            msg = f'the run of {run.sha[:12]} ended without a record in {output}; its lines above say why'
            raise RuntimeError(msg)
        return records[-1]

    def progress(self, run: Run) -> str:
        """Where the run's current job is, from the cluster's run state and one ``squeue``."""
        return progress_text(where(run.sha, self.machine, self.connect, policy=self.config.policy))

    def cancel(self, run: Run) -> list[str]:
        """``scancel`` every recorded round of *run* and any job of its name Slurm still holds."""
        ids = sorted({*self.submitted(run), *run.job_ids, *self.orphans(run)})
        if ids:
            self.connect(self.machine.grants[0])(f'scancel {shlex.join(ids)}', None)
        return ids

    def standing(self) -> Standing:
        """Probe the first grant locally: headroom (cores, QOS submissions), the last day's use, partitions."""
        grant = self.machine.grants[0]
        shell = self.connect(grant)
        snapshot = probe(shell, grant.slurm_account)
        qos = snapshot.quota.default_qos
        room = Headroom(headroom(snapshot, grant.cpus, self.machine.workstation), snapshot.quota.submit_room(qos))
        facts: dict[str, object] = {
            'quota_cpus': snapshot.quota.cpus,
            'qos': qos,
            'partitions': {name: part.max_minutes for name, part in snapshot.partitions.items() if part.up},
        }
        return Standing(room, parse_usage(shell(USAGE_COMMAND, None)), facts)


def slurm_cluster(root: Path, seat: ClusterAccount | None) -> SlurmCluster:
    """The cluster of *seat*, through the grants of its account only (another user's home is not this one's)."""
    if seat is None:
        msg = 'this box is not on a cluster (no sbatch); a cluster run advances only on its login node'
        raise ValueError(msg)
    grants = tuple(grant for grant in load_grants().grants if grant.user == seat.account)
    if not grants:
        msg = (
            f'no [[hpc.grant]] in {config_path()} has user = "{seat.account}" (the Slurm user this runs as); '
            'add one naming its slurm_account and share so a cluster part can be planned'
        )
        raise ValueError(msg)
    return SlurmCluster(root, Machine(workstation=workstation(), grants=grants), Config(), submitter())


def standing_of(build: Callable[[], Cluster]) -> tuple[Cluster | None, Standing | None, str]:
    """The Slurm side and its standing read locally, or why there is none (not on a cluster, no grant)."""
    try:
        slurm = build()
    except (RuntimeError, ValueError) as why:
        return None, None, str(why)
    try:
        return slurm, slurm.standing(), ''
    except (RuntimeError, OSError, ValueError) as why:  # Slurm did not answer: no headroom is claimed on
        return slurm, Standing(Headroom(cores=0)), str(why)
