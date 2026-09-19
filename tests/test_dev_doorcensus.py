"""The install-door CENSUS machinery, driven by PLANTED repos -- including the two drifts it caught.

WHY PLANTED AND NOT READ OFF THE FAMILY. The live census one file over is a MEASUREMENT: it passes
today because the four checkouts agree with the table today, and a passing measurement cannot say
whether the guard would refuse a disagreement or merely never met one. Every refusal this module can
produce is therefore planted into a real git repository here and pushed through the REAL function --
including the two real drifts, reproduced at the numbers they actually held.

THE TWO DRIFTS, both green for two days under a floor that could not see them: `lab-commons`
recorded 9 installer commands and delivered 16; `wdg-lab` recorded 28 and delivered 30. One drifted
UP by seven and the other by two, and a `declared <= live` floor is satisfied by both. Both
directions are planted below, because a ratchet with one side is half a ratchet: a count that falls
is a door that stopped being read, and that is the more dangerous of the two.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from lab_commons.dev._doorcensus_rows import DECLINED, DOOR_FLOOR, DOORS, REPO_FLOOR, SHARED
from lab_commons.dev.doorcensus import (
    CensusRowError,
    Declined,
    DoorDriftError,
    DoorRow,
    Reading,
    SharedDoor,
    TrackedLockError,
    UnreadableRepo,
    VacuousCensusError,
    assert_census,
    assert_no_tracked_lock,
    committed,
    drift,
    floating_at_head,
    reachable,
    read,
    rows_for,
)

#: A reason long enough to clear `WHY_FLOOR`, for rows whose SUBJECT is something other than prose.
_WHY = (
    'A planted row whose reason exists only to clear the floor, because the floor is checked at '
    'construction and every row in this file would otherwise have to argue a case it is not about. '
    'The rows that carry real reasons are in the data module, and they are read by the live census.'
)

#: The kit, as the one floating requirement a planted consumer declares.
_KIT: tuple[str, ...] = ('lab-commons',)

_GIT = shutil.which('git') or 'git'

_MANIFEST = '[project]\nname = "x"\ndependencies = ["lab-commons @ git+https://example.invalid/lab-commons.git"]\n'


def _repo(root: Path, files: dict[str, str]) -> Path:
    """A real git repository holding *files*, COMMITTED -- the census reads HEAD, never the worktree."""
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True)
    _commit(root, 'planted')
    return root


def _commit(root: Path, message: str) -> None:
    """Stage and commit everything in *root*, identity supplied so a bare box can still plant a repo."""
    subprocess.run([_GIT, 'add', '.'], cwd=root, check=True)
    subprocess.run(
        [_GIT, '-c', 'user.email=a@b.c', '-c', 'user.name=t', 'commit', '-qm', message], cwd=root, check=True
    )


def _row(**kwargs: object) -> DoorRow:
    return DoorRow(why=_WHY, **kwargs)  # type: ignore[arg-type]


def test_a_reading_carries_both_halves_because_either_alone_is_blind() -> None:
    """A count cannot say WHICH command changed; a named set cannot say two became one."""
    text = 'uv pip install -e .\nuv sync\npython -m pytest\n'
    assert read(text, _KIT) == Reading(3, frozenset({'RESOLVES', 'REVERTS', 'INERT'}))
    assert read(text, ()) == Reading(3, frozenset({'INERT'}))


def test_a_file_with_no_installer_command_reads_zero_and_no_delivery() -> None:
    """ZERO IS A MEASUREMENT. Three declared doors in this family legitimately hold none."""
    assert read('echo hello\nmake verify\n', _KIT) == Reading(0, frozenset())


def test_a_row_may_not_pair_a_count_with_a_contradicting_delivery_set() -> None:
    """A row that says nought commands delivered something was typed rather than measured."""
    with pytest.raises(CensusRowError, match='cannot disagree'):
        _row(repo='r', path='Makefile', commands=0, deliveries=frozenset({'INERT'}))
    with pytest.raises(CensusRowError, match='cannot disagree'):
        _row(repo='r', path='Makefile', commands=3, deliveries=frozenset())


def test_a_row_may_not_name_a_delivery_the_enum_does_not_have() -> None:
    """The vocabulary is the enum's, so a value that stops existing cannot live on as a string."""
    with pytest.raises(CensusRowError, match='name no Delivery member'):
        _row(repo='r', path='Makefile', commands=1, deliveries=frozenset({'SAFE'}))


#: One caption-reasoned row of each kind. Every kind is here because the floor is enforced by a
#: helper they share, and a shared helper is exactly what silently stops being called from one of
#: three call sites.
_CAPTIONED: tuple[Callable[[], object], ...] = (
    lambda: DoorRow(repo='r', path='Makefile', commands=1, deliveries=frozenset({'INERT'}), why='it is fine'),
    lambda: Declined(repo='r', path='dep.py', covered_by='some test', why='it is fine'),
    lambda: SharedDoor(repo='r', path='ci.yml', ran_by=('s',), deliveries=frozenset({'INERT'}), why='it is fine'),
)


