"""Every tool cache lives under ``output/cache/<tool>/`` (user ruling 2026-11-24), so `.gitignore` names none."""

from __future__ import annotations

import tomllib
from pathlib import Path

from dev_lab.dev.verifysteps import CACHE_VARS, cache_env

ROOT = Path(__file__).resolve().parents[1]


def test_the_door_points_every_unconfigurable_cache_under_output(tmp_path: Path) -> None:
    """PLANTED CONTROL is the root itself: a variable left at the repo root would not sit under output/cache/."""
    env = cache_env(tmp_path)
    assert set(env) == set(CACHE_VARS) == {'HYPOTHESIS_STORAGE_DIRECTORY', 'MYPY_CACHE_DIR'}
    assert all(Path(value).parent == tmp_path / 'output' / 'cache' for value in env.values())


def test_the_kit_sends_its_configurable_caches_under_output() -> None:
    """pytest, ruff and the coverage HTML report all name a directory under output/cache/."""
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['tool']
    found = (
        data['pytest']['ini_options']['cache_dir'],
        data['ruff']['cache-dir'],
        data['coverage']['html']['directory'],
    )
    assert all(value.startswith('output/cache/') for value in found), found
