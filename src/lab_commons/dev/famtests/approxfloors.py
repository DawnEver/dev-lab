"""A TOLERANCE STATES THE FLOOR IT FALLS BACK TO -- the scan, the two floors, and the planted control.

WHAT THE CONSUMER'S FILE ASSERTS. ``pytest.approx(x, rel=R)`` carries a DEFAULT ``abs=1e-12`` and the
two legs combine with OR, so the assertion passes if EITHER is met. The floor is therefore always
there; the only question is whether the site CHOSE it. On a quantity whose magnitude sits near or
below ``abs / rel`` the absolute leg swallows the stated ratio and the assertion CANNOT FAIL, and on a
quantity that passes through zero a bare ``rel=`` admits only exactly zero. Either way the number
deciding the test came from the framework, in whatever unit the left-hand side happened to be in.

THE COST IS MEASURED IN THIS FAMILY RATHER THAN ARGUED. One repo wrapped ``approx`` at runtime and
recorded the real magnitude compared at every ratio-without-floor site its suite exercised: of 394
static sites, 376 ran, **46 were VACUOUS** -- the absolute leg fully swallowed the stated ``rel=`` --
27 were within an order of magnitude of doing so, and 1 compared against an exact zero. Three of the
vacuous sites, once given a real floor, turned out to depend on float-evaluation-order noise below
their own stated ratio. A second repo found SEVEN bare calls, one of which compared the vacuum
permeability, 1.2566e-6, against the default 1e-12 -- a floor worth 1e-6 of the value under test,
which would have accepted a constant wrong in its seventh digit.

**THE BAR IS THE REPO'S, AND THE THREE CONSUMERS DO NOT AGREE ON IT.** That is the fact deciding this
module's signature, and it was measured rather than assumed: one repo requires ``abs=``
UNCONDITIONALLY, arguing that ``abs=0.0`` is semantically inert on an exact site so a new call cannot
be written wrong at all; the other two refuse only the call that OVERRODE the relative half and left
the absolute half unstated, arguing that a call with neither keyword has overridden nothing and is
asking for ``approx``'s own combined default. Both are defensible and they convict different sets --
``approx(1.0)`` is an offender under the first and clean under the second. So :data:`BARS` is a named
set, ``bar`` is a keyword argument with NO DEFAULT, and a repo says which question it is asking rather
than inheriting one.

A POSITIONAL TOLERANCE IS A TOLERANCE, and this module reads it where all three consumers do not.
``approx``'s signature is ``approx(expected, rel=None, abs=None, nan_ok=False)``, so
``approx(x, 1e-9)`` states a ratio and no floor exactly as the keyword spelling does, and
``approx(x, 1e-9, 0.0)`` states both. Every consumer today reads the keyword list alone and is blind to
the pair, which is wrong in BOTH directions at once: it misses a real offender under the ratio bar and
convicts a call that did state its floor under the unconditional one. The kit is therefore STRICTER
than the files it replaces, and an adopting repo must expect that as a first red rather than read it as
a regression. Naming it here is the point -- a body that quietly kept the blindness would be the
declaration that lies, and one that fixed it silently would hand a repo a red with no sentence for it.

TWO FLOORS, BECAUSE THEY REFUSE DIFFERENT SILENCES AND ONE CONSUMER ALREADY BINDS BOTH. The CORPUS
floor refuses a walk that stopped reaching the tree. The CALL-SITE floor refuses a corpus that is fully
read and holds no ``approx`` at all -- a suite whose tolerance sites were renamed, or a matcher that
stopped matching, reads exactly like a suite that states every floor. The measured spread is why
neither is a constant here: this family's repos hold 2, 7 and 394 call sites over corpora of 55, 22 and
thousands of files. Both floors are taken on BOTH sides, through :mod:`lab_commons.dev.floors`.

THE CORPUS IS THE CALLER'S LIST AND IS NEVER WALKED HERE, the same seam
:func:`lab_commons.dev.cjk.scan_files` draws: one repo asks git for its tracked ``*.py``, another walks
``tests/`` alone, and a third hands over a corpus module's enumerator. A guessed walk does not raise --
it reads a directory that is not there and reports clean -- which is the whole reason the floors above
are mandatory rather than polite.

WHAT THIS DOES NOT PROVE. It is a LINT on the SHAPE of a call, never an oracle on the numerics: a site
stating ``abs=1e-3`` about a quantity of order 1e-6 clears every arm here and is nonsense. Nor does it
speak about absolute tolerances written as bare floats in a package's own arithmetic, or about the UNIT
a floor is expressed in -- that is the other half of the family rule, owned by a different guard, and
claiming it here would be a scope claim with no test under it.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    'BARS',
    'ApproxScan',
    'FloorlessTolerance',
    'approx_calls',
    'assert_every_tolerance_states_its_floor',
    'assert_the_scanner_still_convicts',
    'is_approx',
    'take_scan',
    'unfloored',
]

#: THE TWO QUESTIONS A REPO CAN BE ASKING, as a NAMED SET rather than a boolean, because a boolean
#: cannot be parametrized over and a reader of ``strict=False`` learns nothing about which population
#: it convicts.
#:
#: * ``'unconditional'`` -- every ``approx`` call must state a floor, including one with no tolerance
#:   at all. ``abs=0.0`` is the inert, legal answer on a site whose value is exact.
#: * ``'ratio'`` -- only a call stating a RELATIVE tolerance and no absolute one is refused. A call
#:   with neither has overridden nothing and keeps ``approx``'s own combined default.
BARS: Final[frozenset[str]] = frozenset({'unconditional', 'ratio'})

#: Where ``rel`` and ``abs`` sit in ``approx(expected, rel=None, abs=None, nan_ok=False)`` when they
#: are given positionally. Named rather than written as bare digits because the whole point of
#: :func:`_stated` is that these two positions ARE the two keywords.
_RATIO_ARITY: Final = 2
_FLOOR_ARITY: Final = 3

#: How many ``approx`` calls :func:`assert_the_scanner_still_convicts` plants. One per distinction the
#: scanner draws, so a reader can check the control covers them by counting the lines it writes.
_PLANTED_CALLS: Final = 6


class FloorlessTolerance(AssertionError):
    """At least one comparison states a tolerance whose absolute floor was chosen by the framework."""


@dataclass(frozen=True)
class ApproxScan:
    """One walk: the offenders, and BOTH populations the two floors judge.

    ``files_read`` and ``calls_seen`` are carried beside the offenders rather than derived from them,
    because the numbers a floor needs are how much was READ. A walk that went nowhere, a corpus whose
    tolerance sites have all been renamed, and a suite that states every floor all produce the same
    empty offender tuple and have nothing else in common.
    """

    files_read: int
    calls_seen: int
    offenders: tuple[str, ...]


def is_approx(func: ast.expr) -> bool:
    """Whether *func* names ``approx`` -- dotted or bare, because the IMPORT STYLE is not the subject.

    ``pytest.approx(...)`` and a module-level ``from pytest import approx`` are the same call, and all
    three consumers already treat them so. AN ALIAS IS INVISIBLE HERE, stated rather than implied:
    ``from pytest import approx as close`` is matched by nothing in this module, because the name is
    all an AST lint has and following the binding would be an import resolver this guard does not own.
    Nothing in this family spells it that way today; a repo that starts to has lost the guard in
    silence, which is why the sentence is here and not only in a commit message.
    """
    return (isinstance(func, ast.Name) and func.id == 'approx') or (
        isinstance(func, ast.Attribute) and func.attr == 'approx'
    )


def _stated(call: ast.Call) -> tuple[bool, bool]:
    """``(states a ratio, states a floor)`` for one ``approx`` call -- KEYWORD OR POSITIONAL.

    Reading only the keyword list -- what every consumer does today -- reports ``approx(x, 1e-9)`` as
    having stated nothing at all, and that single reading is wrong in both directions: under the ratio
    bar it excuses a real offender, and under the unconditional bar it convicts a call whose floor was
    given positionally. See :data:`_RATIO_ARITY` for where the two positions come from.
    """
    named = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
    positional = len(call.args)
    return ('rel' in named or positional >= _RATIO_ARITY, 'abs' in named or positional >= _FLOOR_ARITY)


def approx_calls(tree: ast.AST) -> tuple[ast.Call, ...]:
    """Every ``approx`` call in *tree*, in walk order. Pure, so a control drives THIS reader."""
    return tuple(node for node in ast.walk(tree) if isinstance(node, ast.Call) and is_approx(node.func))


def unfloored(tree: ast.AST, *, bar: str) -> tuple[int, ...]:
    """The LINE of every ``approx`` call in *tree* that fails *bar*, sorted.

    Args:
        tree: a parsed module.
        bar: a member of :data:`BARS`. NO DEFAULT -- the two bars convict different sets, and a default
            would hand one repo's ruling to another and then report it as measured.

    Returns:
        The offending line numbers, sorted and without duplicates removed -- two offending calls on one
        line are two offences.

    Raises:
        ValueError: *bar* is not a member of :data:`BARS`. A misspelling must not silently select a
            bar, because both bars return a plausible number and neither reading would look wrong.

    """
    if bar not in BARS:
        msg = f'{bar!r} is not one of {sorted(BARS)}; a bar nobody declared cannot judge anything.'
        raise ValueError(msg)
    lines: list[int] = []
    for call in approx_calls(tree):
        ratio, floor = _stated(call)
        if floor:
            continue
        if bar == 'unconditional' or ratio:
            lines.append(call.lineno)
    return tuple(sorted(lines))


def take_scan(paths: Iterable[Path], *, root: Path, bar: str) -> ApproxScan:
    """Read *paths* once under *bar*, naming each offender ``path:line`` relative to *root*.

    Args:
        paths: the consumer's OWN corpus, handed over rather than walked here. NO DEFAULT and no walk:
            one repo asks git for tracked ``*.py``, another reads ``tests/`` alone, and a guessed walk
            of a directory that is not there reports clean.
        root: what an offender is named relative to. A path outside it keeps its own spelling, so a
            file planted in a ``tmp_path`` stays readable in the refusal.
        bar: a member of :data:`BARS` -- see :func:`unfloored`.

    Returns:
        An :class:`ApproxScan`. A file that cannot be read or parsed is SKIPPED and does not count
        toward ``files_read``: "unparseable" and "parsed and clean" are different facts, and only the
        second is evidence of anything.

    """
    offenders: list[str] = []
    files = 0
    calls = 0
    for path in sorted(paths):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except (OSError, SyntaxError):
            continue
        files += 1
        calls += len(approx_calls(tree))
        named = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
        offenders.extend(f'{named}:{line}' for line in unfloored(tree, bar=bar))
    return ApproxScan(files_read=files, calls_seen=calls, offenders=tuple(sorted(offenders)))


def assert_every_tolerance_states_its_floor(
    scan: ApproxScan,
    *,
    bar: str,
    file_floor: int,
    file_headroom: int,
    call_floor: int,
    call_headroom: int,
    what: str,
) -> None:
    """THE CHECK, with BOTH floors bound on BOTH sides BEFORE one offender is looked at.

    The order is the point. A corpus floor alone passes a fully-read tree whose tolerance sites have
    every one been renamed away from ``approx``; a call floor alone passes a walk that reached three
    files and found their two calls. Only both together say the reading was a reading.

    Args:
        scan: what :func:`take_scan` returned.
        bar: the bar that scan was taken under, quoted back in the refusal so a reader can tell a real
            offender from a repo asking the other question.
        file_floor: the consumer's MEASURED count of files the walk parses. NO DEFAULT -- measured
            2026-09-18, this family's repos hand over 55, 22 and thousands.
        file_headroom: how far past that floor the corpus may grow before the floor is re-measured.
        call_floor: the consumer's MEASURED count of ``approx`` call sites. NO DEFAULT, and it is the
            number that differs most: 2, 7 and 394 across three repos on one day.
        call_headroom: the same band for the call population.
        what: names the guard in every floor refusal. NO DEFAULT -- a wrong label does not raise, it
            sends the reader to a guard that did not fail.

    Raises:
        lab_commons.dev.floors.FloorUnmet: a population is below its floor.
        lab_commons.dev.floors.SlackFloor: a floor has been outgrown and no longer binds.
        FloorlessTolerance: at least one call states a tolerance with no floor under it.

    """
    corpus = f'{what} (corpus)'
    sites = f'{what} (approx call sites)'
    floors.assert_floor(scan.files_read, floor=file_floor, what=corpus)
    floors.assert_floor_still_binds(scan.files_read, floor=file_floor, headroom=file_headroom, what=corpus)
    floors.assert_floor(scan.calls_seen, floor=call_floor, what=sites)
    floors.assert_floor_still_binds(scan.calls_seen, floor=call_floor, headroom=call_headroom, what=sites)
    if scan.offenders:
        msg = (
            f'these comparisons take a floor the framework chose rather than one the site did, under the '
            f'{bar!r} bar:\n  ' + '\n  '.join(scan.offenders) + '\n'
            'State the floor the tolerance falls back to. abs=0.0 is a legitimate answer for a value that '
            'is exact and saying so is the whole cost -- a ratio admits only exactly zero at zero, and a '
            'default absolute leg swallows the ratio wherever the magnitude is small enough.'
        )
        raise FloorlessTolerance(msg)


def assert_the_scanner_still_convicts(plant_root: Path, *, bar: str) -> None:
    """THE PLANTED CONTROL, in BOTH directions, driving the REAL scanner over a REAL file.

    Every distinction the scanner draws is planted at once, each offender beside an honest neighbour
    that must NOT be named: both import spellings, the keyword pair, the POSITIONAL pair no consumer
    reads today, the defaulted call the two bars disagree about, and a call that is not ``approx`` at
    all. A lint convicting everything is deleted rather than obeyed, so the second direction carries as
    much of this function as the first.

    THE AXIS THIS CONTROL IS BLIND TO, named because a control that does not say so invites being
    trusted past its reach: it plants SOURCE TEXT and proves nothing about the CORPUS. A consumer whose
    file list is empty, points at a renamed directory, or silently drops its largest tree passes every
    arm here. That axis belongs to the two floors in
    :func:`assert_every_tolerance_states_its_floor` and is a different argument entirely -- the round
    trip this family got wrong once was parametrized over MODULES when the axis that mattered was
    import SPELLINGS, which is this same mistake one level up.

    Args:
        plant_root: an empty directory to plant into -- a consumer's ``tmp_path``. Taken as an argument
            so the control drives the SHIPPED scanner rather than a re-implementation that would agree
            with itself and prove nothing.
        bar: the consumer's own bar, so the control exercises the question THIS repo asks.

    Raises:
        AssertionError: the scanner missed a planted offender, or named a call that stated its floor.

    """
    planted = plant_root / 'test_planted.py'
    planted.write_text(
        'import pytest\n'
        'from pytest import approx\n'
        'a = v == pytest.approx(0.0, rel=1e-9)\n'
        'b = v == pytest.approx(0.0, rel=1e-9, abs=1e-12)\n'
        'c = v == pytest.approx(0.0)\n'
        'd = v == approx(0.0, rel=1e-9)\n'
        'e = v == approx(0.0, 1e-9)\n'
        'f = v == approx(0.0, 1e-9, 0.0)\n'
        'g = v == some.other.call(0.0, rel=1e-9)\n',
        encoding='utf-8',
    )
    scan = take_scan([planted], root=plant_root, bar=bar)
    if scan.calls_seen != _PLANTED_CALLS:
        msg = (
            f'the reader found {scan.calls_seen} approx calls among the {_PLANTED_CALLS} planted ones. It '
            f'either misses an import spelling or has reached a call that is not approx at all -- the '
            f'dotted and the bare form are one call, and `some.other.call(rel=...)` is not one.'
        )
        raise AssertionError(msg)
    lines = tuple(int(site.split(':')[1]) for site in scan.offenders)
    expected = (3, 5, 6, 7) if bar == 'unconditional' else (3, 6, 7)
    if lines != expected:
        msg = (
            f'under the {bar!r} bar the scanner named lines {lines} and the planted offenders are '
            f'{expected}. The floored call on 4 and the POSITIONALLY floored call on 8 must both be left '
            f'alone; the positional ratio on 7 must be named, which is the site every consumer file reads '
            f'past today; and the defaulted call on 5 is exactly the line the two bars disagree about, so a '
            f'body answering the same for both would have no bar at all.'
        )
        raise AssertionError(msg)
