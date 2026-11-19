"""``hpcaccount ci-pause`` / ``ci-resume``: refused on drift, only the marked lines, the declared lines back, no job."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Final

import pytest
from _hpcaccount_fakes import FAMILY, HOST, home_of, tools_of

from dev_lab.dev.hpcaccount import cimark, cipause, deploy, drift
from dev_lab.dev.hpcaccount.spec import MARK, cron_lines, load

MINE: Final = '0 1 * * * echo mine\n'


@pytest.fixture(autouse=True)
def _slurm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, 'slurm_dirs', lambda: ['/opt/slurm/bin'])


def _account(tmp_path: Path, mine: str = '', extra: str = '', family: str = FAMILY) -> tuple[Path, Path, list[str]]:
    """A home, the machine file, and the args naming its clone; its crontab is the declared lines plus *mine*."""
    home, clone, machine = home_of(tmp_path, extra, family)
    spec = load(machine)
    lines = cron_lines(spec, home, slurm=['/opt/slurm/bin']) if spec else []
    (tmp_path / 'crontab.txt').write_text(mine + ''.join(f'{line}\n' for line in lines), encoding='utf-8')
    return home, machine, ['--config', str(machine), '--from', str(clone), '--host', HOST]


def _cron(tmp_path: Path) -> str:
    return (tmp_path / 'crontab.txt').read_text(encoding='utf-8')


def test_pause_without_drift_removes_only_the_marked_lines(tmp_path: Path) -> None:
    home, _, args = _account(tmp_path)
    assert MARK in _cron(tmp_path)
    assert cipause.ci_pause(args, home=home, tools=tools_of(tmp_path)) == 0
    assert _cron(tmp_path) == ''
    assert cimark.marker(home).is_file()
    assert not list(home.glob('.cache/dev-lab/*/*/*/backup')), 'nothing is backed up'


def test_pause_refuses_while_the_account_drifts_naming_each_item_and_the_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, _, args = _account(tmp_path, mine=MINE, extra='\n[user]\nshell = "zsh"\n')
    before = _cron(tmp_path)
    assert cipause.ci_pause(args, home=home, tools=tools_of(tmp_path)) == 2
    err = capsys.readouterr().err
    assert 'echo mine' in err
    assert 'user.shell' in err
    assert 'declare it in the config source or accept its loss with --discard-drift' in err
    assert _cron(tmp_path) == before
    assert not cimark.marker(home).exists()


def test_discard_drift_accepts_the_loss_and_keeps_the_users_own_line(tmp_path: Path) -> None:
    home, _, args = _account(tmp_path, mine=MINE)
    assert cipause.ci_pause([*args, drift.DISCARD], home=home, tools=tools_of(tmp_path)) == 0
    assert _cron(tmp_path) == MINE
    assert '1 drift item(s) discarded' in cimark.marker(home).read_text(encoding='utf-8')


def test_a_stale_clone_refuses_the_pause_and_removes_nothing(tmp_path: Path) -> None:
    home, _, args = _account(tmp_path)
    before = _cron(tmp_path)
    args[args.index('--from') + 1] = str(tmp_path / 'gone')
    assert cipause.ci_pause(args, home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == before


def test_a_research_account_is_refused_and_untouched(tmp_path: Path) -> None:
    home, machine, args = _account(tmp_path, mine=MINE, family=FAMILY.replace('"verification"', '"research"'))
    assert 'role = "research"' in machine.read_text(encoding='utf-8')
    assert cipause.ci_pause([*args, drift.DISCARD], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == MINE
    assert not (home / '.cache').exists()


def test_resume_restores_exactly_the_declared_lines_and_clears_the_marker(tmp_path: Path) -> None:
    home, machine, args = _account(tmp_path, mine=MINE)
    tools = tools_of(tmp_path)
    assert cipause.ci_pause([*args, drift.DISCARD], home=home, tools=tools) == 0
    assert cipause.ci_resume(['--config', str(machine)], home=home, tools=tools) == 0
    lines = _cron(tmp_path).splitlines()
    assert lines[0] == MINE.strip()
    assert len(lines) == 2
    assert lines[1].endswith(f'{MARK}dev-lab')
    assert not cimark.marker(home).exists()


def test_resume_without_the_marker_is_refused(tmp_path: Path) -> None:
    home, machine, _ = _account(tmp_path)
    before = _cron(tmp_path)
    assert cipause.ci_resume(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == before


def test_a_paused_account_refuses_deploy_naming_the_resume_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, machine, args = _account(tmp_path)
    tools = tools_of(tmp_path)
    assert cipause.ci_pause(args, home=home, tools=tools) == 0
    assert deploy.deploy(['--config', str(machine)], home=home, hostname='login01', tools=tools) == 2
    assert 'ci-resume-fleet' in capsys.readouterr().err
    assert _cron(tmp_path) == ''


def test_the_unpaused_control_reaches_past_the_guard(tmp_path: Path) -> None:
    home, _, _ = _account(tmp_path)
    assert cimark.paused_refusal(home) == ''
    assert 'exit 2' in cimark.paused_guard()


def test_no_job_cancellation_path_exists() -> None:
    for module in (cipause, cimark, drift):
        source = inspect.getsource(module)
        assert not {'scancel', 'squeue', 'sbatch', 'kill'} & set(source.replace('(', ' ').split())
