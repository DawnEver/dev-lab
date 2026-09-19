"""``lab_commons.dev.famtests.countpins`` -- every arm driven GREEN and, where reachable, driven RED.

WHICH RED IS NOT PLANTABLE, SAID HERE RATHER THAN LEFT TO BE NOTICED.
:func:`~lab_commons.dev.famtests.countpins.assert_the_grader_still_convicts` computes its expected
offender set FROM the vocabulary it is handed, so no argument a caller can pass makes it fail -- by
construction, and deliberately, because a control a caller can aim is a control a caller can aim
somewhere harmless. Its red is "the grader stopped grading", which cannot be planted without
replacing the thing under test. What IS driven here instead is the layer under it:
:func:`~lab_commons.dev.famtests.countpins.count_pins` is called directly with EQUALITY on all seven
planted shapes and under two different vocabularies, which is the same claim without a stub in it.
``boxseat`` and ``venvspelling`` set that precedent in this package.

THIS REPO TAKES THE READING AND NOT THE VERDICT, and the bottom of this file says why with the
measurement that decided it. A body that has only ever run on a planted ``tmp_path`` tree is a
proposal rather than a capability, so the walk IS driven over this repo's real ``tests/`` and its
floor is bound there -- but the conviction is not adopted, because going green would have required
either a fifteen-suffix vocabulary authored to fit the answer or a fourteen-file exemption list, and
both are the waiver-nobody-wrote this module exists to refuse.
"""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests.countpins import (
    Pin,
    PinScan,
    assert_no_constant_is_a_count_pin,
    assert_the_grader_still_convicts,
    count_pins,
    module_constants,
    take_scan,
)

_ROOT = Path(__file__).resolve().parents[1]

#: optimi-lab's declared vocabulary, used here as the ARGUMENT this body takes rather than as a
#: constant it closes over. A consumer is free to declare fewer; it may not omit the declaration.
_SUFFIXES = ('_FLOOR', '_CEILING', '_BAND', '_DEPTH', '_MAX', '_MIN', '_LIMIT', '_HEADROOM')
_NAMES = frozenset(suffix.lstrip('_') for suffix in _SUFFIXES)

#: The seven shapes the grader must tell apart, as one planted module source.
_PLANTED = (
    'from typing import Final\n'
    'OVERSIZE_PINS: Final = 2\n'
    'RETIRED_COUNT = 11\n'
    'SOURCE_FILE_FLOOR: Final = 15\n'
    'MODULE_SIZE_BAND = 320\n'
    "NAMED_PINS: Final = frozenset({'a'})\n"
    'LAZY_IMPORT_PINS: Final[dict[str, str]] = {}\n'
    'lowercase_is_not_a_constant = 3\n'
)


def _named(
    module_source: str,
    *,
    threshold_suffixes: tuple[str, ...],
    threshold_names: Collection[str],
) -> frozenset[str]:
    """The grader's answer as a set of NAMES, so an assertion reads as the claim it is making."""
    found = count_pins(
        ast.parse(module_source),
        threshold_suffixes=threshold_suffixes,
        threshold_names=threshold_names,
    )
    return frozenset(pin.name for pin in found)


def test_the_grader_names_exactly_the_two_count_pins() -> None:
    """EQUALITY over all seven shapes. A grader that names everything passes a membership control."""
    assert _named(_PLANTED, threshold_suffixes=_SUFFIXES, threshold_names=_NAMES) == frozenset(
        {'OVERSIZE_PINS', 'RETIRED_COUNT'}
    )


def test_a_repo_declaring_no_suffixes_is_stricter_rather_than_broken() -> None:
    """THE OTHER SIDE OF THE EXEMPTION. An empty vocabulary must convict the thresholds too.

    This is what proves the exemption is doing work rather than the pattern failing to match, and it
    is the reason ``threshold_suffixes`` has no default: a kit-supplied set would silently hand this
    repo's four-name acquittal to a repo that declared nothing.
    """
    assert _named(_PLANTED, threshold_suffixes=(), threshold_names=()) == frozenset(
        {'OVERSIZE_PINS', 'RETIRED_COUNT', 'SOURCE_FILE_FLOOR', 'MODULE_SIZE_BAND'}
    )


def test_the_grader_reads_both_assignment_spellings() -> None:
    """``Final`` is this family's spelling; missing it would exempt every constant in the tree."""
    annotated = _named('from typing import Final\nPINNED: Final = 4\n', threshold_suffixes=(), threshold_names=())
    plain = _named('PINNED = 4\n', threshold_suffixes=(), threshold_names=())
    assert annotated == plain == frozenset({'PINNED'})


def test_a_bool_is_a_flag_and_not_a_pin() -> None:
    """``True`` is an ``int`` to :mod:`ast`, so the exclusion is explicit or every flag is convicted."""
    assert _named('ENABLED = True\n', threshold_suffixes=(), threshold_names=()) == frozenset()


