"""The controls for :mod:`lab_commons.dev.famtests.rostercensus` -- every arm driven in BOTH directions.

WHAT IS PROVED HERE, and it is deliberately not "the census works": that is
:mod:`lab_commons.dev.supersede`'s own test file, and re-asserting it here would be two answers to one
question. What this file owns is the ARMS a consumer calls -- that each one FIRES on a planted
violation and STAYS SILENT on the honest shape beside it. A detector that never fires reports exactly
what a clean roster reports, which is the blind spot that let a six-module import gap survive across
two repos until it was driven rather than read.

EVERY NO-DEFAULT ARGUMENT GETS ITS OWN COUNTER-CONTROL. It is not enough that *moves_side* and
*package* are required by the signature; what makes them worth requiring is that a WRONG value
reports CLEAN rather than raising, so the wrong one is planted and the silence is asserted. That is
the ``LAB_CZ_BASE_REF`` shape stated as a test instead of as prose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import floors, supersede
from lab_commons.dev.famtests.rostercensus import (
    SUBPACKAGE_IMPORT,
    EmptyWaiver,
    UnadoptedWaiver,
    UnresolvedKit,
    assert_every_waived_row_adopted,
    assert_no_stale_moves,
    assert_reach,
    assert_the_grader_still_convicts,
    assert_waiver_is_the_named_set,
    kit_directory,
    named_only_paths,
    stale_moves,
)

#: The kit's own dotted path, spelled in full for the reason the module docstring gives.
PACKAGE = 'lab_commons.dev'

#: One repo's spelling of the move side. Planted rather than imported, so nothing here depends on a
#: consumer's vocabulary -- which is the fact the signature refuses to guess.
MOVES = 'MOVES'


def claim(path: str, *, side: str, grade: str, module: str | None = 'checkout') -> supersede.Claim:
    """A graded row, built directly so an arm is driven without a whole roster behind it."""
    return supersede.Claim(
        path=path,
        side=side,
        kit_module=module,
        detectors=(supersede.PROVENANCE,),
        covered=(),
        remainder=(),
        grade=grade,
    )


def census(*claims: supersede.Claim, modules_read: int = 46) -> supersede.Census:
    """A census over *claims*, with ``rows_read`` derived so a caller cannot desynchronise the two."""
    return supersede.Census(claims=claims, rows_read=len(claims), modules_read=modules_read)


def test_the_kit_directory_resolves_and_is_the_directory_the_census_reads() -> None:
    """The live half: the installed kit resolves, and what comes back is really the kit."""
    found = kit_directory(package=PACKAGE)
    assert found.is_dir(), f'{found} is not a directory, so `kit_modules` would read nothing'
    assert (found / 'supersede.py').is_file(), (
        f'{found} resolved without the module every consumer of this body imports, so the spec '
        f'answered about some other package.'
    )


def test_an_unresolvable_package_refuses_instead_of_returning_a_directory() -> None:
    """THE CONTROL for the resolution: a kit that is not there must RAISE, never read as empty."""
    with pytest.raises(UnresolvedKit, match='does not resolve to a package'):
        kit_directory(package='lab_commons.dev.no_such_kit_directory')


def test_the_reach_arm_passes_only_when_every_declared_row_was_judged() -> None:
    """EQUALITY on rows, a FLOOR on modules -- and each refuses on its own."""
    taken = census(claim('a.py', side=MOVES, grade=supersede.UNTOUCHED))
    assert_reach(taken, rows_declared=1, module_floor=35, module_headroom=16)
    with pytest.raises(AssertionError, match='judged 1 of 2 declared rows'):
        assert_reach(taken, rows_declared=2, module_floor=35, module_headroom=16)
    with pytest.raises(supersede.VacuousCensus, match='below the 99 floor'):
        assert_reach(taken, rows_declared=1, module_floor=99, module_headroom=16)


def test_the_reach_arm_now_has_the_side_both_labs_had_to_write_by_hand() -> None:
    """THE SECOND SIDE, PLANTED IN BOTH DIRECTIONS, and this arm did not exist until 2026-09-18.

    `assert_reach` refused an UNDER-read kit and said nothing whatever about a floor the kit had
    OUTGROWN, so `KIT_MODULE_FLOOR` sat at 35 in both labs through a kit that grew 46 -> 51 -> 56 --
    a floor that would have passed a kit which had lost three fifths of itself. The remedy a
    `SlackFloor` names is to RE-MEASURE THE FLOOR, never to widen the headroom, which is why the
    headroom arrives as a keyword argument with no default rather than as a number chosen here.

    THE AXIS THIS CONTROL IS BLIND TO: it drives the arithmetic of the band, not what
    `kit_modules` counted. A resolver that reported 46 modules of the WRONG package clears every
    assertion below -- that claim belongs to `supersede`, which calls surface overlap a RULER.
    """
    taken = census(claim('a.py', side=MOVES, grade=supersede.UNTOUCHED), modules_read=46)
    assert_reach(taken, rows_declared=1, module_floor=35, module_headroom=11)
    with pytest.raises(floors.SlackFloor, match='RE-MEASURE THE FLOOR'):
        assert_reach(taken, rows_declared=1, module_floor=35, module_headroom=10)
    with pytest.raises(floors.FloorMisdeclared, match='headroom'):
        assert_reach(taken, rows_declared=1, module_floor=35, module_headroom=0)


def test_a_module_floor_of_zero_is_refused_as_the_vacuity_written_down() -> None:
    """THE FLOOR'S OWN FLOOR. A floor that refuses nothing is how a kit nobody read reads green."""
    taken = census(claim('a.py', side=MOVES, grade=supersede.UNTOUCHED), modules_read=0)
    with pytest.raises(supersede.VacuousCensus, match='refuses nothing'):
        assert_reach(taken, rows_declared=1, module_floor=0, module_headroom=16)


