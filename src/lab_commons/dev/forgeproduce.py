"""ONE LOCAL PART, PRODUCED INLINE: run the claimed argv, stream it, hold its claim, release what it left.

Extracted from :mod:`lab_commons.dev.forgeserve` (its module docstring states the contract): the output
streams prefixed ``[platform]``; the loop wakes every *beat_s* (the host's tick period) and calls
*beat* with the time produced so far -- serve publishes its host card there, so a host busy for hours
still ticks and ``forge queue``'s STALE keeps meaning down; the claim is renewed on the FORGE's clock
every *renew_s* (counted in wakes) while the producer lives; a ref that moved on stops it
(``superseded by <sha>``) unless the new tip is
reach-equivalent (:mod:`lab_commons.dev.forgecarry`) -- then the run finishes and its part is also posted
on that tip, naming the sha it was judged at; a producer past
:data:`PRODUCE_WALL_S` is killed; and a claim it left ``pending`` is released as ``error`` with the reason
its exit code names -- or ``stopped`` when :mod:`lab_commons.dev.stoprun` stopped it on purpose. A LOAN
a reservation holder preempts (*yields* names the lease at a wake) has its process tree stopped and its
claim released ``preempted by reservation <id>``: OPEN again, re-queued, never an error.

THE PART IS JUDGED AT THE CLAIMED SHA, in a tree this producer owns (:mod:`lab_commons.dev.shatree`):
the declared argv (read at the sha) runs with that tree's own interpreter, cwd = the tree, and the tree
is removed once the run ended -- after its record and the streamed output are kept in the serving
checkout's ``parts/<sha>/`` (:func:`~lab_commons.dev.shatree.close_tree`). The serving checkout's HEAD
decides nothing. A tree that cannot be built spawns nothing, and the claim is released naming the step
that refused.

WHAT THE RUN MEASURED IS LEARNED (:mod:`lab_commons.compute.learned`). The producer's process tree is
sampled at every wake for its resident memory; a run that ended on its own (not superseded, not stopped)
records its peak, wall and held cpu-seconds under ``(platform, no needs)`` -- the box half of the one
demand table a Slurm run also writes. A box part holds the whole box, so its cpu-seconds are its wall
times the box's cores. A signalled exit's peak is a floor (:func:`~lab_commons.compute.learned.record_run`).

A PRODUCER RUNS BELOW NORMAL OS PRIORITY (:func:`below_normal`, user ruling 2026-10-13): a light run is
admitted beside a heavy part (:mod:`lab_commons.dev.boxwait`), and the scheduler keeps it responsive.
"""

from __future__ import annotations

import contextlib
import dataclasses
import math
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.learned import Run, record_run
from lab_commons.dev.bounded import logical_cores
from lab_commons.dev.forge import fetch_origin
from lab_commons.dev.forgecarry import SETTLED, carry_target, equivalent
from lab_commons.dev.forgeclaim import Work, forge_now
from lab_commons.dev.forgeschedule import tip_of
from lab_commons.dev.forgestatus import Status, status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import origin_url, part_context, parts_of
from lab_commons.dev.producer import ProducerExit, preempted, producing, release_reason
from lab_commons.dev.servelock import was_stopped
from lab_commons.dev.shatree import TreeFailed, close_tree, open_tree
from lab_commons.dev.stoprun import declared_signatures, process_table, stop
from lab_commons.proc import process_tree, working_set_bytes

__all__ = ['PRODUCE_WALL_S', 'Produced', 'produce']

#: How long a produced part may run before it is called hung, in seconds.
PRODUCE_WALL_S: Final = 24 * 3600


@dataclass(frozen=True)
class Produced:
    """One claimed local part and what producing it did."""

    ref: str
    sha: str
    platform: str
    argv: tuple[str, ...]
    returncode: int


#: Bytes in one gibibyte.
_GB: Final = 1024.0**3


def tree_gb(pid: int) -> float | None:
    """Resident GB of *pid*'s whole process tree now, or ``None`` when nothing of it could be read."""
    readings = [working_set_bytes(one) for one in process_tree(pid)]
    known = [r for r in readings if r is not None]
    return sum(known) / _GB if known else None


def learn_box_run(root: Path, item: Work, run: Run, *, killed: bool) -> None:
    """Record one finished box run of *root*'s repository under ``(platform, no needs)``."""
    record_run(origin_url(root), item.platform, (), run, killed=killed)


