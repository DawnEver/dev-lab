"""THE ECHOED-TOKEN SCANNER, driven on this repo's own trees and on a planted one.

WHAT THIS FILE IS FOR, AND IT IS NOT A CONSUMER'S ARM. It asserts that the SHARED BODY behaves --
that the scanner names the echo, leaves its three honest neighbours alone, and refuses a walk that
read nothing -- and then it turns the scanner on THIS repo, which is where the shape was found.

THE CONTROLS RUN IN BOTH DIRECTIONS AT EVERY SEAM. A scanner that only ever fires is deleted rather
than obeyed, so every distinction it draws is planted beside an honest neighbour; the floor is
driven from both sides, since a floor that has stopped binding is a waiver nothing uses; and the
whole-tree arm names a POPULATION rather than a verdict, because finding nothing is vacuous.

THE AXIS EVERY ARM HERE IS BLIND TO is the module's own last paragraph: this reads data flow inside
ONE function body. An echo through a file, an attribute or a second function is invisible to it, so
the offender set is a lower bound and the floor counts bodies READ rather than offenders found.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests import echoedtoken

if TYPE_CHECKING:
    from collections.abc import Collection

ROOT: Final = Path(__file__).resolve().parents[1]

#: The trees this repo keeps assertion bodies and tests in, and what a file in each is called.
ROOTS: Final[tuple[tuple[str, str], ...]] = (('src/lab_commons', '*.py'), ('tests', '*.py'))

#: The scanner's own module carries the shape as DATA, in the planted source its control writes.
EXEMPT: Final[tuple[str, ...]] = ('src/lab_commons/dev/famtests/echoedtoken.py',)

#: MEASURED 2026-09-18 over :data:`ROOTS`: 2338 function bodies. Set below the population with room,
#: and re-measured rather than widened when :data:`HEADROOM` stops covering the gap.
FUNCTION_FLOOR: Final = 2000

#: How far past the floor the population may grow before the floor is re-measured.
HEADROOM: Final = 1200


def take() -> echoedtoken.EchoScan:
    """One walk for this repo, so no arm below reads a different tree than the one it judges."""
    return echoedtoken.take_scan(ROOT, roots=ROOTS, exempt=EXEMPT)


def test_every_exemption_names_a_file_that_is_here() -> None:
    """An exemption naming a deleted file covers nothing while still reading as a decision."""
    missing = [rel for rel in EXEMPT if not (ROOT / rel).is_file()]
    assert missing == [], f'exempted but absent: {missing}'


def test_no_clause_in_this_repo_checks_its_own_echo() -> None:
    """THE VERDICT, with the floor bound first so a walk that parsed nothing cannot read as clean."""
    echoedtoken.assert_no_clause_checks_its_own_echo(take(), floor=FUNCTION_FLOOR, headroom=HEADROOM)


def test_the_walk_reads_the_population_the_floor_was_measured_against() -> None:
    """The floor is a statement about SIZE, so the size is reported rather than only compared."""
    scan = take()
    assert scan.functions_read > FUNCTION_FLOOR, f'{scan.functions_read} bodies against a floor of {FUNCTION_FLOOR}'


def test_a_walk_that_reached_nothing_is_refused_rather_than_reported_clean() -> None:
    """PLANTED: the state this scanner is most likely to hide behind, since its clean answer is common."""
    empty = echoedtoken.EchoScan(functions_read=0, offenders=())
    with pytest.raises(floors.FloorUnmet):
        echoedtoken.assert_no_clause_checks_its_own_echo(empty, floor=FUNCTION_FLOOR, headroom=HEADROOM)


def test_a_floor_that_has_stopped_binding_is_refused_too() -> None:
    """THE OTHER SIDE OF THE RATCHET: a floor the population outgrew is a waiver nothing uses."""
    grown = echoedtoken.EchoScan(functions_read=FUNCTION_FLOOR + HEADROOM + 1, offenders=())
    with pytest.raises(floors.SlackFloor):
        echoedtoken.assert_no_clause_checks_its_own_echo(grown, floor=FUNCTION_FLOOR, headroom=HEADROOM)


def test_an_offender_is_refused_and_the_refusal_names_the_site() -> None:
    """A count could only say that one exists. The site is what a reader has to go and look at."""
    dirty = echoedtoken.EchoScan(
        functions_read=FUNCTION_FLOOR + 1,
        offenders=('a/b.py:4: arm(): word is searched for in text, which was built from it',),
    )
    with pytest.raises(echoedtoken.EchoedToken, match=r'a/b\.py:4'):
        echoedtoken.assert_no_clause_checks_its_own_echo(dirty, floor=FUNCTION_FLOOR, headroom=HEADROOM)


def test_the_scanner_names_the_planted_echo_and_none_of_its_honest_neighbours(tmp_path: Path) -> None:
    """BOTH DIRECTIONS, THROUGH THE SHIPPED SCANNER, over a real tree it walks itself."""
    echoedtoken.assert_the_scanner_still_convicts(tmp_path, roots=ROOTS)


def test_the_control_refuses_to_run_with_no_roots(tmp_path: Path) -> None:
    """A control handed nothing walks nothing and passes in triumph, which is the vacuous green."""
    empty: Collection[tuple[str, str]] = ()
    with pytest.raises(AssertionError, match='pass in triumph'):
        echoedtoken.assert_the_scanner_still_convicts(tmp_path, roots=empty)


def test_a_membership_test_that_decides_nothing_is_left_alone(tmp_path: Path) -> None:
    """THE AXIS THE FIRST DRAFT WAS BLIND TO: an expression is not a claim.

    ``lab_commons.proc.kill_process_tree`` writes ``[pid] if pid in tree else []`` over a ``tree``
    its own call built, and that branch is real -- an unreadable process table returns an empty set.
    A scanner that could not tell a conditional from an assertion named it, and a guard that refuses
    correct code is deleted rather than obeyed.
    """
    planted = tmp_path / 'src/lab_commons/expression.py'
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(
        'def order(pid, closure):\n'
        '    tree = closure(pid)\n'
        '    return sorted(tree - {pid}) + ([pid] if pid in tree else [])\n',
        encoding='utf-8',
    )
    found = echoedtoken.take_scan(tmp_path, roots=ROOTS, exempt=()).offenders
    assert found == (), f'a conditional claims nothing, so it cannot be a claim that never fails: {found}'
