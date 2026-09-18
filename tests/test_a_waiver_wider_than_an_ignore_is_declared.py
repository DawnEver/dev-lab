"""THE TWO WAIVERS THAT ARE WIDER THAN AN IGNORE, and until today nothing in this family read either.

WHAT THIS CLOSES, AND WHY IT IS NOT THE MECHANISM THE STAGE WAS SCOPED FOR. R2's last open row asked
for a section-scoped ``famconfig`` base owning ``[tool.ruff]``, so that a consumer could not silently
ADD an ignore entry. MEASURED 2026-09-18 at HEAD, that property is already enforced and has been
since R1: ``test_the_kit_is_not_linted_less_than_what_it_ships.py`` holds the eight-code waiver set
with a 56-code ceiling and both ratchet sides, and
``test_the_config_census_is_measured.py::test_the_three_consumers_agree_on_the_select_and_diverge_by_five_codes_in_total``
pins every consumer's ignore DELTA as a named set. Both read ruff's RESOLVED CONFIG, so both are
file-agnostic and neither cares whether the table lives in ``ruff.toml`` or ``pyproject.toml``.

So the open hole was never the ignore list. It is the two waivers that grant MORE than an ignore does
and that every arm above is blind to:

* ``exclude`` -- ruff never opens the path. It drops all 58 selectors over a subtree and names no
  code, so it cannot appear in any reading stated over CODES. 13 live rows across the family,
  uncounted until this module.
* ``per-file-ignores`` -- a named code dropped over a glob. 17 live rows, and the three repos that
  have an opinion hold three DIFFERENT ones, which is only visible once they are in one table.

AND A THIRD, ONE LAYER DOWN: the readers themselves were parametrized over the one SPELLING the four
repos use. Ruff honours ``lint.extend-ignore`` and a deprecated top-level ``ignore`` as well, so a
consumer moving an entry across spellings would empty the census's reading while changing nothing
ruff does. ``_config_census.WAIVER_SPELLINGS`` is the table that closes it, and the planted control
below drives THAT table rather than the four checkouts -- because a control parametrized over repos
measures the arm against the last fix, and the axis that mattered here was spellings.

THE RATCHET HAS TWO SIDES, mechanised rather than described: a row that is not declared reds NAMED,
and a declared row no live config needs reds too, because a waiver nothing uses asserts a constraint
on code that no longer exists.

FLOORS, BOTH SIDES, through :mod:`lab_commons.dev.floors`. The low side says a reader that went
silent is INCONCLUSIVE rather than clean; the high side says a floor the population has outgrown has
stopped separating those two, and the remedy is to re-measure it. Every number arrives as a keyword
argument with no default: they are facts about these four checkouts on one day.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from _config_census import (
    CensusError,
    head_sha,
    reachable_repos,
    ruff_config,
    ruff_excludes,
    ruff_per_file_waivers,
    waiver_entries,
)
from _config_census_rows import MACHINE_EXCLUDES, PER_FILE_WAIVERS, REPO_PATHS, TREE_EXCLUDES

from lab_commons.dev.floors import FloorUnmet, SlackFloor, assert_floor, assert_floor_still_binds

#: The least reach that makes the consumer half evidence. lab-commons is always here and is never its
#: own consumer, so one sibling is the floor -- and the arms NAME the repos they did not reach.
REACH_FLOOR: Final[int] = 1

#: THE KIT'S OWN per-file waivers. MEASURED 2026-09-18 at 10 rows, all of them `tests/**`. The floor
#: is below that and the headroom above it, so the band is [8, 12]: a reader that returned nothing
#: reds on the low side, and the kit's own escape hatch growing past twelve reds on the high side
#: with the remedy being to re-measure rather than to widen. lab-commons is always reachable, so this
#: pair is the one arm here that can never be skipped for want of a sibling.
KIT_WAIVER_FLOOR: Final[int] = 8
KIT_WAIVER_HEADROOM: Final[int] = 4

#: THE FAMILY'S EXCLUDE POPULATION, source-hiding rows only, MEASURED 2026-09-18 at 13 across the
#: three consumers (`MACHINE_EXCLUDES` are not counted -- see that table for why). Band [8, 21].
EXCLUDE_FLOOR: Final[int] = 8
EXCLUDE_HEADROOM: Final[int] = 13


def _reached() -> dict:
    return reachable_repos(REPO_PATHS)


def _absent(reached: dict) -> list[str]:
    return sorted(set(REPO_PATHS) - set(reached))


# ------------------------------------------------------------------- arm 1: the excludes are named


def _at(repo: str, root: Path) -> str:
    """How a cross-repo reading names WHERE and WHEN it read, so a refusal is reproducible.

    A census reads three checkouts it does not own, each of which may be mid-lane. Without the sha a
    reader meeting one of these refusals cannot tell a stale row from another repo's in-flight work,
    and the family has already spent an afternoon on exactly that -- see `_config_census.head_sha`.
    Every reading here is taken at HEAD, so the sha is the whole answer to "which tree, at what point".
    """
    return f'{repo} at {(head_sha(root) or "an unresolvable HEAD")[:12]} (read at HEAD, not the working tree)'


def test_every_exclude_that_hides_source_is_a_declared_row() -> None:
    """ARM 1. The widest waiver in a ruff config may not arrive as a line nothing reads.

    Stated over the SOURCE-HIDING excludes only: `.git`, `.venv*` and `**/__version__.py` carry no
    file under review in any repo, so counting them would pad the ceiling with rows nobody would ever
    spend and make the number unreadable.
    """
    reached = _reached()
    assert len(reached) - 1 >= REACH_FLOOR, (
        f'{_absent(reached)} are not checked out beside this repo, so this arm measured only the kit; '
        f'a consumer reach below {REACH_FLOOR} is INCONCLUSIVE rather than green'
    )
    for repo, root in reached.items():
        live = ruff_excludes(root) - set(MACHINE_EXCLUDES)
        declared = set(TREE_EXCLUDES[repo])
        undeclared, stale = sorted(live - declared), sorted(declared - live)
        assert undeclared == [], (
            f'{_at(repo, root)} excludes {undeclared} from ruff entirely and no row declares it. An exclude is '
            f'the widest waiver a config can write -- all 58 selectors dropped over a subtree, no code '
            f'named -- so it is the one that must be typed into TREE_EXCLUDES with what the tree is. '
            f'The ceiling may only SHRINK.'
        )
        assert stale == [], (
            f'{_at(repo, root)} no longer excludes {stale} and the rows are still here. A waiver nothing uses is '
            f'as wrong as an undeclared one: delete the rows in the edit that observed it.'
        )


def test_the_exclude_population_still_binds_its_floor() -> None:
    """The floor under arm 1, BOTH SIDES, so a reader that went quiet cannot read as a clean family."""
    reached = _reached()
    assert len(reached) - 1 >= REACH_FLOOR, f'{_absent(reached)} absent; the floor would measure the kit alone'
    found = sum(len(ruff_excludes(root) - set(MACHINE_EXCLUDES)) for root in reached.values())
    what = 'family ruff source-hiding exclude'
    assert_floor(found, floor=EXCLUDE_FLOOR, what=what)
    assert_floor_still_binds(found, floor=EXCLUDE_FLOOR, headroom=EXCLUDE_HEADROOM, what=what)


def test_the_kit_excludes_nothing_which_is_what_makes_the_zero_reachable() -> None:
    """The counter-example that keeps arm 1 from reading as a law of nature.

    A ceiling over thirteen rows is only a ceiling if zero is attainable. The repo that SHIPS the
    standard opens every file it tracks, so it is.
    """
    kit = reachable_repos(REPO_PATHS)['lab-commons']
    assert ruff_excludes(kit) == frozenset(), (
        f'lab-commons now excludes {sorted(ruff_excludes(kit))}. The kit holding an exclude is the '
        f'"held to less than what it ships" shape one layer out, and it removes the evidence that the '
        f'floor of this ratchet is reachable at all.'
    )
    assert TREE_EXCLUDES['lab-commons'] == ()


# --------------------------------------------------------- arm 2: the per-file waivers are named


def test_every_per_file_waiver_is_a_declared_row() -> None:
    """ARM 2. A code dropped over a glob is a waiver, and it is declared or it reds -- both ways."""
    reached = _reached()
    assert len(reached) - 1 >= REACH_FLOOR, f'{_absent(reached)} absent; this arm measured only the kit'
    for repo, root in reached.items():
        live = ruff_per_file_waivers(root)
        declared = set(PER_FILE_WAIVERS[repo])
        undeclared, stale = sorted(live - declared), sorted(declared - live)
        assert undeclared == [], (
            f'{_at(repo, root)} waives {undeclared} over a path and no row declares it. A per-file ignore is '
            f'invisible to every arm stated over the GLOBAL ignore list, which is every other ruff arm '
            f'in this family, so this table is the only thing that can see it grow.'
        )
        assert stale == [], (
            f'{_at(repo, root)} no longer waives {stale} and the rows are still here -- a waiver nothing uses. '
            f'Delete them in the edit that observed it; that is what makes the ceiling worth having.'
        )


def test_the_kits_own_per_file_waivers_still_bind_their_floor() -> None:
    """The floor under arm 2, BOTH SIDES, and it is stated over the ONE repo always reachable here."""
    kit = reachable_repos(REPO_PATHS)['lab-commons']
    found = len(ruff_per_file_waivers(kit))
    what = "lab-commons' own ruff per-file waiver"
    assert_floor(found, floor=KIT_WAIVER_FLOOR, what=what)
    assert_floor_still_binds(found, floor=KIT_WAIVER_FLOOR, headroom=KIT_WAIVER_HEADROOM, what=what)


def test_motronics_holds_the_zero_and_it_is_a_principle_rather_than_an_accident() -> None:
    """The row that makes the family's disagreement legible instead of averaging it away.

    motronics waives nothing per file under a 2026-08-02 user directive its own `ruff.toml` states in
    full, and its `test_suppression_ratchet.py` pins the table at zero pairs. optimi-lab also holds
    zero and declares nothing about it. Two zeros, one of them load-bearing.
    """
    reached = _reached()
    lane = reached.get('motronics-studio')
    if lane is None:
        pytest.skip('the motronics lane is not checked out beside this repo')
    assert ruff_per_file_waivers(lane) == frozenset(), (
        'the motronics lane grew a per-file ignore. That table is EMPTY BY PRINCIPLE there and the '
        'principle is written in the file: a waiver belongs in the file it governs as a noqa comment carrying '
        'a measured reason. A row here is that directive being reversed somewhere else.'
    )
    assert PER_FILE_WAIVERS['motronics-studio'] == ()


# ------------------------------------------------------------------------------ planted controls


#: THE AXIS THE CONTROL IS PARAMETRIZED OVER IS SPELLING, and naming it is the point. Every row is a
#: config ruff honours and the pre-2026-09-18 reader did not: an `extend-` form, or the deprecated
#: top-level form ruff still accepts. A control over REPOS would pass every one of these, because no
#: repo uses any of them TODAY -- which is exactly the shape that let a round-trip arm measure the
#: resolver against the last fix rather than against the language.
_SPELLING_CONTROLS: Final[tuple[tuple[str, dict, str], ...]] = (
    ('ignore', {'lint': {'ignore': ['E501']}}, 'E501'),
    ('ignore', {'lint': {'extend-ignore': ['E501']}}, 'E501'),
    ('ignore', {'ignore': ['E501']}, 'E501'),
    ('ignore', {'extend-ignore': ['E501']}, 'E501'),
    ('select', {'lint': {'extend-select': ['ANN']}}, 'ANN'),
    ('select', {'select': ['ANN']}, 'ANN'),
    ('exclude', {'exclude': ['attic']}, 'attic'),
    ('exclude', {'extend-exclude': ['attic']}, 'attic'),
    ('exclude', {'lint': {'exclude': ['attic']}}, 'attic'),
    ('exclude', {'format': {'extend-exclude': ['attic']}}, 'attic'),
    ('per-file-ignores', {'lint': {'per-file-ignores': {'tests/**': ['S101']}}}, 'tests/**::S101'),
    ('per-file-ignores', {'lint': {'extend-per-file-ignores': {'tests/**': ['S101']}}}, 'tests/**::S101'),
    ('per-file-ignores', {'per-file-ignores': {'tests/**': ['S101']}}, 'tests/**::S101'),
)


@pytest.mark.parametrize(('kind', 'config', 'entry'), _SPELLING_CONTROLS)
def test_the_reader_is_driven_over_spellings_and_not_over_the_four_checkouts(
    kind: str, config: dict, entry: str
) -> None:
    """PLANTED CONTROL, THROUGH THE READER THE ARMS USE. Each spelling must be SEEN, not assumed absent."""
    assert entry in waiver_entries(config, kind), (
        f'{kind} written as {config} read empty. Ruff honours that spelling, so a consumer moving one '
        f'entry into it would empty every arm above while changing nothing ruff does.'
    )


@pytest.mark.parametrize('key', ['force-exclude', 'respect-gitignore', 'preview', 'line-length'])
def test_a_key_that_is_not_a_waiver_is_not_read_as_one(key: str) -> None:
    """THE OTHER SIDE OF THE CONTROL. A reader that found waivers everywhere would be noise.

    `force-exclude` is the trap: it sits beside `exclude`, contains the word, and is a BOOLEAN about
    how exclusion applies to explicitly-passed paths. Reading it as an exclude would add a phantom row
    to wdg-lab's ceiling, and a ratchet with a phantom row cannot be spent.
    """
    assert waiver_entries({key: True, 'lint': {}}, 'exclude') == frozenset()
    assert waiver_entries({key: True, 'lint': {}}, 'per-file-ignores') == frozenset()


def test_an_undeclared_waiver_is_NAMED_by_the_arm_and_not_merely_counted() -> None:
    """THE ARM'S OWN REFUSAL, PLANTED, against a config that cannot exist in any checkout here."""
    planted = {'exclude': ['attic', '.git', 'src/secret_tree'], 'lint': {'per-file-ignores': {'src/**': ['S101']}}}
    live_excludes = waiver_entries(planted, 'exclude') - set(MACHINE_EXCLUDES)
    undeclared = sorted(live_excludes - set(TREE_EXCLUDES['motronics-studio']))
    assert undeclared == ['src/secret_tree'], (
        f'the refusal reported {undeclared}. It must NAME the row -- a count cannot say which exclude '
        f'appeared, and the honest-looking repair when a digit disagrees is to edit the digit.'
    )
    assert sorted(waiver_entries(planted, 'per-file-ignores')) == ['src/**::S101']