@pytest.mark.parametrize('build', _CAPTIONED)
def test_no_row_kind_accepts_a_caption_for_a_reason(build: Callable[[], object]) -> None:
    """A caption is how a door gets dropped while still looking considered -- refused AT CONSTRUCTION."""
    with pytest.raises(CensusRowError, match='under the'):
        build()


def test_a_declined_door_must_name_the_mechanism_that_covers_it_instead() -> None:
    """A door covered by nothing is not declined, it is dropped -- and the two look identical in a list."""
    with pytest.raises(CensusRowError, match='covered by nothing'):
        Declined(repo='r', path='dep.py', covered_by='', why=_WHY)


def test_a_shared_door_shared_with_nobody_is_an_ordinary_row() -> None:
    """The kind exists for the caller's names; with no caller there is no second classification."""
    with pytest.raises(CensusRowError, match='shared with nobody'):
        SharedDoor(repo='r', path='ci.yml', ran_by=(), deliveries=frozenset({'INERT'}), why=_WHY)


def test_the_census_reads_head_and_not_the_working_tree(tmp_path: Path) -> None:
    """A sibling lane's uncommitted edit must not be able to turn this repo red -- it did once."""
    root = _repo(tmp_path / 'r', {'pyproject.toml': _MANIFEST, 'Makefile': 'go:\n\tuv pip install -e .\n'})
    (root / 'Makefile').write_text('go:\n\tuv sync\n', encoding='utf-8')
    rows = (_row(repo='r', path='Makefile', commands=1, deliveries=frozenset({'RESOLVES'})),)
    assert drift(root, rows, _KIT) == ()
    assert 'uv pip install' in (committed(root, 'Makefile') or '')


def test_the_repo_under_verification_is_read_from_its_working_tree_instead(tmp_path: Path) -> None:
    """THE OTHER SIDE OF THAT SPLIT, and the first cut of this module got it wrong.

    Read at `HEAD`, a door repair in the diff under review is invisible until after it is committed,
    so the guard would be demanding that the fix and the row it justifies land together in one
    unchecked commit. The SAME planted repo, the SAME row, the two `at_head` answers -- one passes
    and one refuses, which is what makes the flag a decision rather than a default nobody set.
    """
    root = _repo(tmp_path / 'r', {'pyproject.toml': _MANIFEST, 'Makefile': 'go:\n\tuv sync\n'})
    (root / 'Makefile').write_text('go:\n\tuv sync -P lab-commons\n', encoding='utf-8')
    fixed = (_row(repo='r', path='Makefile', commands=1, deliveries=frozenset({'RESOLVES'})),)
    assert drift(root, fixed, _KIT, at_head=False) == ()
    assert len(drift(root, fixed, _KIT, at_head=True)) == 1


def test_a_count_that_drifted_UP_is_caught_at_the_real_numbers(tmp_path: Path) -> None:
    """THE PLANTED CONTROL for drift one: recorded 9, delivers 16, and a floor of 5 passes both."""
    lines = ''.join(f'\tpython -m step{n}\n' for n in range(16))
    root = _repo(tmp_path / 'r', {'pyproject.toml': _MANIFEST, 'Makefile': f'go:\n{lines}'})
    stale = (_row(repo='r', path='Makefile', commands=9, deliveries=frozenset({'INERT'})),)
    found = drift(root, stale, _KIT)
    assert len(found) == 1
    assert '9 commands' in found[0]
    assert '16 commands' in found[0]


def test_a_count_that_drifted_DOWN_is_caught_too(tmp_path: Path) -> None:
    """The other side of the ratchet, and the more dangerous one: a door that stopped being read."""
    root = _repo(tmp_path / 'r', {'pyproject.toml': _MANIFEST, 'Makefile': 'go:\n\tpython -m step\n'})
    stale = (_row(repo='r', path='Makefile', commands=30, deliveries=frozenset({'INERT'})),)
    assert len(drift(root, stale, _KIT)) == 1


def test_a_delivery_set_that_gained_REVERTS_is_caught_at_an_unchanged_count(tmp_path: Path) -> None:
    """The defect this whole layer exists for, and a count alone is blind to it -- one in, one out."""
    root = _repo(tmp_path / 'r', {'pyproject.toml': _MANIFEST, 'Makefile': 'go:\n\tuv sync\n'})
    stale = (_row(repo='r', path='Makefile', commands=1, deliveries=frozenset({'RESOLVES'})),)
    found = drift(root, stale, _KIT)
    assert len(found) == 1
    assert 'REVERTS' in found[0]


def test_a_declared_door_that_is_no_longer_committed_reds_rather_than_reading_empty(tmp_path: Path) -> None:
    """A renamed door must not classify as a file holding no command -- the vacuous green, per file."""
    root = _repo(tmp_path / 'r', {'pyproject.toml': _MANIFEST, 'Makefile': 'go:\n\tuv pip install -e .\n'})
    rows = (_row(repo='r', path='Makefile.old', commands=1, deliveries=frozenset({'RESOLVES'})),)
    found = drift(root, rows, _KIT)
    assert len(found) == 1
    assert 'not committed' in found[0]


