"""ONE LOCAL PART, PRODUCED INLINE: run the claimed argv, stream it, hold its claim, release what it left.

Extracted from :mod:`lab_commons.dev.forgeserve` (its module docstring states the contract): the output
streams prefixed ``[platform]``; the loop wakes every *beat_s* (the host's tick period) and calls
*beat* with the time produced so far -- serve publishes its host card there, so a host busy for hours
still ticks and ``forge queue``'s STALE keeps meaning down; the claim is renewed on the FORGE's clock
every *renew_s* (counted in wakes) while the producer lives. A PART UNDER TEST IS NOT SUPERSEDED (user
ruling 2026-10-13): a ref that moved on never stops it -- newer pushes queue behind it and are tested at the
next tip -- and when the tip is reach-equivalent (:mod:`lab_commons.dev.forgecarry`) its part is also posted
on that tip, naming the sha it was judged at; a claim it left ``pending`` is released as ``error`` with
the reason the box's record names, else its exit code's
(:func:`~lab_commons.dev.producer.box_release_reason`) -- or ``stopped`` when :mod:`lab_commons.dev.stoprun`
stopped it on purpose.

THE PRODUCER RUNS IN THE BOX (:func:`boxed`, :func:`lab_commons.box.command`): admitted on this machine's
box ledger at exactly the demand the tick admitted it at (:func:`lab_commons.compute.learned.box_demand`),
and killed by the box past that memory or its wall (a part's :data:`~lab_commons.compute.learned.BOX_WALL_S`,
a request's declared ``wall_h``). A box with no
room releases the claim retryable; a kill is released naming it -- both read from the box's record
beside the run's tree, never from the exit code, which is the producer's own. A REQUEST (context
``request/<n>``) is the same job on the same path; its producer knows nothing of the forge, so its result
is SETTLED here from the exit code (:func:`lab_commons.dev.forgerequest.settle`).

THE PART IS JUDGED AT THE CLAIMED SHA, in a tree this producer owns (:mod:`lab_commons.dev.shatree`):
the declared argv (read at the sha) runs with that tree's own interpreter, cwd = the tree, and the tree
is removed once the run ended -- after its record and the streamed output are kept in the serving
checkout's ``parts/<sha>/`` (:func:`~lab_commons.dev.shatree.close_tree`). The serving checkout's HEAD
decides nothing. A tree that cannot be built spawns nothing, and the claim is released naming the step
that refused.

WHAT THE RUN MEASURED IS LEARNED (:mod:`lab_commons.compute.learned`). The producer's process tree is
sampled at every wake for its resident memory and its cpu-seconds (:class:`lab_commons.proccpu.TreeCpu`:
user + system over every process of the tree, a child that exited keeping what it was last seen using);
a run that ended on its own (not stopped) records its peak, wall and MEASURED cpu-seconds
under ``(its producer, its need-set)`` -- ``local`` for a part, a request's declared name -- the box half
of the one demand table a Slurm run also writes. A run the box killed records its peak as a
floor (:func:`~lab_commons.compute.learned.record_run`).

A PRODUCER RUNS BELOW NORMAL OS PRIORITY (:func:`below_normal`, user ruling 2026-10-13): an interactive
run admitted beside it on the box ledger keeps the scheduler's favour.
"""

from __future__ import annotations

import contextlib
import dataclasses
import math
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.box import GB, Capacity, Demand, Outcome, command, read_ended
from lab_commons.compute.learned import Run, record_run
from lab_commons.dev.forge import fetch_origin
from lab_commons.dev.forgecarry import SETTLED, carry_target
from lab_commons.dev.forgeclaim import Work, forge_now
from lab_commons.dev.forgelabels import LabelMissing
from lab_commons.dev.forgerequest import CONTEXT_PREFIX, result, settle
from lab_commons.dev.forgestatus import Status, status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import origin_url, parts_of
from lab_commons.dev.producer import ProducerExit, box_release_reason, producing, release_reason
from lab_commons.dev.servelock import was_stopped
from lab_commons.dev.shatree import TreeFailed, close_tree, open_tree, record_manifest
from lab_commons.hpc.needsets import needs_of
from lab_commons.proc import process_tree, working_set_bytes
from lab_commons.proccpu import TreeCpu

__all__ = ['BOX_QUEUE_S', 'Produced', 'boxed', 'produce']

#: How long a producer waits for its box claim, in seconds: the tick admitted it against the box ledger, so
#: only a run admitted in between can be in its way -- then the claim is released and retried next tick.
BOX_QUEUE_S: Final = 60.0