def test_a_declared_row_no_live_config_needs_is_NAMED_by_the_other_side_of_the_ratchet() -> None:
    """THE CONTROL FOR THE DIRECTION THIS TABLE ACTUALLY MOVED IN, and it had none until today.

    Both arms above assert `stale == []` as well as `undeclared == []`, and only the UNDECLARED half
    was ever driven on a doctored input. That is the half a growing table exercises; the half a
    SHRINKING one exercises is stale, and five exclude rows plus two per-file rows were deleted here
    on the strength of an arm no control had watched red. So this plants the shrink: a config that
    has given a waiver up, read against a table that still declares it.

    THE AXIS THIS CONTROL IS BLIND TO: it drives the SET ARITHMETIC, not the READER. A
    `ruff_excludes` that returned the empty set for every checkout would make every declared row look
    stale in exactly this shape, and this control would still pass -- which is what the floor arms and
    the spelling controls are for, and why neither of them may be deleted in favour of this one.
    """
    give_up = {'exclude': ['ignore'], 'lint': {'per-file-ignores': {'examples/tasks/**': ['T201']}}}
    live_excludes = waiver_entries(give_up, 'exclude') - set(MACHINE_EXCLUDES)
    stale = sorted(set(TREE_EXCLUDES['wdg-lab']) - live_excludes)
    assert stale == ['.claude', 'archived', 'output'], (
        f'the stale side reported {stale}. It must NAME the rows whose config line is gone, because '
        f'the edit it asks for is a DELETION and a count cannot say which line to delete.'
    )
    stale_waivers = sorted(set(PER_FILE_WAIVERS['wdg-lab']) - waiver_entries(give_up, 'per-file-ignores'))
    assert 'scripts/*.py::T201' in stale_waivers
    assert 'examples/tasks/**::T201' not in stale_waivers


