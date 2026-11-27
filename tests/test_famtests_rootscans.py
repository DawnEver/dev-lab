"""NEVER-LOG-SECRETS and TOLERANCE-CARRIES-A-UNIT as one-test adoptions over a checkout's tracked corpus (FAM-12).

Each body is driven over a planted git repo: an empty one passes (the adopter with no test code yet), a planted
violation is refused by name (the control saying no), and the honest twin is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_fake import git_out

from dev_lab.dev.famtests.approxfloors import FloorlessTolerance, assert_every_tracked_tolerance_states_its_floor
from dev_lab.dev.famtests.secretlog import LoggedSecret, assert_no_secret_is_logged

ROOT = Path(__file__).resolve().parents[1]


def _repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git_out(root, 'init', '-q')
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
        git_out(root, 'add', name)
    return root


def test_an_empty_repo_adopts_both(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'repo', {})
    assert_no_secret_is_logged(root=root)
    assert_every_tracked_tolerance_states_its_floor(root=root, bar='unconditional', plant_root=tmp_path)


def test_a_planted_logged_secret_is_refused_and_its_hash_is_not(tmp_path: Path) -> None:
    """PLANTED CONTROL: the tracked offender is named; an untracked one is outside the corpus."""
    root = _repo(tmp_path, {'src/a.py': "emit(f'{sha256(token)}')\n", 'src/b.py': "print(f'key {api_key}')\n"})
    with pytest.raises(LoggedSecret, match=r'src/b\.py:1 `api_key`'):
        assert_no_secret_is_logged(root=root)
    git_out(root, 'rm', '-q', '--cached', 'src/b.py')
    assert_no_secret_is_logged(root=root)


def test_a_planted_floorless_tolerance_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a ratio with no floor is named; the floored twin passes."""
    plant = tmp_path / 'plant'
    plant.mkdir()
    root = _repo(tmp_path / 'repo', {'tests/test_x.py': 'import pytest\nok = 1 == pytest.approx(1, rel=1e-9)\n'})
    with pytest.raises(FloorlessTolerance, match=r'tests/test_x\.py:2'):
        assert_every_tracked_tolerance_states_its_floor(root=root, bar='ratio', plant_root=plant)
    (root / 'tests/test_x.py').write_text(
        'import pytest\nok = 1 == pytest.approx(1, rel=1e-9, abs=0.0)\n', encoding='utf-8'
    )
    assert_every_tracked_tolerance_states_its_floor(root=root, bar='ratio', plant_root=plant)


def test_dev_lab_logs_no_secret() -> None:
    """Dev-lab adopts its own body: the one-line test a consumer copies."""
    assert_no_secret_is_logged(root=ROOT)