@dataclass(frozen=True)
class Produced:
    """One claimed local part and what producing it did."""

    ref: str
    sha: str
    platform: str
    argv: tuple[str, ...]
    returncode: int
    stopped: bool = False  # by :mod:`lab_commons.dev.stoprun`, on purpose


#: Bytes in one gibibyte.
_GB: Final = 1024.0**3


def tree_gb(pid: int) -> float | None:
    """Resident GB of *pid*'s whole process tree now, or ``None`` when nothing of it could be read."""
    readings = [working_set_bytes(one) for one in process_tree(pid)]
    known = [r for r in readings if r is not None]
    return sum(known) / _GB if known else None


def learn_box_run(root: Path, item: Work, run: Run, *, killed: bool) -> None:
    """Record one finished box run of *root*'s repository under ``(its producer, its need-set)``.

    A part's producer is ``local``; a request's is its declared NAME, so it never shares a test part's record.
    """
    record_run(origin_url(root), item.producer, needs_of(item.platform), run, killed=killed)


def boxed(item: Work, argv: Sequence[str], capacity: Capacity, outcome: Path) -> list[str]:
    """*argv* run through the box at the demand the tick admitted *item* at, recording how it ended at *outcome*.

    An item claimed with no demand declares the whole *capacity*, as an unmeasured box part does
    (:func:`~lab_commons.compute.learned.box_demand`).
    """
    asked = item.demand or {'cpu': capacity.cpu, 'mem_gb': capacity.mem_bytes / GB}
    seats = {name: 1 for name in needs_of(item.platform) if name in capacity.seats}
    cpu = max(1, min(math.floor(capacity.cpu), int(asked['cpu'])))
    demand = Demand(cpu=cpu, mem_gb=asked['mem_gb'], wall_s=item.wall_s, seats=seats)
    what = f'{item.context}@{item.sha[:12]}'
    return command(argv, demand, BOX_QUEUE_S, key=item.context, what=what, outcome=outcome, fingerprint=item.sha)


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
    meter: Callable[[int], Callable[[], float | None]] = lambda pid: TreeCpu(pid).sample,
    capacity: Callable[[], Capacity] | None = None,
) -> Produced:
    """Run one local part's argv in its tree at the sha, streaming it and holding its claim; release what it left.

    The tree is built first and removed last (:mod:`lab_commons.dev.shatree`); the argv runs in the box
    (:func:`boxed`, sized against *capacity*, default this box's). At each heartbeat the ref is
    renewed; a ref that moved on never stops the producer -- *fetch* reads the tip once, at the end, to carry to.
    """
    try:
        tree = open_tree(root, item.sha, item.context)
    except TreeFailed as failed:
        _post(client(root), item, 'error', f'released: no tree at {item.sha[:12]} -- {failed}', say)
        say(f'[{item.platform}] {close_tree(root, item.sha, item.context)}')
        return Produced(item.ref, item.sha, item.platform, item.argv, ProducerExit.INCONCLUSIVE)
    heard: list[str] = []  # the run's log, kept beside its record in the serving checkout by close_tree
    try:
        argv = (str(tree.python), *item.argv)
        record = tree.path.with_name(f'{tree.path.name}.outcome.json')  # beside the run's tree, read and removed
        held = boxed(item, argv, (capacity or Capacity.read)(), record)
        return _run(root, item, (argv, held), (tree.path, record), client=client, spawn=spawn, clock=clock,
                    say=say, lease=lease, renew_s=renew_s, fetch=fetch, heard=heard,
                    beat_s=renew_s if beat_s is None else beat_s, beat=beat, sample=sample, learn=learn,
                    meter=meter)  # fmt: skip
    finally:
        say(f'[{item.platform}] {close_tree(root, item.sha, item.context, log="".join(heard))}')