def test_the_exclude_band_reds_on_both_sides_at_the_numbers_it_was_re_taken_at() -> None:
    """BOTH SIDES OF THE RE-TAKEN EXCLUDE BAND, PLANTED, so [2, 15] is driven and not just written.

    The floor moved 8 -> 2 in the same edit that deleted five of the rows it counted. A re-taken
    number that no control drives is a digit somebody edited, so both bounds are exercised here
    against the live measurement's neighbours rather than against the measurement itself.
    """
    what = 'planted family exclude'
    with pytest.raises(FloorUnmet):
        assert_floor(EXCLUDE_FLOOR - 1, floor=EXCLUDE_FLOOR, what=what)
    with pytest.raises(SlackFloor):
        assert_floor_still_binds(
            EXCLUDE_FLOOR + EXCLUDE_HEADROOM + 1, floor=EXCLUDE_FLOOR, headroom=EXCLUDE_HEADROOM, what=what
        )
    assert_floor(EXCLUDE_FLOOR, floor=EXCLUDE_FLOOR, what=what)
    assert_floor_still_binds(EXCLUDE_FLOOR, floor=EXCLUDE_FLOOR, headroom=EXCLUDE_HEADROOM, what=what)


def test_a_reader_that_went_silent_reds_on_the_low_side_and_a_stale_floor_on_the_high() -> None:
    """BOTH SIDES OF THE FLOOR, PLANTED, through the same `dev.floors` calls the arms make."""
    what = 'planted waiver'
    with pytest.raises(FloorUnmet):
        assert_floor(0, floor=KIT_WAIVER_FLOOR, what=what)
    with pytest.raises(SlackFloor):
        assert_floor_still_binds(
            KIT_WAIVER_FLOOR + KIT_WAIVER_HEADROOM + 1, floor=KIT_WAIVER_FLOOR, headroom=KIT_WAIVER_HEADROOM, what=what
        )
    assert_floor(KIT_WAIVER_FLOOR, floor=KIT_WAIVER_FLOOR, what=what)


def test_a_waiver_kind_the_table_does_not_declare_is_refused_rather_than_read_empty() -> None:
    """An unsupported kind RAISES. Returning an empty set would make a typo read as a clean config."""
    with pytest.raises(CensusError, match='not a declared waiver kind'):
        waiver_entries({'lint': {'ignore': ['E501']}}, 'ignores')


def test_the_resolved_config_is_what_is_read_so_the_arms_do_not_care_which_file_holds_it() -> None:
    """WHY NO SECTION-SCOPED BASE IS NEEDED HERE: every arm reads the config ruff RESOLVES.

    motronics keeps its table in `ruff.toml` and the other three in `[tool.ruff]`. `ruff_config`
    applies ruff's own precedence, so relocating that table between the two files moves nothing any
    arm in this family measures -- which is the measurement that turns the FILE question from a
    prerequisite into a free choice.
    """
    reached = _reached()
    for repo, root in reached.items():
        config = ruff_config(root)
        assert config, f'{repo}: the resolved ruff config read EMPTY, so every arm over it is vacuous'
        assert ruff_excludes(root) == waiver_entries(config, 'exclude')
        assert ruff_per_file_waivers(root) == waiver_entries(config, 'per-file-ignores')