def test_a_checkout_with_no_committed_manifest_is_inconclusive_rather_than_requirement_free(tmp_path: Path) -> None:
    """Answering "no floating requirement" makes every door INERT, which is the clean-looking lie."""
    root = _repo(tmp_path / 'r', {'Makefile': 'go:\n\tuv sync\n'})
    with pytest.raises(UnreadableRepo, match='cannot be read'):
        floating_at_head(root)


def test_a_repo_that_tracks_the_lock_is_refused_by_name(tmp_path: Path) -> None:
    """THE CONDITION EVERY SURVIVING LOCK-CONSUMING DOOR RESTS ON, planted in both directions."""
    clean = _repo(tmp_path / 'clean', {'pyproject.toml': _MANIFEST})
    assert_no_tracked_lock({'clean': clean})
    dirty = _repo(tmp_path / 'dirty', {'pyproject.toml': _MANIFEST, 'uv.lock': 'version = 1\n'})
    with pytest.raises(TrackedLockError, match='dirty'):
        assert_no_tracked_lock({'clean': clean, 'dirty': dirty})


def test_a_census_that_reached_almost_nothing_refuses_to_report_a_clean_family(tmp_path: Path) -> None:
    """Both floors, both sides: too few repos and too few rows each read as a green today."""
    _repo(tmp_path / 'one', {'pyproject.toml': _MANIFEST, 'Makefile': 'go:\n\tuv pip install -e .\n'})
    rows = (_row(repo='one', path='Makefile', commands=1, deliveries=frozenset({'RESOLVES'})),)
    with pytest.raises(VacuousCensusError, match='under the floors'):
        assert_census(tmp_path, {'one': 'one'}, rows, repo_floor=2, door_floor=1)
    with pytest.raises(VacuousCensusError, match='under the floors'):
        assert_census(tmp_path, {'one': 'one'}, rows, repo_floor=1, door_floor=5)


def test_an_absent_sibling_is_absent_rather_than_failing(tmp_path: Path) -> None:
    """Repos are cloned per box; demanding all four would make the census unrunnable on most of them."""
    _repo(tmp_path / 'here', {'pyproject.toml': _MANIFEST})
    assert set(reachable(tmp_path, {'here': 'here', 'elsewhere': 'elsewhere'})) == {'here'}


def test_the_guard_passes_and_refuses_over_the_same_planted_family(tmp_path: Path) -> None:
    """THE TWO SIDES, through `assert_census` itself rather than through `drift` underneath it."""
    _repo(tmp_path / 'a', {'pyproject.toml': _MANIFEST, 'Makefile': 'go:\n\tuv pip install -e .\n'})
    _repo(tmp_path / 'b', {'pyproject.toml': _MANIFEST, 'hook.sh': 'uv run --no-sync python -m x\n'})
    paths = {'a': 'a', 'b': 'b'}
    rows = (
        _row(repo='a', path='Makefile', commands=1, deliveries=frozenset({'RESOLVES'})),
        _row(repo='b', path='hook.sh', commands=1, deliveries=frozenset({'INERT'})),
    )
    assert set(assert_census(tmp_path, paths, rows, repo_floor=2, door_floor=2)) == {'a', 'b'}
    (tmp_path / 'b' / 'hook.sh').write_text('uv run python -m x\n', encoding='utf-8')
    _commit(tmp_path / 'b', 'drop the flag')
    with pytest.raises(DoorDriftError, match='REVERTS'):
        assert_census(tmp_path, paths, rows, repo_floor=2, door_floor=2)


def test_rows_for_partitions_by_repo_and_the_table_covers_more_than_one() -> None:
    """The axis is the repo because the repo is what a lane owns -- and a one-repo table is a note."""
    repos = {row.repo for row in DOORS}
    assert len(repos) >= REPO_FLOOR, repos
    assert len(DOORS) >= DOOR_FLOOR, len(DOORS)
    assert sum(len(rows_for(repo, DOORS)) for repo in repos) == len(DOORS)


def test_the_table_declares_no_path_twice_and_no_row_is_also_declined() -> None:
    """A key in two hands is two answers to one question, and the census would report whichever it met."""
    keys = [row.key for row in DOORS]
    assert sorted(keys) == sorted(set(keys)), 'a door is declared twice'
    overlap = {row.key for row in DOORS} & {row.key for row in DECLINED}
    assert overlap == set(), f'{sorted(overlap)} are both censused and declined'


def test_every_shared_door_is_also_declared_as_an_ordinary_row_in_its_home_repo() -> None:
    """The two readings are of ONE file, so the shared row must not be able to outlive the file itself."""
    assert SHARED, 'the shared table is empty, so the finding it was added for has no row'
    home = {(row.repo, row.path) for row in DOORS}
    for shared in SHARED:
        assert (shared.repo, shared.path) in home, f'{shared.path} is shared but not censused at home'
        assert shared.repo not in shared.ran_by, 'a repo does not run its own file as somebody else'