def _run(
    root: Path,
    item: Work,
    argvs: tuple[tuple[str, ...], list[str]],
    where: tuple[Path, Path],
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
    meter: Callable[[int], Callable[[], float | None]],
) -> Produced:
    argv, held = argvs  # what the part runs, and that argv run through the box
    tree, record = where  # the run's tree, and where the box records how it ended
    context = item.context
    say(f'[{item.platform}] start in {tree.name}: {" ".join(argv)}')
    proc = below_normal(
        spawn,
        held,
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
    wake_s = min(renew_s, beat_s)
    renew_every = max(1, math.ceil(renew_s / wake_s - 1e-9))  # wakes per renewal
    wakes = 0
    usage = _Usage(meter(proc.pid) if proc.pid is not None else lambda: None)
    while True:
        try:
            returncode = proc.wait(timeout=wake_s)
            break
        except subprocess.TimeoutExpired:
            usage.wake(sample(proc.pid) if proc.pid is not None else None)
            wakes += 1
            beat(clock() - started)
            if wakes % renew_every == 0:
                _renew(client(root), item, lease, say)
    pump.join(timeout=5)
    say(f'[{item.platform}] exit={returncode}')
    stopped = proc.pid is not None and was_stopped(proc.pid)  # by stoprun, on purpose
    ended = read_ended(record)
    record.unlink(missing_ok=True)
    boxed_out = box_release_reason(ended)  # the box's decision, from its record: never from the exit code
    if usage.peak is not None and usage.cpu_s > 0 and not stopped:
        wall_s = max(1.0, (clock() - started).total_seconds())
        learn(
            root,
            item,
            Run(usage.peak, usage.cpu_s, wall_s),
            killed=(isinstance(ended, Outcome) and ended.killed) or returncode < 0,
        )
    posts = [status for status in status_history(client(root), item.sha) if status.context == context]
    if context.startswith(CONTEXT_PREFIX) and posts and posts[-1].state == 'pending':
        _settle(
            client(root),
            item,
            (returncode, boxed_out),
            (''.join(heard), record_manifest(root, item.sha, item.context)),
            say,
        )  # a request: its producer posts nothing
    elif posts and posts[-1].state == 'pending':
        reason = 'stopped' if stopped else boxed_out or release_reason(returncode)
        _post(client(root), item, 'error', reason, say)
    elif posts and posts[-1].state in SETTLED:
        fetch(root)
        _carry(root, client(root), item, posts[-1], say)
    return Produced(item.ref, item.sha, item.platform, argv, returncode, stopped=stopped)


class _Usage:
    """What one producer's tree has used: its peak GB and MEASURED cpu-seconds."""

    def __init__(self, cpu: Callable[[], float | None]) -> None:
        self._cpu = cpu
        self.peak: float | None = None
        self.cpu_s = 0.0

    def wake(self, gb: float | None) -> None:
        """Read the tree once: keep its peak and cpu-seconds."""
        self.peak = self.peak if gb is None else max(self.peak or 0.0, gb)
        self.cpu_s = max(self.cpu_s, self._cpu() or 0.0)


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
        say(f'[{item.platform}] carried {verdict.state} to {target[:12]}: no test footprint reaches the diff')


def _settle(
    client: Client,
    item: Work,
    ended: tuple[int, str | None],
    made: tuple[str, tuple[str, tuple[tuple[str, str], ...]]],
    say: Callable[[str], None],
) -> None:
    """A request's result -- the box's release when it ended the run, else the exit code's -- commented, then posted."""
    returncode, boxed_out = ended
    log, record = made  # the run's log, and its record (shatree.record_manifest)
    host = (item.holder.machine or item.holder.login) if item.holder else '-'
    state, description = ('error', boxed_out) if boxed_out else result(returncode, host)
    try:
        number = int(item.context.removeprefix(CONTEXT_PREFIX))
        settle(client, number, state, description, log=log, host=host, record=record)
    except (ForgeCallFailed, LabelMissing) as failed:
        say(f'[{item.platform}] could not comment the result: {failed}')
    _post(client, item, state, description, say)


def _post(client: Client, item: Work, state: str, description: str, say: Callable[[str], None]) -> None:
    try:
        status_post(client, item.sha, context=item.context, state=state, description=description)
    except ForgeCallFailed as failed:  # a missed heartbeat is not a dead producer; say so and keep going
        say(f'[{item.platform}] could not post {state}: {failed}')
    else:
        say(f'[{item.platform}] {state}: {description}')


#: The POSIX niceness a producer runs at: below normal, so an interactive run keeps the scheduler's favour.
BELOW_NORMAL_NICE: Final = 10


def below_normal[P](spawn: Callable[..., P], argv: list[str], **kwargs: object) -> P:
    """Start *argv* through *spawn* at BELOW-NORMAL priority, which its descendants inherit.

    Windows: ``BELOW_NORMAL_PRIORITY_CLASS`` at creation. POSIX has no creation flag (``preexec_fn`` is
    unsafe beside serve's threads), so a real child is reniced at once, before it spawns workers; a
    renice the OS refuses (a parent already nicer, a child already gone) leaves it where it is.
    """
    if sys.platform == 'win32':
        flags = int(kwargs.pop('creationflags', 0) or 0) | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return spawn(argv, creationflags=flags, **kwargs)
    proc = spawn(argv, **kwargs)
    if isinstance(proc, subprocess.Popen):
        with contextlib.suppress(OSError):
            os.setpriority(os.PRIO_PROCESS, proc.pid, BELOW_NORMAL_NICE)
    return proc
