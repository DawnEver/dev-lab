"""THE LIVE HALF: the kit's declared doors re-measured against the kit's own working tree.

This is a MEASUREMENT, not a proof that the guard works -- that is `test_dev_doorcensus.py`, where
every refusal is planted into a real repository and driven through the real function. What this file
buys is that a recorded number cannot age quietly into prose.

IT READS NO SIBLING. Each consumer declares its own doors in its own tests and calls the same
`assert_census` over its own checkout; a census of other repos run from here would be facts about
them stored in this tree, judged against names that are not theirs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev._doorcensus_rows import DOOR_FLOOR, DOORS, REPO_FLOOR, SHARED
from lab_commons.dev.doorcensus import (
    DoorDriftError,
    assert_census,
    assert_no_tracked_lock,
    door_text,
    reachable,
    read,
)
from lab_commons.dev.worktreeplace import family_root

#: This repo's checkout, and the directory it sits in -- the census API joins the two.
_ROOT: Final = Path(__file__).resolve().parents[1]
_BASE: Final = family_root(_ROOT)

#: The repo this suite is verifying, read from its WORKING TREE.
_HERE: Final = 'lab-commons'

_PATHS: Final[dict[str, str]] = {_HERE: _ROOT.name}


def _roots() -> dict[str, Path]:
    return reachable(_BASE, _PATHS)


def test_every_declared_door_still_measures_what_the_table_records() -> None:
    """THE CENSUS. Equality per file, in both directions, over every repo reachable from this box."""
    seen = assert_census(_BASE, _PATHS, DOORS, repo_floor=REPO_FLOOR, door_floor=DOOR_FLOOR, here=_HERE)
    assert 'lab-commons' in seen, 'the census did not even read the tree it runs in'


def test_this_repo_does_not_track_the_lock() -> None:
    """The condition every surviving lock-consuming door rests on, asserted rather than assumed."""
    assert_no_tracked_lock(_roots())


def test_the_shared_ci_door_is_judged_against_what_its_callers_float() -> None:
    """THE FINDING, kept live: at home it reads INERT, and at home is not where it runs.

    Both classifications of the one file are asserted, because the row's whole content is that they
    DIFFER. If the home reading ever stops being vacuous -- the day lab-commons declares a floating
    requirement of its own -- this reds, and that is the day the ordinary row acquires teeth.
    """
    for shared in SHARED:
        assert shared.repo == _HERE, f'{shared.repo} is not this repo, and only this repo`s doors are read here'
        text = door_text(_ROOT, shared.path, at_head=False)
        assert text is not None, f'{shared.path} is declared shared and is not in this tree'
        assert read(text, ()).deliveries <= {'INERT'}, 'the home reading is no longer vacuous'
        assert read(text, shared.caller_floats).deliveries == shared.deliveries, (
            f'{shared.path} run by a caller floating {shared.caller_floats} no longer delivers '
            f'{sorted(shared.deliveries)}'
        )


def test_a_reverting_door_planted_into_a_live_repo_is_refused() -> None:
    """THE PLANTED CONTROL FOR THE LIVE HALF: a green census over real trees proves nothing alone.

    The plant is the edit somebody would actually make -- the `--no-sync` dropped off the shared CI
    workflow's `uv run` -- applied to a copy of THIS repo's real file and classified against a real
    caller's real floating names. No environment is touched and nothing is installed; this is a
    statement about command text, which is the only kind this layer ever makes.
    """
    home = _ROOT / '.github' / 'workflows' / 'python-verify.yml'
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
