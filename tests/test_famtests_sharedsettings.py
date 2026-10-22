"""Adoption of the shared-settings guard HERE, plus the arms that judge the guard itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.config import SHARED_KEYS, User
from dev_lab.dev.famtests.sharedsettings import (
    DEFAULT_LITERALS,
    assert_a_planted_redefinition_is_convicted,
    assert_no_package_redefines_a_shared_setting,
)
from dev_lab.dev.floors import FloorUnmet

#: This repo's kit source.
SOURCE = Path(__file__).resolve().parent.parent / 'src'

#: MEASURED 2026-10-13 at 274 files under ``src``; a floor on FILES READ, not a pin.
FILE_FLOOR = 240


def test_the_owner_is_the_only_module_declaring_a_shared_setting() -> None:
    assert_no_package_redefines_a_shared_setting(SOURCE, floor=FILE_FLOOR, sanctioned={'lab_commons/config.py'})


def test_a_planted_redefinition_is_convicted() -> None:
    assert_a_planted_redefinition_is_convicted()


def test_a_consumer_schema_is_refused_with_the_remedy(tmp_path: Path) -> None:
    (tmp_path / 'schema.py').write_text(
        "class Utils:\n    text_editor_command: str = 'notepad.exe'\n", encoding='utf-8'
    )
    (tmp_path / 'defaults.toml').write_text('[utils]\nlog_date_format = "%d"\n', encoding='utf-8')
    with pytest.raises(AssertionError) as caught:
        assert_no_package_redefines_a_shared_setting(tmp_path, floor=2)
    message = str(caught.value)
    assert 'schema.py:2' in message
    assert "[utils] carries the shared key 'log_date_format'" in message
    assert 'lab_commons.config.user()' in message


def test_an_empty_walk_is_refused_by_the_floor(tmp_path: Path) -> None:
    with pytest.raises(FloorUnmet):
        assert_no_package_redefines_a_shared_setting(tmp_path, floor=1)


def test_every_distinctive_default_is_matched() -> None:
    assert set(DEFAULT_LITERALS.values()) == SHARED_KEYS - {'log_level'}
    assert DEFAULT_LITERALS[User().text_editor_command] == 'text_editor_command'
