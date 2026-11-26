"""dev-lab#46: a checkout volume under the [storage] floor is said at session start, with its door."""

from __future__ import annotations

from pathlib import Path

from lab_commons.headroom import Floor

from dev_lab.dev import volumefloor

_GB = 1024**3


def test_a_planted_low_volume_alarms_naming_the_floor_and_the_door(tmp_path: Path) -> None:
    said = volumefloor.notice(tmp_path, floor=Floor(50 * _GB), reads=lambda _v, _f: (int(0.1 * _GB), None))
    assert said is not None
    assert '0.1 GB free under the 50 GB floor' in said
    assert 'dev_lab.dev.reclaimrun' in said


def test_a_volume_over_the_floor_is_silent(tmp_path: Path) -> None:  # PLANTED CONTROL
    assert volumefloor.notice(tmp_path, floor=Floor(50 * _GB), reads=lambda _v, _f: (60 * _GB, None)) is None


def test_a_file_limited_quota_under_its_files_floor_alarms(tmp_path: Path) -> None:
    said = volumefloor.notice(tmp_path, floor=Floor(_GB, files=100), reads=lambda _v, _f: (2 * _GB, (100, 7)))
    assert said is not None
    assert '7 files left under the 100 files floor' in said


def test_the_real_volume_is_measured(tmp_path: Path) -> None:
    """The shipped reader: a floor above any disk alarms, a zero floor never does."""
    assert volumefloor.notice(tmp_path, floor=Floor(1 << 62)) is not None
    assert volumefloor.notice(tmp_path, floor=Floor(0)) is None
