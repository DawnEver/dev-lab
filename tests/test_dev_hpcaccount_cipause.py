"""``hpcaccount ci-pause`` / ``ci-resume``: backup first, only the marked lines, the declared lines back, no job."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Final

import pytest
from _hpcaccount_fakes import MARKED, home_of, tools_of

from dev_lab.dev.hpcaccount import backup, cimark, cipause, deploy
from dev_lab.dev.hpcaccount.spec import MARK

VERIFICATION: Final = (
    '[deploy]\nhost = "login01"\nroot = "repos"\nrole = "verification"\n'
    'repos = [{ name = "dev-lab", url = "https://forge.example/dev-lab.git", ref = "trunk" }]\n'
)
MINE: Final = '0 1 * * * echo mine\n'


@pytest.fixture(autouse=True)
def _slurm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, '_slurm_dirs', lambda: ['/opt/slurm/bin'])


def _account(tmp_path: Path, cron: str = MINE + MARKED, text: str = VERIFICATION) -> tuple[Path, Path]:
    home, machine = home_of(tmp_path, text)
    (tmp_path / 'crontab.txt').write_text(cron, encoding='utf-8')
    return home, machine


def _cron(tmp_path: Path) -> str:
    return (tmp_path / 'crontab.txt').read_text(encoding='utf-8')


def test_pause_backs_up_first_then_removes_only_the_marked_lines(tmp_path: Path) -> None:
    home, machine = _account(tmp_path)
    assert cipause.ci_pause(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 0
    assert _cron(tmp_path) == MINE
    (saved,) = home.glob('.cache/dev-lab/*/*/*/backup/*/crontab.txt')
    assert saved.read_text(encoding='utf-8') == MINE + MARKED
    assert str(saved.parent) in cimark.marker(home).read_text(encoding='utf-8')


def test_a_failed_backup_removes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, machine = _account(tmp_path)
    monkeypatch.setattr(cipause, 'write_backup', lambda *_a: 'could not write the backup')
    assert cipause.ci_pause(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == MINE + MARKED
    assert not cimark.marker(home).exists()


def test_a_research_account_is_refused_and_untouched(tmp_path: Path) -> None:
    home, machine = _account(tmp_path, text=VERIFICATION.replace('"verification"', '"research"'))
    assert cipause.ci_pause(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == MINE + MARKED
    assert not (home / '.cache').exists()


def test_resume_restores_exactly_the_declared_lines_and_clears_the_marker(tmp_path: Path) -> None:
    home, machine = _account(tmp_path)
    tools = tools_of(tmp_path)
    assert cipause.ci_pause(['--config', str(machine)], home=home, tools=tools) == 0
    assert cipause.ci_resume(['--config', str(machine)], home=home, tools=tools) == 0
    lines = _cron(tmp_path).splitlines()
    assert lines[0] == MINE.strip()
    assert len(lines) == 2
    assert lines[1].endswith(f'{MARK}dev-lab')
    assert not cimark.marker(home).exists()


def test_resume_without_the_marker_is_refused(tmp_path: Path) -> None:
    home, machine = _account(tmp_path)
    assert cipause.ci_resume(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == MINE + MARKED


def test_a_paused_account_refuses_deploy_and_restore_naming_the_resume_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, machine = _account(tmp_path)
    tools = tools_of(tmp_path)
    assert cipause.ci_pause(['--config', str(machine)], home=home, tools=tools) == 0
    assert deploy.deploy(['--config', str(machine)], home=home, hostname='login01', tools=tools) == 2
    assert backup.backup(['--config', str(machine), '--restore', 'latest'], home=home, tools=tools) == 2
    assert capsys.readouterr().err.count('ci-resume-fleet') == 2
    assert _cron(tmp_path) == MINE


def test_the_unpaused_control_reaches_past_the_guard(tmp_path: Path) -> None:
    home, _ = _account(tmp_path)
    assert cimark.paused_refusal(home) == ''
    assert 'exit 2' in cimark.paused_guard()


def test_no_job_cancellation_path_exists() -> None:
    for module in (cipause, backup, cimark):
        source = inspect.getsource(module)
        assert not {'scancel', 'squeue', 'sbatch', 'kill'} & set(source.replace('(', ' ').split())
