"""REFUSAL-NAMES-THE-REMEDY: a wall that TERMINATES, a width the box allows, and the sentence.

THE RULE HAS THREE HALVES AND A REPO NEEDS ALL THREE. "Bound every wait, because a budget is a
ceiling on the WAIT -- split or parallelise, never raise it -- and kill a process TREE by its ROOT
pid, since stopping a wrapper leaves its children running." Stated as prose in four trees; readable
by code in one. What follows is the readable half, migrated 2026-09-16 from motronics-studio's
``scripts/gate/bounded.py``, ``wall_reason.py``, ``width.py`` and ``_box.py``.

WHAT ``subprocess.run(timeout=...)`` DOES NOT DO, and it is the whole reason this module exists. It
kills only the DIRECT child on timeout and then, on Windows specifically, reaps with an UNBOUNDED
``communicate()``. Every grandchild inherits the stdout write handle, so that pipe stays open while
any of them lives -- and a worker pool's workers ARE grandchildren. Measured in motronics-studio on
2026-09-07: a bounded run started at 15:50:29 with a 1800 s wall, whose six worker ledgers all stop
between 16:20:32 and 16:20:36 (so the wall DID fire), whose process tree was still alive at
16:50:20, and which never wrote a verdict at all. It held a shared lock until a human killed it.
**A hang detector that hangs** -- raising the wall makes it strictly worse.

THE SAME SHAPE, WRITTEN OUT BY HAND, IS ALREADY IN A SIBLING'S PROSE.
``wdg-lab/.claude/rules/rem/one-heavy-run-at-a-time.md`` records the identical incident in its own
words -- "``timeout 600 cargo test ...`` killed only the cargo wrapper while the release test
executable kept running at full core count for 40+ minutes" -- and asks a HUMAN to run
``Get-Process | Where-Object ... | Stop-Process`` afterwards. The kill it asks for is
:func:`lab_commons.proc.kill_process_tree`, which is where this module sends it: ONE tree killer in
the family, snapshot-first and children-before-the-root, rather than a second ``taskkill`` spelling
here.

WHY THE WIDTH IS IN THIS MODULE AND NOT BESIDE IT. The refusal is not allowed to say "this is a
different TIER" without having measured how wide the run was, and that is not a stylistic point: the
single sentence motronics printed for years refused a push from a run its own ledger records as
having ONE worker, on a box whose three earlier runs that day ran at 7, 7 and 6 workers inside the
same wall. The diagnosis had never been computed, and its remedy sent the reader to a tier that
would run the same narrowed box for longer. A refusal that names the WRONG remedy is worse than one
that names none, so the sentence and the width it consults ship together.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from lab_commons.proc import kill_process_tree, process_tree, system_memory

__all__ = [
    'BLAS_THREAD_VARS',
    'NARROWED_FLOOR',
    'REAP_AFTER_KILL_S',
    'blas_threads',
    'is_narrowed',
    'logical_cores',
    'reap_tree',
    'run_bounded',
    'terminate_tree',
    'wall_reason',
    'worker_width',
]

#: How long the tree gets to die after the wall kills it, before the run answers anyway. A verdict
#: that waits forever for a corpse is the defect this module exists to remove, so this is bounded
#: and small: the kill has already happened and this is only the reap.
REAP_AFTER_KILL_S = 20

#: The width at or below which a run is NARROWED whatever the box. Kept as a floor under
#: :func:`is_narrowed` so a one-worker run on a two-core box is still reported as narrowed, where
#: the half-of-capacity rule alone would call it healthy.
NARROWED_FLOOR = 2

#: The libraries that spawn a thread pool per PROCESS behind numpy/scipy. All four are read at
#: IMPORT time by their runtime, so they must be in the environment the child is LAUNCHED with --
#: setting them after the pool exists is too late.
BLAS_THREAD_VARS: tuple[str, ...] = (
    'OMP_NUM_THREADS',
    'MKL_NUM_THREADS',
    'OPENBLAS_NUM_THREADS',
    'NUMEXPR_NUM_THREADS',
)

#: Bytes in one gibibyte, spelled once.
_GB = 1024.0**3


def logical_cores() -> int:
    """Logical processors, or a conservative guess. The seam the width tests substitute."""
    return os.cpu_count() or 4


def _available_gb() -> float | None:
    """Available PHYSICAL memory in GB, or ``None`` when this box cannot be read.

    ``None`` IS NOT ZERO, and that distinction is why this returns an optional at all. A box that
    cannot answer how much memory is free is not a box with no memory; conflating the two starves
    every run to its floor on any machine whose instrumentation is damaged -- and that machine is
    live rather than theoretical in this fleet.
    """
    reading = system_memory()
    return None if reading is None else reading.available_bytes / _GB


def worker_width(*, gb_per_worker: float, max_width: int, floor: int, reserve_cores: int, fallback: int) -> int:
    """How many worker processes this box allows, MEMORY FIRST and cores second.

    Taking the smaller of the two is the whole point: an overcommit of memory kills the run
    outright, while an overcommit of processors only makes it slower. The floor is never 0 or 1 --
    those mean SERIAL, which is a choice a human makes and not somewhere a starved box should
    arrive by accident.

    An unreadable box falls back to a width somebody MEASURED rather than to the floor, clipped by
    what the processors allow, because "cannot measure" is not "cannot afford".
    """
    by_cores = logical_cores() - reserve_cores
    available = _available_gb()
    if available is None:
        return min(fallback, max(floor, by_cores))
    return max(floor, min(max_width, by_cores, int(available // gb_per_worker)))


def blas_threads(workers: int) -> int:
    """Threads each WORKER may give its BLAS pool, so N workers do not claim N x cores.

    MEASURED in motronics-studio 2026-09-07, and both ends of the cost came from one cause: nothing
    set any of :data:`BLAS_THREAD_VARS`, so every worker built a pool sized to the WHOLE box -- 53
    threads per worker on 24 logical cores with two workers running, 106 threads competing for 24
    cores, and ~318 in the six-worker run before it. One test took 23x its isolated time and killed
    its worker; another worker reached 14.7 GB resident and the OS killed a 3h29m run. Thread
    arenas are per-pool, so oversubscription inflates MEMORY as well as wall clock, which is why
    the first two diagnoses (a slow test, a small memory budget) were both wrong.

    ONE POOL'S WORTH OF CORES, SHARED OUT: ``cores // workers``, floor 1. ``workers <= 0`` means
    one process, and it may have the whole box -- which is also what makes a serially priced
    duration comparable to the isolated measurement it is supposed to be.
    """
    if workers <= 0:
        return logical_cores()
    return max(1, logical_cores() // workers)


def reap_tree(pid: int) -> frozenset[int]:
    """End the tree rooted at *pid*, and REFUSE outright when this process is inside it.

    THE SELF-MATCH, AND WHY IT IS A REFUSAL RATHER THAN A FILTER. A sweep that reads the process
    table matches ITSELF: ``wdg-lab/.claude/rules/rem/thirty-minute-run-limit.md`` asks a human to
    census survivors and then warns, in its own words, that *"the verification command itself
    matches its own command line, so expect one self-match and ignore it"*. Ignoring is a HUMAN
    step, and a human step is the one missing at 2am. Filtering ourselves out of the kill list
    would not be enough either: an ANCESTOR of ours in the same tree takes the shell, the runner or
    the agent above it with it, and there is then nobody left to report what happened.

    So the whole tree is refused when we are anywhere in it. That is the correct answer for the
    caller this exists for -- a bounded wait reaping a child it spawned is never inside that child's
    tree -- and it turns "remember to ignore one row" into a property.

    :func:`lab_commons.proc.process_tree` takes ONE snapshot and refuses an edge two creation times
    disprove, so the membership test is made against the same closure the kill would have used
    rather than against a second, later reading.

    Returns:
        The pids confirmed terminated. ``frozenset()`` means nothing was reaped -- because the tree
        was empty, because the table could not be read, or because we were in it. A caller that
        needs to tell those apart asks :func:`lab_commons.proc.process_tree` itself.

    """
    tree = process_tree(pid)
    if not tree or os.getpid() in tree:
        return frozenset()
    return kill_process_tree(pid)


def terminate_tree(proc: subprocess.Popen) -> frozenset[int]:
    """Kill *proc* AND EVERYTHING BELOW IT, because the workers are grandchildren.

    ONE TREE KILLER IN THE FAMILY, reached through :func:`reap_tree` so the self-match refusal
    applies here too. :func:`lab_commons.proc.kill_process_tree` takes ONE snapshot of the process
    table, walks the closure refusing an edge two creation times disprove, and kills the descendants
    BEFORE the root -- killing the root first is exactly what leaves survivors, because children are
    orphaned rather than reaped by their parent's death. Spelling a second ``taskkill /T`` here
    would be a second thing to keep true.

    Best-effort BY CONSTRUCTION: a pid that has already exited is the outcome we wanted, so failing
    to kill it is not an error and must never raise into a verdict path. The direct-child fallback
    fires only when the table could not be read AT ALL, which is a state the caller is entitled to
    see as "nothing confirmed" rather than as success.

    Returns:
        The pids :func:`lab_commons.proc.kill_pid` CONFIRMED it terminated -- an observation of a
        cleanup that happened, never the size of the tree we meant to end.

    """
    confirmed = reap_tree(proc.pid)
    if not confirmed:
        try:
            proc.kill()
        except OSError:
            return frozenset()
    return confirmed


def run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    text: bool = False,
    encoding: str | None = None,
    errors: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """``subprocess.run(capture_output=True, timeout=...)``, except the wall terminates the TREE.

    The parameters are SPELLED OUT rather than forwarded as ``**kwargs``, so this reads as the
    narrow thing it is: capture both streams, bound the wait, kill the tree. ``capture_output``,
    ``stdout``, ``stderr`` and ``check`` are absent because this function decides them -- a caller
    that could pass ``stdout=`` could hand the wall a pipe it does not own.

    Raises:
        subprocess.TimeoutExpired: exactly as the call it replaces, carrying whatever output was
            captured, so DESCRIBING the wall stays the caller's job. A caller that treats over-the-
            wall as INCONCLUSIVE must order that test BEFORE the exit code.

    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        text=text,
        encoding=encoding,
        errors=errors,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_tree(proc)
        try:
            out, err = proc.communicate(timeout=REAP_AFTER_KILL_S)
        except subprocess.TimeoutExpired:
            # STILL HOLDING THE PIPE AFTER A TREE KILL. There is nothing left worth a verdict's
            # delay; the captured text is empty and the caller reports the wall, which is the true
            # and complete description of what happened.
            out, err = '', ''
        raise subprocess.TimeoutExpired(list(argv), timeout or 0, output=(out or '') + (err or '')) from None
    return subprocess.CompletedProcess(list(argv), proc.returncode, out, err)


