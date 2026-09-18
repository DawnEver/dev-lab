"""The controls for :mod:`lab_commons.dev.famtests.datedmemory` -- every reader and arm, both ways.

WHAT IS PROVED HERE. Not "the walk works": what this file owns is that each reader FIRES on a
planted offender and STAYS SILENT on the honest neighbour beside it. A reader that names everything
and a reader that names nothing both pass a one-sided test, and the second of those is
indistinguishable from a clean tree -- which is how a six-module import gap survived two repos until
somebody drove it rather than read it.

EVERY NO-DEFAULT ARGUMENT GETS A COUNTER-CONTROL. The signature requiring *trees*,
*non_entry_names*, *not_walked* and *floor* is not the argument for them. The argument is that a
WRONG value reports CLEAN rather than raising: a wrong exclusion set removes files from the
population, a wrong tree list walks nothing, and both then report a tree with no offenders in it. So
the wrong value is planted and the silence is asserted directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests.datedmemory import (
    DATE_DEPTH,
    MemoryScan,
    ParallelTree,
    assert_dates_agree,
    assert_every_entry_is_dated,
    assert_silent_entries_are_the_named_set,
    assert_the_readers_still_convict,
    assert_trees_are_the_named_set,
    date_disagreements,
    entries,
    memory_trees,
    silent,
    take_scan,
    undated,
)

#: One repo's exclusion sets. Planted rather than imported, so nothing here depends on a consumer's
#: answer -- which is the fact the signatures refuse to guess.
DEBRIS = frozenset({'_meta.json', '.gitkeep'})
NOT_WALKED = frozenset({'.git', '.venv', '__pycache__', 'node_modules'})


def plant(root: Path, relative: str, body: str) -> Path:
    """Write *body* at *relative* under *root*, parents made -- a real file for a real reader."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


def a_tree(root: Path) -> Path:
    """The four-shape fixture every reader below is driven over: one of each, plus honest neighbours."""
    plant(root, '2026/09/18/agrees.md', '---\nname: a\ncreated: 2026-09-18\n---\n# a\n')
    plant(root, '2026/09/18/stale.md', '---\nname: b\ncreated: 2026-09-04\n---\n# b\n')
    plant(root, '2026/09/18/quiet.md', '# c\n')
    plant(root, '2026/09/18/attachments/figure.txt', 'below the date is fine\n')
    plant(root, '2026/09/18/_meta.json', '{}')
    plant(root, 'lanes/a-lane.md', '---\ncreated: 2026-09-18\n---\n')
    plant(root, 'loose.md', '---\ncreated: 2026-09-18\n---\n')
    return root


def test_the_population_excludes_what_the_repo_declares_not_an_entry(tmp_path: Path) -> None:
    """Debris out, records in -- and a real fork is in NEITHER exclusion set and still arrives."""
    found = entries(a_tree(tmp_path), non_entry_names=DEBRIS, not_walked=NOT_WALKED)
    names = {path.name for path in found}
    assert '_meta.json' not in names, 'tooling debris must not enter the population a floor is bound to'
    assert {'agrees.md', 'stale.md', 'quiet.md', 'figure.txt', 'a-lane.md', 'loose.md'} == names


def test_a_wrong_exclusion_set_shrinks_the_population_silently(tmp_path: Path) -> None:
    """THE COUNTER-CONTROL for the argument with no default whose wrong value is SILENT, not loud."""
    a_tree(tmp_path)
    honest = entries(tmp_path, non_entry_names=DEBRIS, not_walked=NOT_WALKED)
    by_name = entries(tmp_path, non_entry_names={'a-lane.md'}, not_walked=NOT_WALKED)
    by_directory = entries(tmp_path, non_entry_names=DEBRIS, not_walked={'lanes'})
    assert 'lanes/a-lane.md' in undated(tmp_path, honest), (
        'the fork must be convicted under the sets this repo really declares, or the silence below says nothing'
    )
    for guessed in (by_name, by_directory):
        assert 'lanes/a-lane.md' not in undated(tmp_path, guessed), (
            'a guessed exclusion set does not RAISE -- it removes the offender from the population, and the '
            'reader then has nothing left to name. EITHER argument alone can do it, which is why NEITHER '
            'has a default.'
        )


def test_the_shape_reader_names_the_fork_and_leaves_the_nesting_alone(tmp_path: Path) -> None:
    """THE CONTROL for ``undated``: both offenders come back, and nesting BELOW the date does not."""
    found = entries(a_tree(tmp_path), non_entry_names=DEBRIS, not_walked=NOT_WALKED)
    assert undated(tmp_path, found) == ('lanes/a-lane.md', 'loose.md')
    assert DATE_DEPTH == 3, 'the layout these readers are about is YYYY/MM/DD -- four digits, no kind'


