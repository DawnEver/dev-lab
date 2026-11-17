"""SYNC-OWNS-ITS-ENV: a sync or relock runs only under the target checkout's own interpreter.

2026-11-17: ``forge sync`` in a checkout with no venv ran ``uv sync --project <it> --python <the invoker>``, and the
invoker was another checkout's venv. Every uv run here is a fake runner; no real environment is synced.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import _dep_project, dep
from dev_lab.dev._dep_project import own_interpreter as real_own_interpreter


@pytest.fixture(autouse=True)
def _the_real_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo conftest's stand-in: these tests measure the refusal itself."""
    monkeypatch.setattr(_dep_project, 'own_interpreter', real_own_interpreter)


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    return root


def _foreign(tmp_path: Path) -> Path:
    python = tmp_path / 'other' / '.venv' / 'Scripts' / 'python.exe'
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('foreign', encoding='utf-8')
    return python


def _tree(top: Path) -> list[Path]:
    return sorted(path.relative_to(top) for path in top.rglob('*'))


@pytest.mark.parametrize('argv', [['--sync'], ['--lock-upgrade']])
def test_a_foreign_interpreter_is_refused_by_name_and_the_foreign_env_is_untouched(
    tmp_path, monkeypatch, capsys, argv
) -> None:
    root = _project(tmp_path / 'config')
    foreign = _foreign(tmp_path)
    before = _tree(foreign.parents[1])
    monkeypatch.setattr(sys, 'executable', str(foreign))
    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.main(argv, cwd=root, run=run) == 1
    said = capsys.readouterr().out
    assert 'SYNC-OWNS-ITS-ENV:' in said
    assert str(foreign) in said
    assert str(root) in said
    assert f'\n{foreign} -m dev_lab.dev.dep --bootstrap {root}' in said, 'the door stands on its own line'
    assert not [call for call in calls if call[1:2] in {('sync',), ('lock',)}], 'nothing synced or relocked'
    assert _tree(foreign.parents[1]) == before
    assert foreign.read_text(encoding='utf-8') == 'foreign'


def test_the_lock_upgrade_command_refuses_a_foreign_interpreter(tmp_path) -> None:
    root = _project(tmp_path / 'config')
    with pytest.raises(_dep_project.ForeignEnvRefused, match='SYNC-OWNS-ITS-ENV'):
        _dep_project.lock_upgrade_command(root, str(_foreign(tmp_path)), '0.0.0')


def test_the_checkouts_own_interpreter_proceeds(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path / 'config')
    own = root / '.venvs' / 'abc' / 'Scripts' / 'python.exe'
    own.parent.mkdir(parents=True)
    own.write_text('', encoding='utf-8')
    monkeypatch.setattr(sys, 'executable', str(_foreign(tmp_path)))
    assert _dep_project.own_interpreter(root, str(own)) == str(own)
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    command = _dep_project.uv_command(root, str(own), (), syncing=True, upgrade_packages=(), frozen=True)
    assert command[command.index('--python') + 1] == str(own)


def test_only_a_frozen_bootstrap_builds_under_the_invoking_interpreter(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path / 'config')
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    missing = str(root / '.venv' / 'Scripts' / 'python.exe')
    command = _dep_project.uv_command(root, missing, (), syncing=True, upgrade_packages=(), frozen=True)
    assert command[command.index('--python') + 1] == sys.executable
    with pytest.raises(_dep_project.ForeignEnvRefused):
        _dep_project.uv_command(root, missing, (), syncing=False, upgrade_packages=(), frozen=True)