def test_a_flagged_row_on_the_moves_side_is_named_and_an_unflagged_one_is_not() -> None:
    """THE CHECK, both directions: the duplicate is convicted and the honest neighbour is left alone."""
    taken = census(
        claim('scripts/repo/worktree_debris.py', side=MOVES, grade=supersede.SUPERSEDED),
        claim('scripts/repo/own.py', side=MOVES, grade=supersede.UNTOUCHED),
        claim('scripts/repo/split.py', side='SPLITS', grade=supersede.PARTIAL),
    )
    assert stale_moves(taken, moves_side=MOVES) == {
        'scripts/repo/worktree_debris.py': 'superseded against `checkout`',
    }, 'only a FLAGGED row on the MOVES side is stale; a split and an untouched row are not'
    with pytest.raises(AssertionError, match='worktree_debris'):
        assert_no_stale_moves(taken, moves_side=MOVES)


def test_a_guessed_moves_label_reports_the_roster_clean_which_is_why_it_has_no_default() -> None:
    """THE COUNTER-CONTROL for the one argument whose wrong value is SILENT rather than loud.

    This is the ``LAB_CZ_BASE_REF`` shape in miniature: the wrong answer does not raise, it widens
    the scope until nothing matches and then reports a pass. A default here would ship that pass.
    """
    taken = census(claim('scripts/repo/worktree_debris.py', side=MOVES, grade=supersede.SUPERSEDED))
    assert stale_moves(taken, moves_side='moves') == {}, 'the plant must be invisible under the wrong label'
    assert_no_stale_moves(taken, moves_side='moves')
    assert stale_moves(taken, moves_side=MOVES), (
        'the same census must convict under the right label, or the silence above says nothing'
    )


def test_the_waiver_is_compared_by_equality_in_both_directions() -> None:
    """An arrival is a real stale row; a departure is the fix landing and must red just as loudly."""
    taken = census(
        claim('tests/a.py', side='STAYS', grade=supersede.NAMED_ONLY),
        claim('tests/b.py', side='STAYS', grade=supersede.CONSULTS),
    )
    assert named_only_paths(taken) == frozenset({'tests/a.py'})
    assert_waiver_is_the_named_set(taken, waived={'tests/a.py': 'allowguard'})
    with pytest.raises(AssertionError, match=r"arrived: \['tests/a.py'\]"):
        assert_waiver_is_the_named_set(taken, waived={'tests/other.py': 'allowguard'})
    with pytest.raises(AssertionError, match='adopted-and-still-waived'):
        assert_waiver_is_the_named_set(taken, waived={'tests/a.py': 'allowguard', 'tests/c.py': 'visibility'})


