"""COMMONS-BELOW-FLOOR: a missing lab_commons module names the heal; any other import failure passes through."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from dev_lab.dev.commonsfloor import RULE, CommonsBelowFloor, importing

ROOT = Path(__file__).resolve().parents[1]


def _missing(name: str) -> None:
    said = f"No module named '{name}'"
    raise ModuleNotFoundError(said, name=name)


def _import_under_guard(root: Path, name: str) -> None:
    with importing(root):
        _missing(name)


def test_a_missing_lab_commons_module_names_the_heal(tmp_path: Path) -> None:
    with pytest.raises(CommonsBelowFloor) as refused:
        _import_under_guard(tmp_path, 'lab_commons.storage')
    message = str(refused.value)
    assert RULE in message
    assert 'lab_commons.storage' in message
    assert f'--lock-upgrade {tmp_path} --upgrade-package lab-commons' in message


def test_any_other_missing_module_is_not_reworded(tmp_path: Path) -> None:
    """Planted control: the wall speaks only for lab-commons; an unrelated missing module keeps its own error."""
    with pytest.raises(ModuleNotFoundError) as raised:
        _import_under_guard(tmp_path, 'numpy')
    assert not isinstance(raised.value, CommonsBelowFloor)


def test_the_floor_carries_lab_commons_storage() -> None:
    """dev-lab imports lab_commons.storage at load, so its floor is at least the first lab-commons carrying it."""
    manifest = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    (requirement,) = (dep for dep in manifest['project']['dependencies'] if dep.startswith('lab-commons'))
    floor = re.search(r'>=0\.3\.1\.dev(\d+)', requirement)
    assert floor is not None, requirement
    assert int(floor.group(1)) >= 1579, requirement
