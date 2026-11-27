"""SHARE-FOLDER-HOLDS-DATA: a synced share folder keeps data and the command that regenerates each figure."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev.famtests.sharefolder import (
    MANIFEST,
    assert_every_share_folder_holds_data,
    share_folder_problems,
)

if TYPE_CHECKING:
    from pathlib import Path


def _folder(tmp_path: Path, manifest: str | None) -> Path:
    folder = tmp_path / 'share'
    folder.mkdir()
    (folder / 'torque.csv').write_text('t,T\n0,1\n', encoding='utf-8')
    if manifest is not None:
        (folder / MANIFEST).write_text(manifest, encoding='utf-8')
    return folder


_GOOD = '[figures]\n"torque.png" = "uv run <cli> render cases/x --plot"\n'


def test_data_with_its_commands_passes(tmp_path: Path) -> None:
    folder = _folder(tmp_path, _GOOD)
    assert share_folder_problems(folder) == []
    assert_every_share_folder_holds_data([folder])


def test_a_rendered_image_is_refused_planted_control(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same folder holding the rendered figure is refused, naming the file."""
    folder = _folder(tmp_path, _GOOD)
    (folder / 'plots').mkdir()
    (folder / 'plots' / 'torque.PNG').write_bytes(b'\x89PNG')
    found = share_folder_problems(folder)
    assert len(found) == 1
    assert 'plots/torque.PNG' in found[0]
    with pytest.raises(AssertionError, match=r'plots/torque\.PNG'):
        assert_every_share_folder_holds_data([folder])


def test_a_declared_input_image_stays(tmp_path: Path) -> None:
    """A source image nothing can regenerate (a teardown photo) is INPUT, declared by name."""
    folder = _folder(tmp_path, None)
    (folder / MANIFEST).write_text('inputs = ["teardown.jpg"]\n' + _GOOD, encoding='utf-8')
    (folder / 'teardown.jpg').write_bytes(b'jpg')
    assert share_folder_problems(folder) == []


def test_a_missing_manifest_or_an_empty_command_is_refused(tmp_path: Path) -> None:
    assert any(MANIFEST in one for one in share_folder_problems(_folder(tmp_path, None)))
    other = tmp_path / 'b'
    other.mkdir()
    (other / MANIFEST).write_text('[figures]\n"a.png" = ""\n', encoding='utf-8')
    assert any("'a.png'" in one for one in share_folder_problems(other))


def test_no_declared_folder_is_refused_not_vacuous() -> None:
    """An empty declaration would read green on nothing (FLOOR-ON-EVERY-SCAN)."""
    with pytest.raises(AssertionError, match='no share folder'):
        assert_every_share_folder_holds_data([])