def _pump(stream: Iterable[str], platform: str, say: Callable[[str], None], heard: list[str]) -> None:
    for line in stream:
        heard.append(line)
        say(f'[{platform}] {line.rstrip()}')


def produce(
    root: Path,
    item: Work,
    *,
    client: Callable[[Path], Client],
    spawn: Callable[..., Any],
    clock: Callable[[], datetime],
    say: Callable[[str], None],
    lease: timedelta,
    renew_s: float,
    fetch: Callable[[Path], None] = fetch_origin,
    beat_s: float | None = None,
    beat: Callable[[timedelta], object] = lambda _elapsed: None,
    sample: Callable[[int], float | None] = tree_gb,
    learn: Callable[..., object] = learn_box_run,
    yields: Callable[[], int] = lambda: 0,
) -> Produced:
    """Run one local part's argv in its tree at the sha, streaming it and holding its claim; release what it left.

    The tree is built first and removed last (:mod:`lab_commons.dev.shatree`). At each heartbeat the ref is
    re-read from ``origin``: a ref that moved on stops the producer, and its claim is released ``superseded by <sha>``.
    """
    try:
        tree = open_tree(root, item.sha)
    except TreeFailed as failed:
        _post(client(root), item, 'error', f'released: no tree at {item.sha[:12]} -- {failed}', say)
        say(f'[{item.platform}] {close_tree(root, item.sha)}')
        return Produced(item.ref, item.sha, item.platform, item.argv, ProducerExit.INCONCLUSIVE)
    heard: list[str] = []  # the run's log, kept beside its record in the serving checkout by close_tree
    try:
        return _run(root, item, (str(tree.python), *item.argv), tree.path, client=client, spawn=spawn, clock=clock,
                    say=say, lease=lease, renew_s=renew_s, fetch=fetch, heard=heard,
                    beat_s=renew_s if beat_s is None else beat_s, beat=beat, sample=sample, learn=learn,
                    yields=yields)  # fmt: skip
    finally:
        say(f'[{item.platform}] {close_tree(root, item.sha, log="".join(heard))}')