def test_a_private_constant_is_still_read() -> None:
    """A pin does not stop being a pin by being private, and the refusal's reader is the same person."""
    assert _named('_PINNED = 4\n', threshold_suffixes=(), threshold_names=()) == frozenset({'_PINNED'})


def test_a_standalone_threshold_word_is_exempt_without_a_prefix() -> None:
    """A module whose single threshold is just ``CEILING`` makes exactly the claim a suffix makes."""
    assert _named('CEILING = 9\n', threshold_suffixes=_SUFFIXES, threshold_names=_NAMES) == frozenset()
    assert _named('CEILING = 9\n', threshold_suffixes=_SUFFIXES, threshold_names=()) == frozenset({'CEILING'})


def test_a_convicted_pin_carries_the_number_it_claims() -> None:
    """The per-item REASON. A bare name lets a test assert only on a count, which is the shape refused."""
    found = count_pins(ast.parse('RETIRED_COUNT = 11\n'), threshold_suffixes=(), threshold_names=())
    assert found == (Pin(name='RETIRED_COUNT', literal='11'),)
    assert str(found[0]) == 'RETIRED_COUNT = 11'


def test_module_constants_reads_only_the_module_level() -> None:
    """A constant inside a class or function is not a module-level pin and must not be read."""
    source = 'TOP = 1\n\n\nclass C:\n    INNER = 2\n\n\ndef f():\n    LOCAL = 3\n    return LOCAL\n'
    assert set(module_constants(ast.parse(source))) == {'TOP'}


def test_the_control_passes_under_both_vocabularies() -> None:
    """The shipped control, driven with a full vocabulary and with none at all."""
    assert_the_grader_still_convicts(threshold_suffixes=_SUFFIXES, threshold_names=_NAMES)
    assert_the_grader_still_convicts(threshold_suffixes=(), threshold_names=())


# -- the walk ------------------------------------------------------------------------------------


def _plant_tree(tmp_path: Path) -> Path:
    """A throwaway tests tree with one offender and one clean module, written so the REAL walk runs."""
    directory = tmp_path / 'tests' / 'architecture'
    directory.mkdir(parents=True)
    (directory / 'test_pinned.py').write_text('OVERSIZE_PINS = 2\nA_FLOOR = 15\n', encoding='utf-8')
    (directory / 'test_clean.py').write_text("NAMED_PINS = frozenset({'a'})\nB_CEILING = 9\n", encoding='utf-8')
    (directory / 'not_a_test.py').write_text('IGNORED_PIN = 7\n', encoding='utf-8')
    return tmp_path


def _scan(root: Path, *, exempt: tuple[str, ...] = ()) -> PinScan:
    return take_scan(
        root,
        roots=('tests',),
        threshold_suffixes=_SUFFIXES,
        threshold_names=_NAMES,
        exempt=exempt,
    )


def test_the_walk_convicts_a_planted_pin_and_reads_every_constant(tmp_path: Path) -> None:
    """EQUALITY on the offender map, and the constant count includes the modules that were clean."""
    scan = _scan(_plant_tree(tmp_path))
    assert scan.offenders == {'tests/architecture/test_pinned.py': (Pin(name='OVERSIZE_PINS', literal='2'),)}
    assert scan.modules_read == 2, 'the walk must take `test_*.py` only -- `not_a_test.py` is not a guard'
    assert scan.constants_read == 4
    assert scan.unused_exemptions == ()


def test_an_exemption_acquits_the_file_it_names(tmp_path: Path) -> None:
    """The waiver works -- and the constants in the exempt file are still COUNTED toward the floor."""
    scan = _scan(_plant_tree(tmp_path), exempt=('tests/architecture/test_pinned.py',))
    assert scan.offenders == {}
    assert scan.constants_read == 4, 'an exempt file is still READ; excluding it would shrink the floor silently'


def test_an_exemption_that_names_nothing_is_the_waiver_side_of_the_ratchet(tmp_path: Path) -> None:
    """A ratchet has two sides, and this is the one every hand-written copy of the guard omits."""
    scan = _scan(_plant_tree(tmp_path), exempt=('tests/architecture/test_renamed_away.py',))
    assert scan.unused_exemptions == ('tests/architecture/test_renamed_away.py',)
    with pytest.raises(AssertionError, match='name no module the walk reached'):
        assert_no_constant_is_a_count_pin(scan, floor=1, headroom=10)


def test_an_unparseable_module_raises_rather_than_being_skipped(tmp_path: Path) -> None:
    """A skipped file is a corpus silently lost; the floor cannot see one file going missing."""
    directory = tmp_path / 'tests'
    directory.mkdir()
    (directory / 'test_broken.py').write_text('def (\n', encoding='utf-8')
    with pytest.raises(SyntaxError):
        _scan(tmp_path)


