"""A BLOCKING WAIT WITH NO CEILING, found by READING the tree -- the scan `bounded` is not.

WHAT THE CONSUMER'S FILE ASSERTS. No test and no script may wait on a child without a ``timeout=``.
The cost is measured rather than argued: in the originating repo, three gate runs went INCONCLUSIVE
in one day, stalling at 99% with the deadlock detector reporting **no output for 854 s and 0.03 s of
CPU across the whole pytest process tree**. That signature is not a spin and not a crash -- it is a
BLOCKED WAIT. Four tests added that day called ``subprocess.run`` with no ceiling, and the verdict
the gate finally wrote ~28 minutes later was "INCONCLUSIVE -- evidence about nothing." Seven
pre-existing calls were found beside the four new ones, so this is a LINT and not a review item: the
cheapest place to refuse an unbounded wait is before it ever runs.

THE SECOND ROOT COSTS MORE THAN THE FIRST, which is why ``roots`` is an argument and not a constant.
A test that hangs takes a verdict with it; a SCRIPT that hangs takes whatever invoked it, unattended,
with nobody reading the output -- a pre-push hook waiting forever on a credential prompt while the
developer's push never returns, and an impact reader running INSIDE the gate whose ``git diff`` parks
the gate itself on a stuck index lock. A repo's answer about WHICH trees to walk and what a file in
each is called is therefore a repo fact: one walks ``tests/test_*.py`` plus every module under
``scripts/``, another has no ``scripts/`` at all.

WHY THIS IS NOT BOLTED ONTO :mod:`lab_commons.dev.bounded`, which is the question this half was
dispatched with, answered the way ``_datedmemory_readings`` answered it of ``datedlog``. ``bounded``
owns THE WAIT: it runs a child under a wall, reaps the tree, prices the width and writes the refusal
sentence. This owns THE SCAN. That much is only a direction, and a direction is not a boundary --
these three measured differences are:

* THEY DO NOT READ THE SAME THING AND SHARE NO NAME. ``bounded``'s nine public functions take a
  command, a ``Popen``, a pid, a worker count; they import ``os`` and ``subprocess`` and touch a LIVE
  process. This takes a ``Path`` and imports ``ast``. Measured 2026-09-18, the overlap between the
  two surfaces is EMPTY -- a module bolted onto a neighbour it shares no argument type with is
  adjacency, not cohesion.
* THE REFUSALS ARE OPPOSITE IN KIND AND IN TIME. ``bounded`` refuses at RUNTIME, on ONE call, by
  TERMINATING a live process tree -- a gate. This refuses BEFORE anything runs, over a whole tree,
  and must RETURN THE SET: an offender list is pinned, reported in bulk and ratcheted downward, and
  an exception that fires on the first site can do none of the three. The originating repo found
  ELEVEN sites at once; a first-offender refusal would have reported one of them eleven times.
* THEIR FLOORS DIFFER BECAUSE ONLY ONE OF THEM SCANS. ``bounded`` has no floor and needs none: it
  reads no population, so it has no silence to be vacuous. A scan pointed at a tree that moved
  reports exactly what a clean tree reports, so every arm here goes through
  :mod:`lab_commons.dev.floors` first, on BOTH sides, with the consumer's own measured number.

A FOURTH REASON IS ARITHMETIC AND IS RECORDED BECAUSE IT WOULD HAVE FORCED THE SAME ANSWER ANYWAY:
``bounded`` is 293 lines, and this body plus its floors and its control lands near 300. A module over
400 lines is a red in this family, and two halves this week were SPLIT at a seam their own first
sentence named rather than pinned. Bolting these together would have built the split in advance.

THE THIRD ANSWER -- "beside it in :mod:`lab_commons.dev`" -- IS REFUSED ON PLACEMENT, not on taste.
Every family body that walks a CONSUMER'S TREE and is judged by one of its architecture tests lives
here under ``famtests``; ``dev`` holds the runtime the repos CALL. This is the first kind.

WHAT THIS DOES NOT PROVE. ``shell=True`` is out of scope -- ruff's ``S602`` already owns it, and a
second mechanism for one defect gives a reader two messages and no owner. Nor does a ``timeout=``
keyword prove the ceiling is SIZED: a call bounded at 86400 clears every arm here. That is
:func:`lab_commons.dev.bounded.wall_reason`'s subject, one layer in, and a claim otherwise would be
the declaration that lies. The arms that DRIVE it are
:mod:`lab_commons.dev.famtests.boundedremedy`, which is this module's opposite half -- one live wait
on a real tree and a real clock, where this one reads a whole tree before anything runs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

__all__ = [
    'BLOCKING',
    'WAITERS',
    'UnboundedWait',
    'UntimedScan',
    'VacuousExemption',
    'assert_every_exemption_is_real',
    'assert_every_wait_is_bounded',
    'assert_the_scanner_still_convicts',
    'take_scan',
    'untimed_waits',
]

#: The ``subprocess`` calls that BLOCK waiting for a child. ``Popen`` is deliberately absent: it
#: returns immediately and the wait happens later, so the ceiling belongs on the ``wait``/
#: ``communicate`` that follows -- both of which :data:`WAITERS` covers.
BLOCKING: Final[frozenset[str]] = frozenset({'call', 'check_call', 'check_output', 'run'})

#: The methods that block on an ALREADY-STARTED child, whatever object they hang off. Matched by
#: attribute name alone, because the receiver is routinely a local whose type no scan can see.
WAITERS: Final[frozenset[str]] = frozenset({'communicate', 'wait'})


class UnboundedWait(AssertionError):
    """At least one blocking wait declares no ceiling, so a hung child can park whatever ran it."""


class VacuousExemption(AssertionError):
    """An exempt path is not on disk, so the waiver has stopped covering anything it names."""


@dataclass(frozen=True)
class UntimedScan:
    """One walk, with the offender set and the file count its floor judges.

    The count is carried BESIDE the offenders rather than derived from them, because the number that
    matters to a floor is how many files were READ -- a walk that found nothing and a walk that went
    nowhere have the same empty offender list and nothing else in common.
    """

    files_read: int
    offenders: tuple[str, ...]


def untimed_waits(root: Path, *, roots: Collection[tuple[str, str]], exempt: Collection[str]) -> UntimedScan:
    """Every blocking child-wait under the declared roots that names no ``timeout=``.

    Args:
        root: the consumer's checkout.
        roots: ``(directory, glob)`` pairs -- the trees to walk and what a file in each is called. NO
            DEFAULT: ``scripts/`` takes EVERY module while a test tree usually takes ``test_*.py``,
            since a helper imported by a hook hangs exactly as hard as the hook, and one repo in this
            family has no ``scripts/`` tree at all. A guessed pair does not raise; it walks a
            directory that is not there and reports clean, which is why the floor below is mandatory.
        exempt: repo-relative paths whose own source names these calls as DATA -- the consumer's
            guard file itself, and any fixture that plants an offender on purpose. NO DEFAULT, and a
            consumer must assert each one exists: an exemption naming a deleted file covers nothing
            while still reading as a decision. :func:`assert_every_exemption_is_real` IS that
            assertion, published here rather than left to each consumer to hand-write -- it was the
            last body in this module a repo still had to write for itself.

    Returns:
        An :class:`UntimedScan`. Offenders are spelled ``path:line: attr() waits with no timeout=``,
        sorted by path then line, so the set is comparable and can be pinned.

    """
    skip = frozenset(exempt)
    hits: list[str] = []
    files = 0
    for directory, pattern in roots:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob(pattern)):
            rel = path.relative_to(root).as_posix()
            if '__pycache__' in path.parts or rel in skip:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            except (OSError, SyntaxError):
                continue
            files += 1
            hits.extend(f'{rel}:{node.lineno}: {name}() waits with no timeout=' for node, name in _bare_waits(tree))
    return UntimedScan(files_read=files, offenders=tuple(hits))


def _bare_waits(tree: ast.AST) -> list[tuple[ast.Call, str]]:
    """The blocking calls in one parsed module that declare no ceiling.

    A POSITIONAL TIMEOUT COUNTS, AND ONLY FOR THE WAITERS. ``Event.wait(5)`` and ``Popen.wait(5)``
    both take their ceiling positionally and are bounded; ``subprocess.run(cmd)`` takes the COMMAND
    positionally, so the same rule there would excuse every call in the tree. That asymmetry was
    found by widening the walk to a second root and meeting a deadlock sampler for the first time --
    it is the reason this is a helper with its own sentence rather than one condition inline.
    """
    out: list[tuple[ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        is_blocking = name in BLOCKING and getattr(node.func.value, 'id', '') == 'subprocess'
        is_waiter = name in WAITERS
        if not (is_blocking or is_waiter):
            continue
        if any(keyword.arg == 'timeout' for keyword in node.keywords):
            continue
        if is_waiter and node.args:
            continue
        out.append((node, name))
    return out


def take_scan(root: Path, *, roots: Collection[tuple[str, str]], exempt: Collection[str]) -> UntimedScan:
    """Walk *root* once -- the same reading :func:`untimed_waits` returns, under the name the arms use.

    Published as its own name because every other body in this package hands its arms a ``take_scan``
    result, and a consumer that has to remember which module spells it differently is one edit away
    from calling the arm twice over two different walks.
    """
    return untimed_waits(root, roots=roots, exempt=exempt)


def assert_every_wait_is_bounded(scan: UntimedScan, *, floor: int, headroom: int) -> None:
    """THE CHECK, with the FLOOR BOUND FIRST so an empty walk cannot read as a bounded tree.

    Args:
        scan: what :func:`take_scan` returned.
        floor: the consumer's MEASURED count of files the walk reads, set below the real population.
            NO DEFAULT -- measured 2026-09-18, this family's three repos hold 423, 56 and 174
            candidate modules, and one repo's number handed to another is a floor nothing measured.
        headroom: how far past its floor that population may grow before the floor is re-measured.
            NO DEFAULT: a floor measured against a smaller tree refuses only a total collapse, and
            the remedy is to re-measure it rather than to widen the band.

    Raises:
        lab_commons.dev.floors.FloorUnmet: the walk read fewer files than the floor.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding.
        UnboundedWait: at least one blocking wait declares no ceiling.

    """
    floors.assert_floor(scan.files_read, floor=floor, what='untimed-wait')
    floors.assert_floor_still_binds(scan.files_read, floor=floor, headroom=headroom, what='untimed-wait')
    if scan.offenders:
        msg = (
            'a hung child parks whatever ran it at 0% CPU until a deadlock detector fires, and the '
            'verdict is then INCONCLUSIVE -- evidence about nothing. Add timeout=:\n  ' + '\n  '.join(scan.offenders)
        )
        raise UnboundedWait(msg)


def assert_every_exemption_is_real(root: Path, *, exempt: Collection[str]) -> None:
    """Every path the scan SKIPS is a file that is still here -- the other half of the ratchet.

    THE OBLIGATION :func:`untimed_waits` STATES AND DOES NOT ENFORCE. Its ``exempt`` argument is a
    waiver, and a waiver naming a deleted file covers nothing while still reading as a decision --
    the segment of the tree it was written about is once again scanned, or once again not, and
    nobody is told either way. This is the arm that refuses it, and it is the counterpart of
    :func:`lab_commons.dev.famtests.citedtests.assert_every_exemption_is_real`, which published the
    same mechanism for the prose half while this half was left to each consumer to hand-write.

    IT IS DRIVEN ON AN EMPTY SET AS WELL AS A POPULATED ONE, and that is not padding. Both consumer
    files this arm was carved from declare ``EXEMPT = ()`` -- the state they are measured in -- so an
    assertion that only ever ran over a non-empty set would never have been exercised in the shape
    those repos are actually in. It also keeps the failure mode honest: the day the first exemption
    is written is the day this arm starts doing work, and it must already be green when that happens.

    Args:
        root: the consumer's checkout. NO DEFAULT, and it is resolved HERE rather than inside
            :mod:`lab_commons.dev.famtests` -- a body that answered against its own checkout would
            pass every waiver in every repo and report the kit's tree as the repo's.
        exempt: the exact collection handed to :func:`untimed_waits` as its ``exempt``. NO DEFAULT
            for the same reason the scan takes none: a default here is a waiver the consumer never
            wrote, asserted against the wrong tree.

    Raises:
        VacuousExemption: at least one exempt path is not on disk.

    """
    missing = sorted(name for name in exempt if not (root / name).exists())
    if missing:
        msg = (
            f'{missing} are exempt from a scan they are no longer part of. An exemption naming a '
            f'deleted file is a silent widening: the waits it excused are read again -- or the tree '
            f'it named is read by nobody -- and the entry still reads as a decision somebody made. '
            f'Delete the row in the same edit that deleted the file.'
        )
        raise VacuousExemption(msg)


def assert_the_scanner_still_convicts(plant_root: Path, *, roots: Collection[tuple[str, str]]) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL scanner over a REAL tree.

    A lint that has never been shown to fire proves nothing when it is green, and the opposite error
    is just as fatal: one that refuses every subprocess it sees gets deleted rather than obeyed. So
    every distinction the scanner draws is planted at once, each offender beside an honest neighbour
    that must NOT be named -- an unbounded ``run`` beside a bounded one, a bare ``Popen().wait()``
    beside the ``Popen`` itself (which never blocks), and a positional ``wait(5)``, which is bounded
    and which a rule copied from the blocking calls would have convicted.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``. Taken as an
            argument so the control drives the SHIPPED scanner rather than a re-implementation, which
            would agree with itself and prove nothing.
        roots: the consumer's own ``(directory, glob)`` pairs, so the control exercises the walk THIS
            repo declares. The first pair is the one planted into; a repo whose first tree is not
            walked would otherwise pass a control over a tree it never reads.

    Raises:
        AssertionError: the scanner missed a planted offender, or named a bounded call.

    """
    pairs = list(roots)
    if not pairs:
        msg = 'the control was handed no roots, so it would walk nothing and pass in triumph'
        raise AssertionError(msg)
    directory, pattern = pairs[0]
    name = pattern.replace('*', 'planted') if '*' in pattern else 'planted.py'
    planted = plant_root / directory / name
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(
        'import subprocess\n'
        'import threading\n'
        'subprocess.run(["a"], check=False)\n'
        'subprocess.run(["b"], check=False, timeout=5)\n'
        'p = subprocess.Popen(["c"])\n'
        'p.wait()\n'
        'threading.Event().wait(5)\n',
        encoding='utf-8',
    )
    found = take_scan(plant_root, roots=pairs, exempt=()).offenders
    lines = sorted(int(hit.split(':')[1]) for hit in found)
    if lines != [3, 6]:
        msg = (
            f'the scanner named lines {lines} and the planted offenders are the unbounded run on 3 and '
            f'the bare wait on 6. A bounded run, a Popen (which never blocks) and a POSITIONAL '
            f'wait(5) must all three be left alone -- a lint that refuses correct code is deleted '
            f'rather than obeyed, and one that misses the bare wait is why Popen is not in BLOCKING.'
        )
        raise AssertionError(msg)
