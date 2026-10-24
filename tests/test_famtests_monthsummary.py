"""MONTHLY-PLANS-CARRIED: the planted control both ways, and this repo's own memory tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests import monthsummary
from dev_lab.dev.famtests.monthsummary import assert_every_month_carries_its_plans, assert_the_reader_still_convicts

_MEMORY = Path(__file__).resolve().parents[1] / '.claude' / 'memory'

#: The month this repo adopted the rule: its first summary is October 2026's.
_SINCE = '2026/10'


def test_the_planted_control_convicts_exactly_the_planted_offenders(tmp_path: Path) -> None:
    assert_the_reader_still_convicts(tmp_path)


def test_the_planted_control_reds_when_the_carry_goes_blind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monthsummary, 'CLOSED', frozenset(monthsummary.STATUSES))
    with pytest.raises(AssertionError, match='must read 6'):
        assert_the_reader_still_convicts(tmp_path)


def test_every_month_of_this_repo_carries_its_plans() -> None:
    assert_every_month_carries_its_plans(_MEMORY, since=_SINCE)