def test_an_empty_waiver_is_refused_so_the_arm_is_deleted_rather_than_pinned_at_zero() -> None:
    """THE RATCHET'S SECOND SIDE. A waiver nothing uses is as wrong as a capability that vanished."""
    taken = census(claim('tests/a.py', side='STAYS', grade=supersede.CONSULTS))
    assert not named_only_paths(taken), 'the fixture must be the fixed state, or the refusal below is ambiguous'
    with pytest.raises(EmptyWaiver, match='DELETE the arm'):
        assert_waiver_is_the_named_set(taken, waived={})


def test_a_waived_row_must_prove_its_adoption_by_its_own_text(tmp_path: Path) -> None:
    """THE CEILING ON THE WAIVER, planted three ways: adopted, unadopted, and unplaced."""
    adopted = tmp_path / 'tests' / 'adopted.py'
    adopted.parent.mkdir(parents=True)
    adopted.write_text(f'{SUBPACKAGE_IMPORT}allowguard\n', encoding='utf-8')
    (tmp_path / 'tests' / 'silent.py').write_text('import os\n', encoding='utf-8')

    placed = frozenset({'tests/adopted.py', 'tests/silent.py'})
    assert_every_waived_row_adopted(root=tmp_path, path='tests/adopted.py', module='allowguard', placed=placed)
    with pytest.raises(UnadoptedWaiver, match='does not import it'):
        assert_every_waived_row_adopted(root=tmp_path, path='tests/silent.py', module='allowguard', placed=placed)
    with pytest.raises(UnadoptedWaiver, match='no placement row'):
        assert_every_waived_row_adopted(root=tmp_path, path='tests/adopted.py', module='allowguard', placed=frozenset())


def test_a_waiver_naming_the_wrong_module_does_not_pass_on_the_files_other_import(tmp_path: Path) -> None:
    """The proof reads the module NAME, not merely the import form -- otherwise any adoption waives all."""
    path = tmp_path / 'tests' / 'adopted.py'
    path.parent.mkdir(parents=True)
    path.write_text(f'{SUBPACKAGE_IMPORT}allowguard\n', encoding='utf-8')
    with pytest.raises(UnadoptedWaiver, match='`visibility`'):
        assert_every_waived_row_adopted(
            root=tmp_path, path='tests/adopted.py', module='visibility', placed=frozenset({'tests/adopted.py'})
        )


def test_the_planted_control_holds_against_the_grader_that_ships_today() -> None:
    """The body a consumer calls to prove its own census is not silent, run here against this kit."""
    assert_the_grader_still_convicts(moves_side=MOVES)
    assert_the_grader_still_convicts(moves_side='anything-the-roster-calls-it')


def test_the_body_takes_a_real_census_end_to_end_against_the_installed_kit() -> None:
    """THE INTEGRATION ARM: the pieces compose, and the kit read is a real one rather than a floor."""
    modules = supersede.kit_modules(kit_directory(package=PACKAGE))
    taken = supersede.take_census(
        {'tests/_arch_corpus.py': 'STAYS', 'tests/test_dev_supersede.py': 'STAYS'},
        modules,
        root=Path(__file__).resolve().parents[1],
        package=PACKAGE,
        row_floor=2,
        module_floor=35,
    )
    assert_reach(taken, rows_declared=2, module_floor=35, module_headroom=len(modules) - 35 + 1)
    assert_no_stale_moves(taken, moves_side=MOVES)
    assert len(modules) >= 35, (
        f'{len(modules)} kit modules read; a census over a kit nobody read grades every row UNTOUCHED'
    )
