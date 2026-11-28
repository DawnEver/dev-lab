"""SYNC-OWNS-ITS-ENV: a sync or relock runs only under the target checkout's own interpreter.

2026-11-17: ``forge sync`` in a checkout with no venv ran ``uv sync --project <it> --python <the invoker>``, and the
invoker was another checkout's venv. Every uv run here is a fake runner; no real environment is synced.
"""

import sys
from collections.abc import Callable
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
    command = _dep_project.uv_command(root, str(own), (), frozen=True)
    assert command[command.index('--python') + 1] == str(own)


def test_only_a_frozen_bootstrap_builds_under_the_invoking_interpreter(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path / 'config')
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    missing = str(root / '.venv' / 'Scripts' / 'python.exe')
    command = _dep_project.uv_command(root, missing, (), frozen=True)
    assert command[command.index('--python') + 1] == sys.executable
    with pytest.raises(_dep_project.ForeignEnvRefused):
        _dep_project.uv_command(root, missing, (), frozen=False)


def test_a_bootstrap_the_caller_cannot_serve_asks_uv_for_the_targets_requires_python(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\nrequires-python = ">=99.0"\n', encoding='utf-8'
    )
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    missing = str(root / '.venv' / 'Scripts' / 'python.exe')
    command = _dep_project.uv_command(root, missing, (), frozen=True)
    assert command[command.index('--python') + 1] == '>=99.0'


@pytest.mark.parametrize(
    ('running', 'spec', 'caller'),
    [
        ((3, 12, 9), '>=3.13', False),
        ((3, 13, 1), '>=3.13', True),
        ((3, 13, 1), '>=3.12,<3.13', False),
        ((3, 12, 9), '==3.12.*', True),
        ((3, 12, 9), '~=3.11', True),
        ((3, 12, 9), '~=3.13.0', False),
        ((3, 12, 9), '>=3.12; nonsense', False),
    ],
)
def test_a_fitting_caller_builds_and_any_other_hands_uv_the_spec(tmp_path, running, spec, *, caller) -> None:
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text(f'[project]\nname="e"\nrequires-python = "{spec}"\n', encoding='utf-8')
    assert _dep_project.bootstrap_python(root, running=running) == (sys.executable if caller else spec)


def _own_env(root: Path, cfg: str) -> Path:
    """An own environment of *root* whose ``pyvenv.cfg`` says *cfg* (empty: no cfg at all)."""
    python = root / '.venvs' / 'abc' / 'Scripts' / 'python.exe'
    python.parent.mkdir(parents=True)
    python.write_text('', encoding='utf-8')
    if cfg:
        (python.parents[1] / 'pyvenv.cfg').write_text(f'home = /x\n{cfg}\n', encoding='utf-8')
    return python


@pytest.mark.parametrize(
    ('cfg', 'version'),
    [
        ('version_info = 3.15', (3, 15)),
        ('version = 3.14.10', (3, 14, 10)),
        ('implementation = CPython', None),
        ('', None),
    ],
)
def test_an_environments_python_is_read_from_its_pyvenv_cfg(tmp_path, cfg, version) -> None:
    assert _dep_project.env_version(str(_own_env(tmp_path, cfg))) == version


def test_a_bootstrap_rebuilds_an_environment_its_requires_python_refuses(tmp_path, monkeypatch) -> None:
    """2026-11-27: every family venv ran 3.15 when the family moved to 3.14, and a bootstrap reused it, failing."""
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text('[project]\nname="e"\nrequires-python = ">=99.0"\n', encoding='utf-8')
    unfit = str(_own_env(root, 'version_info = 3.15'))
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    command = _dep_project.uv_command(root, unfit, (), frozen=True)
    assert command[command.index('--python') + 1] == '>=99.0'