def _run(
    root: Path,
    item: Work,
    argv: tuple[str, ...],
    tree: Path,
    *,
    client: Callable[[Path], Client],
    spawn: Callable[..., Any],
    clock: Callable[[], datetime],
    say: Callable[[str], None],
    lease: timedelta,
    renew_s: float,
    fetch: Callable[[Path], None],
    heard: list[str],
    beat_s: float,
    beat: Callable[[timedelta], object],
    sample: Callable[[int], float | None],
    learn: Callable[..., object],
    yields: Callable[[], int],
) -> Produced:
    context = part_context(item.platform)
    say(f'[{item.platform}] start in {tree.name}: {" ".join(argv)}')
    proc = below_normal(
        spawn,
        list(argv),
        cwd=tree,
        env=os.environ | producing(context, item.sha),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    pump = threading.Thread(target=_pump, args=(proc.stdout, item.platform, say, heard), daemon=True)
    pump.start()
    started = clock()
    superseded = ''
    displaced = 0  # the reservation whose holder preempted this loan
    wake_s = min(renew_s, beat_s)
    renew_every = max(1, math.ceil(renew_s / wake_s - 1e-9))  # wakes per renewal
    wakes = 0
    peak: float | None = None
    while True:
        try:
            returncode = proc.wait(timeout=wake_s)
            break
        except subprocess.TimeoutExpired:
            if (clock() - started).total_seconds() > PRODUCE_WALL_S:
                proc.kill()
                returncode = proc.wait()
                say(f'[{item.platform}] killed: past the {PRODUCE_WALL_S} s wall')
                break
            if proc.pid is not None and (now := sample(proc.pid)) is not None:
                peak = max(peak or 0.0, now)
            superseded, displaced, why = _interrupted(root, item, fetch, yields)
            if why:
                _halt(root, proc)
                returncode = proc.wait()
                say(f'[{item.platform}] stopped: {why}')
                break
            wakes += 1
            beat(clock() - started)
            if wakes % renew_every == 0:
                _renew(client(root), item, lease, say)
    pump.join(timeout=5)
    say(f'[{item.platform}] exit={returncode}')
    stopped = proc.pid is not None and was_stopped(proc.pid)  # by stoprun, on purpose
    if peak is not None and not superseded and not stopped and not displaced:
        wall_s = max(1.0, (clock() - started).total_seconds())
        learn(root, item, Run(peak, wall_s * logical_cores(), wall_s), killed=returncode < 0)
    posts = [status for status in status_history(client(root), item.sha) if status.context == context]
    if superseded or displaced or (posts and posts[-1].state == 'pending'):
        reason = 'stopped' if stopped else release_reason(returncode)
        reason = f'superseded by {superseded[:12]}' if superseded else reason
        reason = preempted(displaced) if displaced else reason
        _post(client(root), item, 'error', reason, say)
    elif posts and posts[-1].state in SETTLED:
        _carry(root, client(root), item, posts[-1], say)
    return Produced(item.ref, item.sha, item.platform, argv, returncode)


def _interrupted(
    root: Path, item: Work, fetch: Callable[[Path], None], yields: Callable[[], int]
) -> tuple[str, int, str]:
    """``(tip it was superseded by, lease that preempted it, why)`` at a wake; ``('', 0, '')`` to keep running."""
    fetch(root)
    tip = tip_of(root, item.ref)
    if tip and tip != item.sha and not equivalent(root, item.sha, tip):
        return tip, 0, f'{item.ref} moved on to {tip[:12]}'
    displaced = yields()
    return '', displaced, preempted(displaced) if displaced else ''


def _halt(root: Path, proc: subprocess.Popen[str]) -> None:
    """Stop *proc*'s whole tree through :mod:`lab_commons.dev.stoprun`; a pid it refuses is killed alone."""
    code, _ = stop(proc.pid, process_table(), dry_run=False, signatures=declared_signatures(root))
    if code:
        proc.kill()


def _renew(client: Client, item: Work, lease: timedelta, say: Callable[[str], None]) -> None:
    """The heartbeat: the same claim, until the FORGE's time plus the lease; an unheld item has none."""
    if item.holder is None:
        return
    try:
        renewed = dataclasses.replace(item.holder, until=forge_now(client) + lease)
    except (ForgeCallFailed, OSError) as failed:
        say(f'[{item.platform}] could not read the forge clock to renew: {failed}')
        return
    _post(client, item, 'pending', renewed.description(), say)


def _carry(root: Path, client: Client, item: Work, verdict: Status, say: Callable[[str], None]) -> None:
    """Post *verdict* -- the part judged at the item's sha -- also on the ref's tip when it is reach-equivalent."""
    target = carry_target(root, client, ref=item.ref, sha=item.sha, platform=item.platform)
    part = parts_of([verdict])[0].get(item.platform)
    if not target or part is None:
        return
    carried = dataclasses.replace(part, carried=item.sha[:12])
    try:
        status_post(client, target, context=verdict.context, state=verdict.state, description=carried.description(),
                    target_url=verdict.url)  # fmt: skip
    except ForgeCallFailed as failed:
        say(f'[{item.platform}] could not carry to {target[:12]}: {failed}')
    else:
        say(f'[{item.platform}] carried {verdict.state} to {target[:12]}: only inert paths changed')


def _post(client: Client, item: Work, state: str, description: str, say: Callable[[str], None]) -> None:
    try:
        status_post(client, item.sha, context=part_context(item.platform), state=state, description=description)
    except ForgeCallFailed as failed:  # a missed heartbeat is not a dead producer; say so and keep going
        say(f'[{item.platform}] could not post {state}: {failed}')
    else:
        say(f'[{item.platform}] {state}: {description}')


#: The POSIX niceness a producer runs at: below normal, so an interactive run keeps the scheduler's favour.
BELOW_NORMAL_NICE: Final = 10


def below_normal(spawn: Callable[..., Any], argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401 -- spawn's own
    """Start *argv* through *spawn* at BELOW-NORMAL priority, which its descendants inherit.

    Windows: ``BELOW_NORMAL_PRIORITY_CLASS`` at creation. POSIX has no creation flag (``preexec_fn`` is
    unsafe beside serve's threads), so a real child is reniced at once, before it spawns workers; a
    renice the OS refuses (a parent already nicer, a child already gone) leaves it where it is.
    """
    if sys.platform == 'win32':
        flags = kwargs.pop('creationflags', 0) | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return spawn(argv, creationflags=flags, **kwargs)
    proc = spawn(argv, **kwargs)
    if isinstance(proc, subprocess.Popen):
        with contextlib.suppress(OSError):
            os.setpriority(os.PRIO_PROCESS, proc.pid, BELOW_NORMAL_NICE)
    return proc
