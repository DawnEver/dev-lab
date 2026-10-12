"""The Windows Scheduled Task that makes a workstation a ``forge serve`` host; never installed by a test."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lab_commons.dev import servetask
from lab_commons.dev.venvpath import venv_interpreter


def _root(tmp_path: Path) -> Path:
    python = tmp_path / 'co' / venv_interpreter(os_name='nt')
    python.parent.mkdir(parents=True)
    python.touch()
    return tmp_path / 'co'


def test_the_task_serves_this_checkout_every_five_minutes_as_this_user_only_when_logged_on(tmp_path: Path) -> None:
    root = _root(tmp_path)
    argv = servetask.create_argv(root, user='DOM\\ada', mode='integrate')
    assert argv[:4] == ['schtasks', '/Create', '/TN', 'lab-forge-serve']
    assert argv[argv.index('/SC') + 1 : argv.index('/SC') + 4] == ['MINUTE', '/MO', '5']
    assert argv[argv.index('/RU') + 1] == 'DOM\\ada'
    assert '/IT' in argv  # only when the user is logged on
    assert '/RP' not in argv  # no stored password
    action = argv[argv.index('/TR') + 1]
    assert f'cd /d "{root}"' in action
    python = venv_interpreter(os_name='nt')
    assert action.endswith(f'&& "{python}" -m lab_commons.dev.forge serve --mode integrate --lock')


def test_a_dry_run_prints_the_exact_command_and_runs_nothing(tmp_path: Path, capsys) -> None:
    ran: list[list[str]] = []
    code = servetask.main(['--dry-run', '--root', str(_root(tmp_path))], run=ran.append)
    assert code == 0
    assert ran == []
    out = capsys.readouterr().out
    assert subprocess.list2cmdline(servetask.create_argv(_root_of(tmp_path), user=servetask.this_user())) in out
    assert 'schtasks /Change /TN lab-forge-serve /DISABLE' in out


def _root_of(tmp_path: Path) -> Path:
    return tmp_path / 'co'


def test_a_checkout_without_its_venv_is_refused(tmp_path: Path, capsys) -> None:
    ran: list[list[str]] = []
    assert servetask.main(['--root', str(tmp_path)], run=ran.append) == 2
    assert ran == []
    assert '.venv' in capsys.readouterr().err


def test_an_install_runs_the_one_command_it_would_print(tmp_path: Path) -> None:
    ran: list[list[str]] = []
    root = _root(tmp_path)
    assert servetask.main(['--root', str(root)], run=lambda argv: ran.append(argv) or 0, windows=True) == 0
    assert ran == [servetask.create_argv(root, user=servetask.this_user())]
