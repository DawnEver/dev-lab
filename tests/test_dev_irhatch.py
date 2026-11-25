"""The IR build hook: a hatchling wheel build of the fixture repo carries the generated (git-ignored) IR modules."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest
from hatchling.builders.wheel import WheelBuilder

FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))
    (root / 'src' / 'sample_pkg').mkdir(parents=True)
    (root / 'src' / 'sample_pkg' / '__init__.py').write_text('', encoding='utf-8')
    return root


def test_a_wheel_build_generates_and_ships_the_ir(repo: Path, tmp_path: Path) -> None:
    wheel = next(iter(WheelBuilder(str(repo)).build(directory=str(tmp_path / 'dist'), versions=['standard'])))
    names = set(zipfile.ZipFile(wheel).namelist())
    for module in ('_ir_runtime', '_ir_codec', '_ir_ids', '_ir_widgets', '_ir_samples'):
        assert f'sample_pkg/{module}.py' in names
    assert (repo / 'src' / 'sample_pkg' / '_ir_widgets.py').is_file()


def test_a_build_without_the_hook_ships_no_ir(repo: Path, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same repo without the hook declaration ships nothing generated."""
    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(pyproject.read_text(encoding='utf-8').replace('[tool.hatch.build.hooks.ir-schema]\n', ''))
    wheel = next(iter(WheelBuilder(str(repo)).build(directory=str(tmp_path / 'dist'), versions=['standard'])))
    assert not any('_ir_' in name for name in zipfile.ZipFile(wheel).namelist())
