"""ADVANCING THE CLUSTER RUNS one tick: each run's next step, results before submits, bounded by the tick's period.

Called by :func:`dev_lab.dev.forgeserve.serve` every tick and by ``forge serve --submit`` for one run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path

from lab_commons.hpc.account import ClusterAccount

from dev_lab.dev import forgerun, forgerunstate, forgesubmit
from dev_lab.dev.forgealarm import (
    RUN,
    Alarm,
)
from dev_lab.dev.forgeclaim import Claim, forge_now
from dev_lab.dev.forgework import Client
from dev_lab.dev.platformparts import run_tag
from dev_lab.dev.tickholder import phase
from dev_lab.supervise.notice import Context


def advance_runs(
    root: Path,
    runs: Sequence[forgerunstate.Run],
    *,
    client: Callable[[Path], Client],
    machine: str,
    seat: ClusterAccount | None,
    lease: timedelta,
    slurm: forgerunstate.Cluster | None,
    why: str,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
    beat: Callable[[], None] = lambda: None,
    spent: Callable[[], bool] = lambda: False,
    submit: Callable[[forgerunstate.Run], str] | None = None,
) -> list[str]:
    """Advance every run one tick; the shas still in flight. A run that cannot advance waits and alarms.

    A run's step can be slow (a gather, the routing and the post of a 55k-test record, a submit's prep), so
    the host card is published (*beat*) before each, and once the runs' own period is *spent* (counted from
    the first run, so the rounds before cannot spend it) the runs not yet reached wait for the next tick. A
    tick always advances at least one, and *runs* arrive least recently advanced first
    (:func:`forgerunstate.live`), so the runs one tick leaves are the first the next reaches: every run is
    reached within as many ticks as there are runs. The runs are bounded by one period plus one step, and
    ``forge queue``'s STALE keeps meaning down.

    RESULTS BEFORE SUBMITS (Ada 2026-11-07): a submit builds and collects on the login node -- over an hour
    cold -- so a finished run never waits behind a collection in its own tick (:func:`forgesubmit.hand_off`).
    """
    if not runs:
        return []
    built = client(root)
    me = Claim(machine, built.whoami(), forge_now(built) + lease, str(seat) if seat else '')
    if slurm is None:  # not on a cluster, or no grant for this account
        for run in runs:
            alarm(
                Alarm(
                    RUN,
                    run.repo_url,
                    f'the cluster run of {run.sha[:12]} cannot advance',
                    why,
                    context=Context(sha=run.sha),
                )
            )
        say(f'[serve] no cluster to advance {len(runs)} run(s) on: {why}')
        return [run.sha for run in runs]
    runs, left = forgesubmit.hand_off(runs, submit, say)
    for at, run in enumerate(runs):
        if at and spent():
            waiting = [one.sha for one in runs[at:]]
            say(f'[serve] the tick ran past its period: {" ".join(sha[:12] for sha in waiting)} wait for the next')
            return left + waiting
        beat()
        phase(f'advancing the cluster run of {run.sha[:12]} ({run.phase})')
        try:
            after = forgerun.advance(
                root, run, client=built, me=me, lease=lease, cluster=slurm, say=say, alarm=alarm,
            )  # fmt: skip
        except (RuntimeError, OSError, ValueError) as stuck:  # Slurm or the build refused: the run waits
            alarm(
                Alarm(
                    RUN,
                    run.repo_url,
                    f'the cluster run of {run.sha[:12]} cannot advance',
                    str(stuck),
                    context=Context(sha=run.sha),
                )
            )
            say(f'{run_tag(run.platform, run.sha)}: cannot advance: {stuck}')
            after = run
        if after is not None:
            forgerunstate.touch(after)
            left.append(after.sha)
    return left