def test_a_walk_that_reached_nothing_is_refused_rather_than_read_as_clean(tmp_path: Path) -> None:
    """THE FLOOR. An empty answer and a clean tree are the same result, and only one means anything."""
    scan = _scan(tmp_path)
    assert scan.offenders == {}, 'the empty tree is CLEAN by the offender reading -- which is the trap'
    with pytest.raises(floors.FloorUnmet):
        assert_no_constant_is_a_count_pin(scan, floor=10, headroom=10)


def test_a_floor_the_population_outgrew_is_refused(tmp_path: Path) -> None:
    """The floor's other side: a number that now refuses only a total collapse."""
    scan = _scan(_plant_tree(tmp_path))
    with pytest.raises(floors.SlackFloor):
        assert_no_constant_is_a_count_pin(scan, floor=1, headroom=1)


def test_the_floors_are_asserted_before_the_offenders(tmp_path: Path) -> None:
    """ORDER IS THE POINT: an unread tree must red as UNREAD, not pass as clean.

    Planted with an offender present AND the floor unmet, so only the ORDER can decide which refusal
    arrives. An offender-first arm would report the pin and hide the fact that the walk was partial.
    """
    scan = _scan(_plant_tree(tmp_path))
    assert scan.offenders, 'the plant must carry an offender, or this arm cannot tell the two orders apart'
    with pytest.raises(floors.FloorUnmet):
        assert_no_constant_is_a_count_pin(scan, floor=999, headroom=10)


def test_a_planted_offender_reaches_the_refusal_with_its_number(tmp_path: Path) -> None:
    """The refusal must name the pin AND what it currently claims, or a reader has to go looking."""
    scan = _scan(_plant_tree(tmp_path))
    with pytest.raises(AssertionError, match='OVERSIZE_PINS = 2'):
        assert_no_constant_is_a_count_pin(scan, floor=1, headroom=10)


# -- the walk on a REAL tree, and why this repo does not yet take the VERDICT --------------------
#
# THIS REPO DOES NOT ADOPT THE RATCHET IN THIS COMMIT, AND THE REASON IS A MEASUREMENT RATHER THAN
# AN INTENTION. Driven over `tests/` on 2026-09-19 with optimi-lab's eight suffixes, the scan reads
# 115 modules and 347 constants and convicts 21 names in 14 files. Hand-read, ALMOST ALL OF THEM ARE
# GENUINE MAGNITUDES spelled with an ending this tree uses and that vocabulary does not carry --
# `SLOW_S`, `_POLL_S`, `_WAIT_S`, `NOISE_LINES`, `SUBSTANTIAL_LINE_CHARS`, `SEPARATION_FACTOR`,
# `OVERHEAD_MULTIPLE`, `_WORKER_LIFETIME_S`. That is precisely the FALSE POSITIVE class the module
# under test names in its own docstring: it reads NAMES, so a threshold spelled outside the declared
# vocabulary is convicted and `RETIRED_ROWS = 2` is invisible.
#
# The two ways to go green from here are both the defect this guard is about. Declaring fifteen
# suffixes until the tree passes is A WAIVER NOBODY WROTE, authored to fit the answer; listing
# fourteen exempt files is the same thing with paths instead of endings. Either is a real change
# with its own evidence and its own reading of each of the 21, and it is NOT this lane's.
#
# So what is asserted here is the half that IS evidence: THE WALK REACHES A REAL CORPUS. A body that
# has only ever run on a planted tmp_path tree is a proposal, and the floor below is the same floor
# an adopter will bind -- on CONSTANTS READ, never on offenders, because the offender population is
# a lower bound whose clean value is the empty set.

#: optimi-lab's vocabulary, used to take the reading above. Not this repo's declaration -- this repo
#: has not made one, which is the point of the comment block.
_MEASURING_SUFFIXES = _SUFFIXES

#: MEASURED 2026-09-19: 347 constants over 115 test modules. Set below it with room for ordinary
#: deletion, and paired with a headroom so a tree that grows past it must RE-MEASURE rather than
#: keep a number that would refuse only a total collapse.
CONSTANT_FLOOR = 280
CONSTANT_HEADROOM = 90


def test_the_walk_reads_this_repos_real_test_tree() -> None:
    """THE FLOOR, BOUND ON THE LIVE TREE. The verdict is not taken; the corpus is proved reachable."""
    scan = take_scan(
        _ROOT,
        roots=('tests',),
        threshold_suffixes=_MEASURING_SUFFIXES,
        threshold_names=_NAMES,
        exempt=(),
    )
    floors.assert_floor(scan.constants_read, floor=CONSTANT_FLOOR, what='COUNT-PIN (this repo, reading only)')
    floors.assert_floor_still_binds(
        scan.constants_read,
        floor=CONSTANT_FLOOR,
        headroom=CONSTANT_HEADROOM,
        what='COUNT-PIN (this repo, reading only)',
    )
    assert scan.modules_read > 1, scan.modules_read
    assert scan.unused_exemptions == ()