def test_silent_and_disagreeing_are_two_populations_and_not_one(tmp_path: Path) -> None:
    """The split this module publishes: a pin over a mixture cannot say WHICH half moved."""
    found = entries(a_tree(tmp_path), non_entry_names=DEBRIS, not_walked=NOT_WALKED)
    assert silent(tmp_path, found) == ('2026/09/18/quiet.md',), 'the entry with no field, and only it'
    assert date_disagreements(tmp_path, found) == {'2026/09/18/stale.md': '2026-09-04'}, (
        'the entry whose header contradicts its directory, pinned WITH the date it claims'
    )
    assert set(silent(tmp_path, found)).isdisjoint(date_disagreements(tmp_path, found)), (
        'no entry may be named by both readers, or one fix would red two arms'
    )


def test_an_undated_entry_is_named_once_and_not_by_the_frontmatter_readers(tmp_path: Path) -> None:
    """``lanes/a-lane.md`` is undated AND dates itself; only the shape reader may claim it."""
    a_tree(tmp_path)
    plant(tmp_path, 'notes/nofield.md', '# no field at all\n')
    found = entries(tmp_path, non_entry_names=DEBRIS, not_walked=NOT_WALKED)
    assert 'notes/nofield.md' in undated(tmp_path, found)
    assert 'notes/nofield.md' not in silent(tmp_path, found), (
        'an undated entry is already named by the shape reader; naming it again would make one move fix '
        'one arm and red another.'
    )


def test_the_trees_are_a_named_set_compared_in_both_directions(tmp_path: Path) -> None:
    """An arrival is a fork nobody decided on; a disappearance means a scan stopped covering a tree."""
    (tmp_path / '.claude' / 'memory').mkdir(parents=True)
    (tmp_path / 'sub' / '.claude' / 'memory').mkdir(parents=True)
    declared = ('.claude/memory', 'sub/.claude/memory')
    assert memory_trees(tmp_path, not_walked=NOT_WALKED) == declared
    assert_trees_are_the_named_set(tmp_path, declared=declared, not_walked=NOT_WALKED)
    with pytest.raises(AssertionError, match=r"appeared: \['sub/.claude/memory'\]"):
        assert_trees_are_the_named_set(tmp_path, declared=('.claude/memory',), not_walked=NOT_WALKED)
    with pytest.raises(AssertionError, match='declared and not found'):
        assert_trees_are_the_named_set(tmp_path, declared=(*declared, 'gone/.claude/memory'), not_walked=NOT_WALKED)


def test_a_not_walked_directory_hides_a_tree_which_is_why_it_has_no_default(tmp_path: Path) -> None:
    """THE COUNTER-CONTROL for ``not_walked``: the wrong set does not raise, it stops finding trees."""
    (tmp_path / '.claude' / 'memory').mkdir(parents=True)
    (tmp_path / 'node_modules' / '.claude' / 'memory').mkdir(parents=True)
    assert memory_trees(tmp_path, not_walked=NOT_WALKED) == ('.claude/memory',)
    assert memory_trees(tmp_path, not_walked=()) == ('.claude/memory', 'node_modules/.claude/memory'), (
        'with nothing excluded the vendored tree arrives, so the exclusion is a real decision the repo '
        'makes rather than a formality'
    )


def test_the_scan_qualifies_every_row_by_its_tree(tmp_path: Path) -> None:
    """Five trees, one pinned set: a row must say which tree it is in or the pin is ambiguous."""
    a_tree(tmp_path / '.claude' / 'memory')
    plant(tmp_path / 'sub' / '.claude' / 'memory', '2026/09/18/quiet.md', '# c\n')
    scan = take_scan(
        tmp_path,
        trees=('.claude/memory', 'sub/.claude/memory'),
        non_entry_names=DEBRIS,
        not_walked=NOT_WALKED,
    )
    assert scan.entries_read == 7, scan
    assert scan.undated == ('.claude/memory/lanes/a-lane.md', '.claude/memory/loose.md')
    assert scan.silent == ('.claude/memory/2026/09/18/quiet.md', 'sub/.claude/memory/2026/09/18/quiet.md'), (
        'the same basename in two trees must be two distinct rows, or a fix in one tree would satisfy '
        'the pin for the other'
    )
    assert scan.disagreements == {'.claude/memory/2026/09/18/stale.md': '2026-09-04'}


def test_a_declared_tree_that_is_not_there_contributes_nothing_and_the_floor_catches_it(tmp_path: Path) -> None:
    """A missing tree is not an exception here: it is a smaller population, which the floor refuses."""
    scan = take_scan(tmp_path, trees=('.claude/memory',), non_entry_names=DEBRIS, not_walked=NOT_WALKED)
    assert scan.entries_read == 0
    with pytest.raises(floors.FloorUnmet, match='dated-memory'):
        assert_every_entry_is_dated(scan, floor=1, headroom=500)


