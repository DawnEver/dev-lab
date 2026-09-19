"""A PIN IS A NAMED SET; a number may only be a THRESHOLD, and its NAME must say so.

WHY THIS IS FAMILY, AND IT ARRIVES AS A CORRECTION. ``NAMED-SETS-NOT-COUNTS`` was claimed as
enforced by optimi-lab on 2026-09-15 while citing three modules that merely HAPPEN to use named
sets. That is the declaration-that-lies shape one level up: nothing refused the edit replacing
``OVERSIZE_PINS = frozenset()`` with ``OVERSIZE_COUNT = 0``, so the rule was EXEMPLIFIED rather than
enforced, and exemplifying a rule and enforcing it are different facts of which only one is a
mechanism. Measured 2026-09-19 one repo over: wdg-lab cites the same rule at SIX modules that use
named sets and holds no count-pin guard at all -- the identical defect, still live, which is what
makes this a family body rather than one repo's tidiness.

THE INCIDENT THE RULE IS PRICED FROM, from this family's own integration page. A pin read
``mec transient: 2``, a merge silently dropped a restriction, the table delivered 1, AND THE PIN WAS
LOWERED TO 1 WITH A NOTE EXPLAINING WHY. The pin was right and the table was wrong. An integer
cannot say WHICH row moved, so a reader cannot tell a delivered capability from a pending one, and
the honest-looking repair when the number disagrees is to edit the digit.

THE PROPERTY, stated so a reader can violate it on purpose. A module-level constant bound to a bare
NUMBER must be named as a THRESHOLD -- a quantity whose whole content IS the magnitude, and about
which there is no set of rows a number could have failed to name. Everything else that is pinned is
a SET: a frozenset, a dict, a tuple of names.

WHAT THE KIT KEEPS AND WHAT THE REPO RULES ON. The grader is here; every word it grades by is an
ARGUMENT WITH NO DEFAULT. ``threshold_suffixes`` is the one this module must never guess, because it
IS THE EXEMPTION MECHANISM -- a default suffix set is a waiver the consumer never wrote, shipped
into its tree by a library it imported for something else. optimi-lab declares eight; a repo with
none is making a stricter claim and is entitled to.

WHAT IT CANNOT SEE, AND WHY THE FLOOR COUNTS CONSTANTS RATHER THAN OFFENDERS. This reads NAMES.
``RETIRED_ROWS = 2`` is a count pin and is INVISIBLE, and a genuine threshold spelled without a
declared suffix is a FALSE POSITIVE. So the offender population is a LOWER BOUND, and a lower bound
is worthless as a floor: the natural answer of a clean scan is the empty set, which is also exactly
what walking the wrong directory returns. :class:`PinScan` therefore carries ``constants_read``, and
:func:`assert_no_constant_is_a_count_pin` asserts the FLOORS FIRST and the offenders second.

A RATCHET HAS TWO SIDES. The capability side is the grader convicting a pin; the waiver side is an
``exempt`` entry naming a file the walk never reached, which reads as a decision and is a hole. Both
red here, and the second one is the half every hand-written copy of this guard has been missing.

THE CONTROL PLANTS A MODULE SOURCE AND CALLS THE REAL GRADER, ASSERTING EQUALITY.
:func:`assert_the_grader_still_convicts` is not optional and is not parametrisable by the caller
beyond the two vocabularies it is grading with -- a control a caller can aim is a control a caller
can aim somewhere harmless. EQUALITY and not membership, because a grader that names EVERYTHING
passes a membership control and would then convict every threshold in the adopting tree.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

__all__ = [
    'Pin',
    'PinScan',
    'assert_no_constant_is_a_count_pin',
    'assert_the_grader_still_convicts',
    'count_pins',
    'module_constants',
    'take_scan',
]


@dataclass(frozen=True, slots=True)
class Pin:
    """ONE convicted constant, WITH THE NUMBER IT WAS BOUND TO -- the reason, not just the name.

    A bare name tells a reader which line to open; the literal tells them what the pin currently
    claims, which is the thing to replace with a set. It is also what lets a control assert on the
    CLASSIFICATION rather than on a count, and a count is the shape this whole module refuses.
    """

    name: str
    literal: str

    def __str__(self) -> str:
        """The offender as one repair-shaped line: the name, then what it pins."""
        return f'{self.name} = {self.literal}'


@dataclass(frozen=True, slots=True)
class PinScan:
    """What one walk read and what it convicted. A READING plus its own floor material.

    ``constants_read`` is the floor's subject and ``offenders`` is not, for the reason the module
    docstring gives: the offender set is a LOWER BOUND whose natural clean value is empty, which is
    indistinguishable from a walk that reached nothing.
    """

    constants_read: int
    modules_read: int
    offenders: Mapping[str, tuple[Pin, ...]]
    unused_exemptions: tuple[str, ...]


def module_constants(module: ast.Module) -> dict[str, ast.expr]:
    """Every module-level UPPER_SNAKE constant in *module*, mapped to the expression it is bound to.

    BOTH SPELLINGS COUNT -- ``X: Final = ...`` and ``X = ...``. Reading only one of them exempts
    whichever the adopting tree happens to use, which in this family is ``Final`` and would be the
    WHOLE tree; that is why the existing consumer file carries a test for this alone.

    Leading and trailing underscores are stripped before the case test, so a private ``_PINNED`` is
    read: a pin does not stop being a pin by being private, and the reader of a refusal is the same
    person either way.
    """
    found: dict[str, ast.expr] = {}
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            found[node.target.id] = node.value
        elif isinstance(node, ast.Assign) and node.value is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value
    return {name: value for name, value in found.items() if name.strip('_') and name.lstrip('_').isupper()}


def count_pins(
    module: ast.Module,
    *,
    threshold_suffixes: tuple[str, ...],
    threshold_names: Collection[str],
) -> tuple[Pin, ...]:
    """THE GRADER. Constants bound to a bare number whose NAME does not declare them a threshold.

    ``bool`` is excluded because ``True`` is an ``int`` to :mod:`ast` and a flag is not a pin. A
    negative or complex literal arrives as a :class:`ast.UnaryOp` or :class:`ast.BinOp` rather than
    a :class:`ast.Constant` and is NOT convicted -- stated rather than left to be found, and it is
    one of the ways the offender set is a lower bound.

    Args:
        module: the parsed module.
        threshold_suffixes: the name endings that make a number legitimate. NO DEFAULT: this is the
            EXEMPTION MECHANISM, and a default here is a waiver the consumer never wrote.
        threshold_names: the same words STANDING ALONE. A module whose single threshold is just
            ``CEILING`` makes exactly the claim a suffix makes, and refusing it teaches nothing
            except to add a prefix. NO DEFAULT for the same reason.

    Returns:
        One :class:`Pin` per convicted constant, sorted by name.

    """
    suffixes = tuple(suffix.upper() for suffix in threshold_suffixes)
    standalone = {name.upper() for name in threshold_names}
    return tuple(
        Pin(name=name, literal=repr(value.value))
        for name, value in sorted(module_constants(module).items())
        if isinstance(value, ast.Constant)
        and isinstance(value.value, int | float)
        and not isinstance(value.value, bool)
        and not (suffixes and name.upper().endswith(suffixes))
        and name.upper().strip('_') not in standalone
    )


def take_scan(
    root: Path,
    *,
    roots: Iterable[str],
    threshold_suffixes: tuple[str, ...],
    threshold_names: Collection[str],
    exempt: Collection[str],
) -> PinScan:
    """Walk *roots* under *root*, grade every module, and report BOTH what was read and what failed.

    A file that does not parse RAISES rather than being skipped: an unparseable module in the tree a
    guard reports on is a louder finding than anything this guard could report, and skipping it is
    how a walk quietly loses its corpus.

    Args:
        root: the checkout. Repo-relative POSIX paths in the result are spelled against it.
        roots: the directories to walk, repo-relative. NO DEFAULT -- one repo keeps its architecture
            guards in ``tests/architecture`` and another in ``tests/``, and a guessed directory that
            resolves to nothing REPORTS THE TREE CLEAN.
        threshold_suffixes: see :func:`count_pins`.
        threshold_names: see :func:`count_pins`.
        exempt: repo-relative POSIX paths whose pins are permitted. Every entry that names no module
            the walk reached is reported in ``unused_exemptions`` -- the waiver side of the ratchet.

    Returns:
        The :class:`PinScan`.

    """
    base = Path(root)
    waived = frozenset(exempt)
    paths = sorted({path for directory in roots for path in (base / directory).rglob('test_*.py')})
    constants = 0
    offenders: dict[str, tuple[Pin, ...]] = {}
    reached: set[str] = set()
    for path in paths:
        name = path.relative_to(base).as_posix()
        reached.add(name)
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        constants += len(module_constants(tree))
        if name in waived:
            continue
        found = count_pins(tree, threshold_suffixes=threshold_suffixes, threshold_names=threshold_names)
        if found:
            offenders[name] = found
    return PinScan(
        constants_read=constants,
        modules_read=len(paths),
        offenders=offenders,
        unused_exemptions=tuple(sorted(waived - reached)),
    )


def assert_no_constant_is_a_count_pin(scan: PinScan, *, floor: int, headroom: int) -> None:
    """THE CHECK: FLOORS FIRST, then the waiver side, then the offenders.

    THE ORDER IS THE POINT. An offender assertion that runs first reports a clean tree whenever the
    walk read nothing, which is what a renamed directory, a widened exclusion and a stopped walk all
    look like. The floor is on CONSTANTS READ rather than on offenders, because the offender
    population is a lower bound whose clean value is the empty set.

    Args:
        scan: what :func:`take_scan` returned.
        floor: the smallest constant population this scan can read and still be evidence. NO
            DEFAULT: it is the adopting repo's own measurement.
        headroom: the largest slack the floor may carry before it must be RE-MEASURED. The remedy
            for a breach is to re-take the floor; widening the headroom is how the arm is kept while
            the guard it stands for is given up.

    Raises:
        lab_commons.dev.floors.FloorUnmet: the walk read fewer constants than *floor*.
        lab_commons.dev.floors.SlackFloor: the floor has been outgrown past *headroom*.
        AssertionError: an exemption names nothing, or a constant is a count pin.

    """
    what = 'COUNT-PIN (module-level constants)'
    floors.assert_floor(scan.constants_read, floor=floor, what=what)
    floors.assert_floor_still_binds(scan.constants_read, floor=floor, headroom=headroom, what=what)
    if scan.unused_exemptions:
        msg = (
            f'these count-pin exemptions name no module the walk reached: '
            f'{list(scan.unused_exemptions)}. A waiver nothing uses is a hole that READS AS A '
            f'DECISION -- and it is the half of the ratchet a hand-written copy of this guard always '
            f'omits, because a rename silently converts an exemption into permission for a file '
            f'nobody is looking at. Delete the entry with the file, or fix the path.'
        )
        raise AssertionError(msg)
    if scan.offenders:
        listed = '\n  '.join(
            f'{path}: ' + ', '.join(str(pin) for pin in pins) for path, pins in sorted(scan.offenders.items())
        )
        msg = (
            f'these constants pin something with a NUMBER:\n  {listed}\n'
            f'An integer cannot say WHICH row moved, so a reader cannot tell a delivered capability '
            f'from a pending one -- and when it disagrees with the tree the repair that looks honest '
            f'is to edit the digit. This family has already paid for that once: a pin read 2, a merge '
            f'dropped a restriction, the table delivered 1, and the PIN was lowered. Pin the named set '
            f'instead, or -- if the number IS the quantity -- rename it so its own name declares it a '
            f'threshold.'
        )
        raise AssertionError(msg)


def assert_the_grader_still_convicts(
    *,
    threshold_suffixes: tuple[str, ...],
    threshold_names: Collection[str],
) -> None:
    """THE CONTROL. Plant a module SOURCE, drive the REAL grader, and assert EQUALITY on the set.

    Seven planted shapes, because the grader makes seven distinctions and a control driving one
    leaves six asserted by prose:

    * a count pin with a SET-SHAPED NAME (``OVERSIZE_PINS = 2``) -- the exact edit that was never
      refused, and the reason this module exists;
    * a ``_COUNT`` pin, which announces itself;
    * a threshold exempt BY ITS OWN SUFFIX -- the declaration the whole exemption rests on;
    * a second threshold under a different suffix, so one working suffix cannot carry the rest;
    * a ``frozenset`` pin, which is the RIGHT shape and must never be named;
    * an EMPTY ``dict`` pin, which is the right shape at its weakest -- a grader keying on
      truthiness rather than on type would convict it;
    * a lowercase name, which is not a constant at all.

    THE CALLER'S OWN VOCABULARY IS USED, not a fixture one, so a repo that declares a suffix set the
    grader cannot act on finds out HERE rather than by reporting its tree clean. A repo declaring no
    suffixes at all is legal and stricter, and its two threshold plants are then convicted -- which
    is asserted, because a control that quietly changes shape under its argument proves nothing.

    Args:
        threshold_suffixes: the repo's declared suffixes -- see :func:`count_pins`.
        threshold_names: the repo's declared standalone threshold words.

    Raises:
        AssertionError: the grader's answer on planted input is not exactly the expected set.

    """
    planted = ast.parse(
        'from typing import Final\n'
        'OVERSIZE_PINS: Final = 2\n'
        'RETIRED_COUNT = 11\n'
        'SOURCE_FILE_FLOOR: Final = 15\n'
        'MODULE_SIZE_BAND = 320\n'
        "NAMED_PINS: Final = frozenset({'a'})\n"
        'LAZY_IMPORT_PINS: Final[dict[str, str]] = {}\n'
        'lowercase_is_not_a_constant = 3\n'
    )
    suffixes = tuple(suffix.upper() for suffix in threshold_suffixes)
    standalone = {name.upper() for name in threshold_names}
    thresholds = {
        name
        for name in ('SOURCE_FILE_FLOOR', 'MODULE_SIZE_BAND')
        if (suffixes and name.endswith(suffixes)) or name in standalone
    }
    expected = frozenset({'OVERSIZE_PINS', 'RETIRED_COUNT'}) | (
        frozenset({'SOURCE_FILE_FLOOR', 'MODULE_SIZE_BAND'}) - thresholds
    )
    found = count_pins(planted, threshold_suffixes=threshold_suffixes, threshold_names=threshold_names)
    named = frozenset(pin.name for pin in found)
    if named != expected:
        msg = (
            f'the grader answered {sorted(named)} on planted input, and this vocabulary expects '
            f'{sorted(expected)}. Named and not expected: {sorted(named - expected)}; expected and '
            f'missed: {sorted(expected - named)}. It must name BOTH count pins, never name a '
            f'set-valued pin (including the EMPTY dict) and never name a lowercase binding, and it '
            f'must exempt exactly the thresholds THIS repo declared -- no more, which would be a '
            f'waiver nobody wrote, and no fewer, which would convict the declaration the exemption '
            f'rests on.'
        )
        raise AssertionError(msg)
    if any(pin.literal == '' for pin in found):
        msg = 'a convicted pin carried no literal, so its finding cannot say what the number currently claims'
        raise AssertionError(msg)

    annotated = count_pins(
        ast.parse('from typing import Final\nPINNED: Final = 4\n'),
        threshold_suffixes=threshold_suffixes,
        threshold_names=threshold_names,
    )
    plain = count_pins(
        ast.parse('PINNED = 4\n'),
        threshold_suffixes=threshold_suffixes,
        threshold_names=threshold_names,
    )
    one = frozenset({'PINNED'})
    if not (frozenset(pin.name for pin in annotated) == frozenset(pin.name for pin in plain) == one):
        msg = (
            f'the grader read the two assignment spellings differently: `PINNED: Final = 4` gave '
            f'{[str(pin) for pin in annotated]} and `PINNED = 4` gave {[str(pin) for pin in plain]}. '
            f"THE SHAPE IT MISSES IS THE ONE A VIOLATION WILL ARRIVE IN -- `Final` is this family's "
            f'usual spelling, so a reader blind to it exempts the whole tree while reporting clean. '
            f'The consumer this body was carved from carries a dedicated arm for exactly this, which '
            f'is what makes it family rather than an invariant nobody drives.'
        )
        raise AssertionError(msg)