def test_a_sync_or_relock_under_an_unfit_environment_is_refused_naming_the_bootstrap(tmp_path) -> None:
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text('[project]\nname="e"\nrequires-python = ">=99.0"\n', encoding='utf-8')
    unfit = str(_own_env(root, 'version_info = 3.15'))
    with pytest.raises(_dep_project.UnfitEnvRefused, match=r'runs Python 3\.15') as refused:
        _dep_project.own_interpreter(root, unfit)
    assert f'\n{sys.executable} -m dev_lab.dev.dep --bootstrap {root}' in str(refused.value), 'the door, own line'
    with pytest.raises(_dep_project.UnfitEnvRefused):
        _dep_project.lock_upgrade_command(root, unfit, '0.0.0')


def test_a_fitting_environment_is_its_own_interpreter(tmp_path) -> None:
    """Planted control: the same environment under a requirement it meets proceeds."""
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text('[project]\nname="e"\nrequires-python = ">=3.15,<3.16"\n', encoding='utf-8')
    fit = str(_own_env(root, 'version_info = 3.15'))
    assert _dep_project.own_interpreter(root, fit) == fit


def _uv_answers(code: int, said: str, calls: list[tuple[str, ...]]) -> Callable[..., SimpleNamespace]:
    def run(command, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(command))
        return SimpleNamespace(returncode=code, stdout=said, stderr='')

    return run


def test_a_missing_interpreter_is_fetched_through_the_network_door(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text('[project]\nname="e"\nrequires-python = ">=99.0"\n', encoding='utf-8')
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    monkeypatch.setattr(_dep_project, '_found', lambda _uv, _spec: False)
    calls: list[tuple[str, ...]] = []
    assert _dep_project.fetch_python(root, run=_uv_answers(0, '', calls), environment=None) == ''
    assert calls == [('uv', 'python', 'install', '>=99.0')]


def test_a_failed_fetch_refuses_naming_the_spec_and_the_network_door(tmp_path, monkeypatch) -> None:
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text('[project]\nname="e"\nrequires-python = ">=99.0"\n', encoding='utf-8')
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    monkeypatch.setattr(_dep_project, '_found', lambda _uv, _spec: False)
    run = _uv_answers(2, 'error: No interpreter found for Python >=99.0', [])
    said = _dep_project.fetch_python(root, run=run, environment=None)
    assert '>=99.0' in said
    assert f'{sys.executable} -m dev_lab.dev.netverb -- uv python install ">=99.0"' in said


def test_a_host_holding_a_fitting_interpreter_fetches_nothing(tmp_path, monkeypatch) -> None:
    """Planted control: the fetch is not a step every bootstrap pays."""
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text('[project]\nname="e"\nrequires-python = ">=3.0"\n', encoding='utf-8')
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    monkeypatch.setattr(_dep_project, '_found', lambda _uv, _spec: True)
    calls: list[tuple[str, ...]] = []
    assert _dep_project.fetch_python(root, run=_uv_answers(0, '', calls), environment=None) == ''
    assert calls == []


@pytest.mark.parametrize(('cfg', 'reused'), [('version_info = 3.12.12', False), ('version_info = 3.14.10', True)])
def test_a_bootstrap_builds_on_requires_python_and_reuses_only_a_matching_env(
    tmp_path, monkeypatch, cfg, *, reused
) -> None:
    """dev-lab #1093: a 3.12 env under ``==3.14.*`` is rebuilt on a fitting Python; a 3.14 env is reused."""
    root = _project(tmp_path / 'config')
    (root / 'pyproject.toml').write_text('[project]\nname="e"\nrequires-python = "==3.14.*"\n', encoding='utf-8')
    env = str(_own_env(root, cfg))
    monkeypatch.setattr(_dep_project.shutil, 'which', lambda _name: 'uv')
    command = _dep_project.uv_command(root, env, (), frozen=True)
    built_on = command[command.index('--python') + 1]
    assert built_on == (env if reused else _dep_project.bootstrap_python(root))
    assert built_on != env or reused, 'the 3.12 interpreter is never handed to uv'