def test_the_floor_is_bound_before_a_single_offender_is_looked_at(tmp_path: Path) -> None:
    """THE POINT OF THE HALF: "no undated entries" and "no entries at all" are not the same answer."""
    empty = MemoryScan(trees=('.claude/memory',), entries_read=0, undated=(), silent=(), disagreements={})
    assert not empty.undated, 'an empty walk reports exactly what a clean tree reports'
    with pytest.raises(floors.FloorUnmet):
        assert_every_entry_is_dated(empty, floor=300, headroom=500)
    del tmp_path


def test_the_floors_second_side_refuses_a_number_the_tree_has_outgrown() -> None:
    """A floor of 1 against 4000 entries refuses only a total collapse -- re-measure it, do not keep it."""
    grown = MemoryScan(trees=('.claude/memory',), entries_read=4000, undated=(), silent=(), disagreements={})
    assert_every_entry_is_dated(grown, floor=3500, headroom=1000)
    with pytest.raises(floors.SlackFloor, match='RE-MEASURE THE FLOOR'):
        assert_every_entry_is_dated(grown, floor=1, headroom=1000)


def test_a_fork_above_the_floor_is_refused_as_a_parallel_tree() -> None:
    """The check itself, with the floor satisfied so the refusal is about the tree and not the walk."""
    scan = MemoryScan(
        trees=('.claude/memory',),
        entries_read=352,
        undated=('.claude/memory/lanes/a-lane.md',),
        silent=(),
        disagreements={},
    )
    with pytest.raises(ParallelTree, match='The date is the PATH'):
        assert_every_entry_is_dated(scan, floor=300, headroom=500)


def test_the_silent_debt_is_compared_by_equality_and_the_empty_set_is_a_legal_end_state() -> None:
    """Two-sided, and DELIBERATELY unlike rostercensus's waiver, which refuses an empty declaration."""
    scan = MemoryScan(trees=(), entries_read=352, undated=(), silent=('a/2026/09/18/x.md',), disagreements={})
    assert_silent_entries_are_the_named_set(scan, declared=('a/2026/09/18/x.md',))
    with pytest.raises(AssertionError, match=r"arrived: \['a/2026/09/18/x.md'\]"):
        assert_silent_entries_are_the_named_set(scan, declared=())
    with pytest.raises(AssertionError, match='fixed and still pinned'):
        assert_silent_entries_are_the_named_set(scan, declared=('a/2026/09/18/x.md', 'a/2026/09/18/y.md'))

    fixed = scan._replace(silent=())
    assert_silent_entries_are_the_named_set(fixed, declared=())
    with pytest.raises(AssertionError, match='fixed and still pinned'):
        assert_silent_entries_are_the_named_set(fixed, declared=('a/2026/09/18/x.md',))


def test_the_date_pin_carries_the_wrong_date_and_not_merely_the_name() -> None:
    """A name alone cannot tell a copied-forward header from a moved directory, so the value is pinned."""
    scan = MemoryScan(trees=(), entries_read=352, undated=(), silent=(), disagreements={'a/x.md': '2026-09-04'})
    assert_dates_agree(scan, declared={'a/x.md': '2026-09-04'})
    with pytest.raises(AssertionError, match='2026-09-04'):
        assert_dates_agree(scan, declared={'a/x.md': '2026-09-05'})
    with pytest.raises(AssertionError):
        assert_dates_agree(scan, declared={})


def test_the_planted_control_holds_against_the_readers_that_ship_today(tmp_path: Path) -> None:
    """The body a consumer calls to prove its own scan is not silent, run here against this kit."""
    assert_the_readers_still_convict(tmp_path / 'one', non_entry_names=DEBRIS)
    assert_the_readers_still_convict(tmp_path / 'two', non_entry_names={'_meta.json'})
    assert_the_readers_still_convict(tmp_path / 'three', non_entry_names=())


def test_the_planted_control_would_fail_if_a_reader_stopped_convicting(tmp_path: Path) -> None:
    """THE CONTROL'S OWN CONTROL: the body must be able to FAIL, or calling it proves nothing.

    Driven by handing it a root that already holds the fork it is about to plant, so the shape reader
    answers something other than the two names the body demands.
    """
    plant(tmp_path, 'notes/already-forked.md', '---\ncreated: 2026-09-18\n---\n')
    with pytest.raises(AssertionError, match='the shape reader named'):
        assert_the_readers_still_convict(tmp_path, non_entry_names=DEBRIS)


def test_a_binary_entry_does_not_stop_the_scan(tmp_path: Path) -> None:
    """A tree holds attachments. An undecodable byte must not take the guard down with it."""
    (tmp_path / '2026' / '09' / '18').mkdir(parents=True)
    (tmp_path / '2026' / '09' / '18' / 'shot.md').write_bytes(b'\xff\xfe not utf-8 \x00')
    found = entries(tmp_path, non_entry_names=DEBRIS, not_walked=NOT_WALKED)
    assert silent(tmp_path, found) == ('2026/09/18/shot.md',), 'unreadable text carries no created: field'
    assert date_disagreements(tmp_path, found) == {}
