"""THE LIVE HALF: the declared census re-measured against the checkouts standing beside this one.

This is a MEASUREMENT of the family, not a proof that the guard works -- that is
`test_dev_doorcensus.py`, where every refusal is planted into a real repository and driven through
the real function. What this file buys is that a recorded number cannot age quietly into prose: on
the day it was written, two of them already had.

IT IS ALSO THE HALF THAT NEEDS AN HONEST ABSENCE. The family's repos are cloned per box and no box
is required to hold all four, so an unreachable sibling is ABSENT rather than failing -- and what
stops that being a free pass is the repo floor, which refuses a run that reached lab-commons alone.
A census of one tree is not a census.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev._doorcensus_rows import DECLINED, DOOR_FLOOR, DOORS, REPO_FLOOR, SHARED
from lab_commons.dev.doorcensus import (
    DoorDriftError,
    assert_census,
    assert_no_tracked_lock,
    committed,
    door_text,
    floating_at_head,
    reachable,
    read,
)

#: This file is `<lab-commons>/tests/`, so the family sits one level above the repo root.
_BASE: Final = Path(__file__).resolve().parents[2]

#: The repo this suite is verifying, whose WORKING TREE is the authority for its own rows. Every
#: sibling is read at `HEAD` instead. Without the split a door repair here is unverifiable until
#: after it is committed, which asks for the row and the fix in one unchecked commit.
_HERE: Final = 'lab-commons'

#: Where each repo is checked out relative to `_BASE`. The motronics entry names a WORKTREE and that
#: is the point: the main checkout is the integrator's and is never read here, so a census run
#: against it would be measuring a tree this lane was told not to touch.
_PATHS: Final[dict[str, str]] = {
    'lab-commons': 'lab-commons',
    'wdg-lab': 'wdg-lab',
    'optimi-lab': 'optimi-lab',
    'motronics-studio': 'motronics-studio/.claude/worktrees/feat/optimi-lab',
}


def _roots() -> dict[str, Path]:
    return reachable(_BASE, _PATHS)


def test_every_declared_door_still_measures_what_the_table_records() -> None:
    """THE CENSUS. Equality per file, in both directions, over every repo reachable from this box."""
    seen = assert_census(_BASE, _PATHS, DOORS, repo_floor=REPO_FLOOR, door_floor=DOOR_FLOOR, here=_HERE)
    assert 'lab-commons' in seen, 'the census did not even read the tree it runs in'


def test_no_repo_in_the_family_tracks_the_lock() -> None:
    """The condition every surviving lock-consuming door rests on, asserted rather than assumed."""
    assert_no_tracked_lock(_roots())


def test_the_shared_ci_door_is_judged_against_the_names_of_the_repos_that_run_it() -> None:
    """THE FINDING, kept live: at home it reads INERT, and at home is not where it runs.

    Both classifications of the one file are asserted, because the row's whole content is that they
    DIFFER. If the home reading ever stops being vacuous -- the day lab-commons declares a floating
    requirement of its own -- this reds, and that is the day the ordinary row acquires teeth.
    """
    roots = _roots()
    for shared in SHARED:
        home = roots.get(shared.repo)
        if home is None:
            pytest.fail(f'{shared.repo} holds a shared door and is not reachable, so this claim is unchecked')
        text = door_text(home, shared.path, at_head=shared.repo != _HERE)
        assert text is not None, f'{shared.path} is declared shared and is not committed in {shared.repo}'
        assert read(text, ()).deliveries <= {'INERT'}, 'the home reading is no longer vacuous'
        for caller in shared.ran_by:
            root = roots.get(caller)
            if root is None:
                continue
            names = floating_at_head(root)
            assert names, f'{caller} declares nothing floating, so running this door there is inert'
            assert read(text, names).deliveries == shared.deliveries, (
                f'{shared.path} run inside {caller} no longer delivers {sorted(shared.deliveries)}'
            )


def test_every_declined_door_is_still_a_file_in_the_repo_that_declined_it() -> None:
    """A decline whose subject no longer exists is a reason nobody will delete, protecting nothing."""
    roots = _roots()
    checked = 0
    for row in DECLINED:
        root = roots.get(row.repo)
        if root is None:
            continue
        assert committed(root, row.path) is not None, (
            f'{row.key} is recorded as a declined door and is not committed there. Either it moved -- '
            f'repoint the row -- or the door is gone and the decline outlived its subject.'
        )
        checked += 1
    assert checked, 'no declined row was checkable on this box, so this test proved nothing'


def test_a_reverting_door_planted_into_a_live_repo_is_refused() -> None:
    """THE PLANTED CONTROL FOR THE LIVE HALF: a green census over real trees proves nothing alone.

    The plant is the edit somebody would actually make -- the `--no-sync` dropped off the shared CI
    workflow's `uv run` -- applied to a copy of THIS repo's real file and classified against a real
    caller's real floating names. No environment is touched and nothing is installed; this is a
    statement about command text, which is the only kind this layer ever makes.
    """
    home = Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'python-verify.yml'
    text = home.read_text(encoding='utf-8')
    assert 'uv run --no-sync make verify' in text, 'the remedy this control plants the removal of is gone'
    assert read(text.replace('uv run --no-sync', 'uv run'), ('lab-commons',)).deliveries == {'REVERTS'}


def test_the_census_refuses_a_drift_planted_into_the_real_table() -> None:
    """The other side of the live half: the real rows, one digit wrong, through the real guard."""
    broken = tuple(
        row if index else type(row)(row.repo, row.path, row.commands + 1, row.deliveries, row.why)
        for index, row in enumerate(DOORS)
    )
    with pytest.raises(DoorDriftError, match='records'):
        assert_census(_BASE, _PATHS, broken, repo_floor=REPO_FLOOR, door_floor=DOOR_FLOOR, here=_HERE)
