"""COMMONS-BELOW-FLOOR: a missing lab_commons module names the heal; any other import failure passes through."""

from __future__ import annotations

import os
import re
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
