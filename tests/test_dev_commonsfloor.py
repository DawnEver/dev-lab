"""COMMONS-BELOW-FLOOR: a missing lab_commons module names the heal; any other import failure passes through."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import _dep_project, dep
from dev_lab.dev._dep_project import own_interpreter
from dev_lab.dev.commonsfloor import RULE, CommonsBelowFloor, importing
from dev_lab.dev.lockcheck import uv_version
from dev_lab.dev.venvpath import VENV_LAYOUTS

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


def test_the_named_heal_runs_from_a_foreign_kit_against_a_skewed_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The heal COMMONS-BELOW-FLOOR names is not itself a wall: SYNC-OWNS-ITS-ENV admits a foreign INVOKER.

    The skewed checkout keeps its own (broken) environment; the healthy kit that runs the door is another
    checkout's. The lock and the sync after it run under the TARGET's own interpreter, never the invoker's.
    """
    monkeypatch.setattr(_dep_project, 'own_interpreter', own_interpreter)  # the real guard, not conftest's stand-in
    root = tmp_path / 'skewed'
    root.mkdir()
    (root / 'pyproject.toml').write_text('[project]\nname="skewed"\nversion="0"\n', encoding='utf-8')
    own = root.joinpath('.venv', *VENV_LAYOUTS[os.name][1:])
    own.parent.mkdir(parents=True)
    own.write_text('the skewed kit', encoding='utf-8')
    healthy = tmp_path / 'healthy' / '.venv' / 'python'
    healthy.parent.mkdir(parents=True)
    healthy.write_text('a healthy dev-lab', encoding='utf-8')
    monkeypatch.setattr(sys, 'executable', str(healthy))
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: uv_version())
    # The target snapshot reads the env key with the standard library alone (dep._snapshot), so a skewed kit
    # answers it; the stub stands in for running the target's real interpreter.
    monkeypatch.setattr(dep, '_snapshot', lambda python: (str(Path(python or '').parent.parent), 'key'))
    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(str(part) for part in command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.main(['--lock-upgrade', str(root), '--upgrade-package', 'lab-commons'], cwd=tmp_path, run=run) == 0
    (lock,) = [call for call in calls if call[1:2] == ('lock',)]
    assert lock[2:4] == ('--upgrade-package', 'lab-commons')
    assert lock[lock.index('--python') + 1] == str(own)
    assert all(str(healthy) not in call for call in calls if call[1:2] in {('lock',), ('sync',)})


def _older_commons(tmp_path: Path) -> Path:
    """A fake lab-commons 0.0.1 shadowing the real one: a package without ``extras`` (or any submodule)."""
    site = tmp_path / 'site'
    (site / 'lab_commons').mkdir(parents=True)
    (site / 'lab_commons' / '__init__.py').write_text('', encoding='utf-8')
    info = site / 'lab_commons-0.0.1.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: lab-commons\nVersion: 0.0.1\n', encoding='utf-8')
    return site


def _dep_entry(site: Path | None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [str(site) if site else '', str(ROOT / 'src')]))}
    command = [sys.executable, '-m', 'dev_lab.dev.dep', '--help']
    return subprocess.run(command, capture_output=True, text=True, encoding='utf-8', env=env, cwd=ROOT, check=False)


def test_a_venv_behind_its_checkout_is_refused_with_the_sync_door(tmp_path: Path) -> None:
    """The 2026-11-22 wall: an older installed lab-commons makes the dep entry exit 2 naming `uv sync --frozen`."""
    ran = _dep_entry(_older_commons(tmp_path))
    assert ran.returncode == 2, ran.stderr
    assert 'Traceback' not in ran.stderr
    assert 'holds lab_commons 0.0.1, older than its code needs' in ran.stderr
    assert f'run `uv sync --frozen` in {ROOT}, then this again' in ran.stderr


def test_the_sync_door_stays_shut_on_a_current_venv() -> None:
    """Planted control: the same entry against the venv's own lab-commons is not refused."""
    ran = _dep_entry(None)
    assert ran.returncode == 0, ran.stderr
    assert RULE not in ran.stderr


def test_a_missing_name_in_lab_commons_is_walled_like_a_missing_module(tmp_path: Path) -> None:
    """``from lab_commons import extras`` fails as ImportError (not ModuleNotFoundError); the wall still speaks."""
    said = "cannot import name 'extras' from 'lab_commons'"
    with pytest.raises(CommonsBelowFloor) as refused, importing(tmp_path):
        raise ImportError(said, name='lab_commons')
    assert "cannot import name 'extras'" in str(refused.value)