def is_narrowed(workers: int, capacity: int) -> bool:
    """Whether *workers* is at most HALF the width *capacity* allows -- or at the floor.

    HALF, and a measurement moved it there from a constant 2. The constant was defensible and was
    also the only case it could catch: a run then refused at **4 workers on an 8-core box** with
    "a full-width run did not fit". Four of eight is not full width, so the sentence asserted a
    property nobody had checked. Half is the widest line that still leaves a healthy 6-of-8 run
    describable as a genuine tier boundary while calling 4-of-8 what it is.

    IT DOES NOT CLAIM THE RUN WOULD HAVE PASSED at full width. Scaling is not linear. The claim is
    only that a reader can tell a narrowed run from a proven tier boundary -- which the single
    unconditional sentence made impossible.
    """
    return workers <= NARROWED_FLOOR or workers * 2 <= capacity


def wall_reason(*, workers: int | None, capacity: int, wider_tier: str) -> str:
    """Why a run hit the wall -- naming the WIDTH, and then the remedy that width implies.

    THREE ANSWERS, NOT ONE, because there are three states and only one of them means "this work
    belongs in a bigger tier":

    * width UNMEASURED -- nothing computed it, so nothing here may describe it, and the reader is
      sent to the wider tier without a diagnosis attached;
    * width NARROWED -- the box was under pressure, so the remedy is to find what held it and
      re-issue at the SAME tier once the width recovers;
    * width HEALTHY and it still did not fit -- the one case where the wider tier is the answer.

    *wider_tier* is the adopting repo's own name for the unbounded tier. It has no default: a
    remedy naming a tier that does not exist in the repo reading it is a dead end wearing a
    remedy's clothes, and this module cannot know what a repo calls its own.
    """
    if not workers:
        # UNKNOWN, not narrow. Nothing measured the width, so nothing here may describe it.
        return f'over the wall: the width was not measured, so this is not diagnosed -- re-issue as {wider_tier}'
    if is_narrowed(workers, capacity):
        plural = '' if workers == 1 else 's'
        return (
            f'over the wall at {workers} worker{plural} of the {capacity} these cores allow: the run '
            f'was NARROWED, so this is memory pressure rather than a proven tier boundary -- find '
            f'what else held the box, re-issue once the width recovers, and as {wider_tier} only if '
            f'it does not'
        )
    return (
        f'over the wall at {workers} of the {capacity} workers these cores allow: the width was '
        f'healthy and the run still did not fit, so this is not slowness, it is a different TIER -- '
        f're-issue as {wider_tier}'
    )
