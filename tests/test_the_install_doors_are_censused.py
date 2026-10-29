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

from dev_lab.dev._doorcensus_rows import DOOR_FLOOR, DOORS, REPO_FLOOR
from dev_lab.dev.doorcensus import (
    DoorDriftError,
    assert_census,
    reachable,
    read,
)

#: This repo's checkout, and the directory it sits in -- the census API joins the two.
_ROOT: Final = Path(__file__).resolve().parents[1]
_BASE: Final = _ROOT.parent

#: The repo this suite is verifying, read from its WORKING TREE.
_HERE: Final = 'dev-lab'

_PATHS: Final[dict[str, str]] = {_HERE: _ROOT.name}


def _roots() -> dict[str, Path]:
    return reachable(_BASE, _PATHS)


def test_every_declared_door_still_measures_what_the_table_records() -> None:
    """THE CENSUS. Equality per file, in both directions, over every repo reachable from this box."""
    seen = assert_census(_BASE, _PATHS, DOORS, repo_floor=REPO_FLOOR, door_floor=DOOR_FLOOR, here=_HERE)
    assert _HERE in seen, 'the census did not even read the tree it runs in'


def test_a_reverting_door_planted_into_a_live_repo_is_refused() -> None:
    """THE PLANTED CONTROL FOR THE LIVE HALF: a green census over real trees proves nothing alone.

    The plant is the edit somebody would actually make -- a `uv run` without `--no-sync` added to this
    repo's real Makefile -- classified against a real caller's floating names. At home it reads INERT;
    against a floating `lab-commons` the planted implicit sync is convicted UNLOCKED. Nothing is installed.
    """
    text = (_ROOT / 'Makefile').read_text(encoding='utf-8')
    assert read(text, ()).deliveries == {'INERT'}
    assert 'UNLOCKED' not in read(text, ('lab-commons',)).deliveries
    planted = text + '\nrun:\n\tuv run python -m dev_lab.dev.verify\n'
    assert 'UNLOCKED' in read(planted, ('lab-commons',)).deliveries


def test_the_census_refuses_a_drift_planted_into_the_real_table() -> None:
    """The other side of the live half: the real rows, one digit wrong, through the real guard."""
    broken = tuple(
        row if index else type(row)(row.repo, row.path, row.commands + 1, row.deliveries, row.why)
        for index, row in enumerate(DOORS)
    )
    with pytest.raises(DoorDriftError, match='records'):
        assert_census(_BASE, _PATHS, broken, repo_floor=REPO_FLOOR, door_floor=DOOR_FLOOR, here=_HERE)
