"""LEDGER-MIGRATES-ON-INSTALL: each installing door migrates the box ledger once, by capability, never silently."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import boxmigrate, dep
from dev_lab.dev.hpcaccount import steps

HELP_WITH = 'usage: python -m lab_commons.box {run,claim,claims,release,migrate} ...'
HELP_WITHOUT = 'usage: python -m lab_commons.box {run,claim,claims,release} ...'


def _env(tmp_path: Path) -> str:
    python = tmp_path / 'env' / 'python'
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('', encoding='utf-8')
    return str(python)


def _fake(
    help_text: str, *, migrate_rc: int = 0, ledger: str = '/ledger/box.sqlite'
) -> tuple[list[tuple[str, ...]], Callable[..., SimpleNamespace]]:
    calls: list[tuple[str, ...]] = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        if argv[-1] == '--help':
            return SimpleNamespace(returncode=0, stdout=help_text, stderr='')
        if argv[-1] == 'migrate':
            return SimpleNamespace(returncode=migrate_rc, stdout='', stderr='LedgerVersionRefused: boom')
        if argv[1] == '-c':
            return SimpleNamespace(returncode=0, stdout=ledger + '\n', stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    return calls, run


def _migrations(calls) -> list[tuple[str, ...]]:
    return [c for c in calls if c[1:] == ('-m', 'lab_commons.box', 'migrate')]


def test_an_env_with_the_verb_is_migrated_exactly_once(tmp_path) -> None:
    python = _env(tmp_path)
    calls, run = _fake(HELP_WITH)
    assert boxmigrate.migrate(python, run=run) == 0
    assert _migrations(calls) == [boxmigrate.command(python)]


def test_an_env_without_the_verb_is_skipped_and_says_so(tmp_path, capsys) -> None:
    """PLANTED CONTROL: the same door against a lab-commons without ``migrate`` runs no migration."""
    python = _env(tmp_path)
    calls, run = _fake(HELP_WITHOUT)
    assert boxmigrate.migrate(python, run=run) == 0
    assert _migrations(calls) == []
    assert 'migration skipped' in capsys.readouterr().out


def test_a_missing_interpreter_is_skipped_and_says_so(tmp_path, capsys) -> None:
    calls, run = _fake(HELP_WITH)
    assert boxmigrate.migrate(str(tmp_path / 'absent'), run=run) == 0
    assert calls == []
    assert 'no interpreter' in capsys.readouterr().out


def test_a_failed_migration_names_the_ledger_and_the_command(tmp_path, capsys) -> None:
    python = _env(tmp_path)
    _, run = _fake(HELP_WITH, migrate_rc=3)
    assert boxmigrate.migrate(python, run=run) == 3
    err = capsys.readouterr().err
    assert '/ledger/box.sqlite' in err
    assert f'{python} -m lab_commons.box migrate' in err
    assert 'LedgerVersionRefused' in err


def _project(tmp_path: Path) -> Path:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="empty"\nversion="0"\n', encoding='utf-8')
    return tmp_path


def _dep_run(help_text: str, *, migrate_rc: int = 0) -> tuple[list[tuple[str, ...]], Callable[..., SimpleNamespace]]:
    """A dep fake whose sync CREATES the interpreter it installs, then answers the box probe."""
    calls, box = _fake(help_text, migrate_rc=migrate_rc)

    def run(argv, **kwargs: object) -> SimpleNamespace:
        if len(argv) > 1 and argv[1] == 'sync':
            env = kwargs.get('env') or {}
            prefix = Path(str(env.get('UV_PROJECT_ENVIRONMENT', '')))
            if prefix.parts:
                for python in (prefix / 'Scripts' / 'python.exe', prefix / 'bin' / 'python'):
                    python.parent.mkdir(parents=True, exist_ok=True)
                    python.write_text('', encoding='utf-8')
        return box(argv, **kwargs)

    return calls, run


@pytest.fixture
def _installed_envs_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake sync writes an empty interpreter; its environment key is read without starting it."""
    monkeypatch.setattr(dep, '_snapshot', lambda python: (str(Path(python).parent.parent), 'fake-env-key'))


@pytest.mark.usefixtures('_installed_envs_answer')
def test_dep_bootstrap_migrates_the_installed_env(tmp_path) -> None:
    root = _project(tmp_path)
    calls, run = _dep_run(HELP_WITH)
    assert dep.main(['--bootstrap', str(root)], cwd=root, run=run) == 0
    assert len(_migrations(calls)) == 1


@pytest.mark.usefixtures('_installed_envs_answer')
def test_dep_bootstrap_reports_a_failed_migration(tmp_path, capsys) -> None:
    root = _project(tmp_path)
    _, run = _dep_run(HELP_WITH, migrate_rc=5)
    assert dep.main(['--bootstrap', str(root)], cwd=root, run=run) == 5
    assert 'box ledger migration failed' in capsys.readouterr().err


@pytest.mark.usefixtures('_installed_envs_answer')
def test_dep_bootstrap_without_the_verb_migrates_nothing(tmp_path) -> None:
    """PLANTED CONTROL for the door: no verb, no migration, the door still succeeds."""
    root = _project(tmp_path)
    calls, run = _dep_run(HELP_WITHOUT)
    assert dep.main(['--bootstrap', str(root)], cwd=root, run=run) == 0
    assert _migrations(calls) == []


def test_the_hpc_build_migrates_after_its_venv_and_reports_a_failure(tmp_path, monkeypatch) -> None:
    seen: list[str] = []

    def fake(python: str, **_kwargs: object) -> int:
        seen.append(python)
        return 7

    monkeypatch.setattr(boxmigrate, 'migrate', fake)
    checkout = tmp_path / 'repo'
    checkout.mkdir()
    (checkout / 'pyproject.toml').write_text('[tool.lab_commons.hpc]\n', encoding='utf-8')
    spec = SimpleNamespace(python='3.12', root=(tmp_path / 'root').as_posix())
    monkeypatch.setattr(steps, 'checkout_of', lambda *_a: checkout)
    monkeypatch.setattr(steps, '_key', lambda *_a: 'k')
    step = steps.Step(steps.Tools(sh=('true',)), dry=False)
    monkeypatch.setattr(step, 'change', lambda *_a, **_k: 0)
    assert steps.build(step, spec, tmp_path, SimpleNamespace(name='repo')) == 7
    assert seen
    assert seen[0].endswith(str(Path('bin') / 'python'))
