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
its exit code names -- or ``stopped`` when :mod:`lab_commons.dev.stoprun` stopped it on purpose.

THE PART IS JUDGED AT THE CLAIMED SHA, in a tree this producer owns (:mod:`lab_commons.dev.shatree`):
the declared argv (read at the sha) runs with that tree's own interpreter, cwd = the tree, and the tree
is removed once the run ended -- after its record and the streamed output are kept in the serving
checkout's ``parts/<sha>/`` (:func:`~lab_commons.dev.shatree.close_tree`). The serving checkout's HEAD
decides nothing. A tree that cannot be built spawns nothing, and the claim is released naming the step
that refused.
"""

from __future__ import annotations

import dataclasses
import math
import os
import subprocess
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forge import fetch_origin
from lab_commons.dev.forgecarry import SETTLED, carry_target, equivalent
from lab_commons.dev.forgeclaim import Work, forge_now
from lab_commons.dev.forgeschedule import tip_of
from lab_commons.dev.forgestatus import Status, status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed
from lab_commons.dev.platformparts import part_context, parts_of
from lab_commons.dev.producer import ProducerExit, producing, release_reason
from lab_commons.dev.servelock import was_stopped
from lab_commons.dev.shatree import TreeFailed, close_tree, open_tree

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
                    beat_s=renew_s if beat_s is None else beat_s, beat=beat)  # fmt: skip
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
) -> Produced:
    context = part_context(item.platform)
    say(f'[{item.platform}] start in {tree.name}: {" ".join(argv)}')
    proc = spawn(
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
    wake_s = min(renew_s, beat_s)
    renew_every = max(1, math.ceil(renew_s / wake_s - 1e-9))  # wakes per renewal
    wakes = 0
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
            fetch(root)
            tip = tip_of(root, item.ref)
            if tip and tip != item.sha and not equivalent(root, item.sha, tip):
                proc.kill()
                returncode = proc.wait()
                superseded = tip
                say(f'[{item.platform}] stopped: {item.ref} moved on to {tip[:12]}')
                break
            wakes += 1
            beat(clock() - started)
            if (
                item.holder is not None and wakes % renew_every == 0
            ):  # the heartbeat: the same claim, until the FORGE's time plus the lease
                built = client(root)
                try:
                    renewed = dataclasses.replace(item.holder, until=forge_now(built) + lease)
                except (ForgeCallFailed, OSError) as failed:
                    say(f'[{item.platform}] could not read the forge clock to renew: {failed}')
                    continue
                _post(built, item, 'pending', renewed.description(), say)
    pump.join(timeout=5)
    say(f'[{item.platform}] exit={returncode}')
    posts = [status for status in status_history(client(root), item.sha) if status.context == context]
    if superseded or (posts and posts[-1].state == 'pending'):
        stopped = proc.pid is not None and was_stopped(proc.pid)  # by stoprun, on purpose
        reason = 'stopped' if stopped else release_reason(returncode)
        reason = f'superseded by {superseded[:12]}' if superseded else reason
        _post(client(root), item, 'error', reason, say)
    elif posts and posts[-1].state in SETTLED:
        _carry(root, client(root), item, posts[-1], say)
    return Produced(item.ref, item.sha, item.platform, argv, returncode)


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
