"""MACHINE-FILE-IS-RENDERED: no write reaches the machine file but its doors; each refusal names them."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from lab_commons.config import config_path
from lab_commons.home import HOME_ENV

from dev_lab.dev import codeplace, devhost, machineguard
from dev_lab.dev.hooks import DENY_RULES, denies, rules_by_id

ROW = rules_by_id(DENY_RULES)[machineguard.RULE_ID]


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text('[repos]\nalpha = "/x/alpha"\n', encoding='utf-8')
    return path


def _edit_hook(path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    payload = {'tool_name': 'Edit', 'tool_input': {'file_path': str(path)}, 'cwd': str(path.parent)}
    codeplace.main([], stdin=io.StringIO(json.dumps(payload)))
    return capsys.readouterr().out


def test_an_edit_of_the_machine_file_is_refused_naming_both_doors(
    machine: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _edit_hook(machine, capsys)
    reason = json.loads(out)['hookSpecificOutput']['permissionDecisionReason']
    assert reason.startswith(f'{machineguard.RULE_ID}:')
    assert 'devhost render --write' in reason
    assert 'devhost local set <table>.<key> <value>' in reason


def test_an_unrelated_file_is_not_refused_by_this_row(machine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """PLANTED CONTROL: a sibling file in the same directory is not the machine file."""
    assert machineguard.refuse_write(machine.with_name('other.toml')) is None
    assert machineguard.RULE_ID not in _edit_hook(machine.with_name('other.toml'), capsys)


def test_the_local_door_writes_the_key_and_says_what_changed(
    machine: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beta = (tmp_path / 'beta').as_posix()
    argv = ['--machine', str(machine), 'local', 'set', 'repos.beta', beta, '--backups', str(tmp_path / 'b')]
    assert devhost.main(argv) == 0
    assert f"local: [repos].beta: None -> '{beta}'" in capsys.readouterr().out
    text = machine.read_text(encoding='utf-8')
    assert f'beta = "{beta}"' in text
    assert 'alpha = "/x/alpha"' in text
    assert (
        devhost.main(['--machine', str(machine), 'local', 'unset', 'repos.alpha', '--backups', str(tmp_path / 'b')])
        == 0
    )
    assert 'alpha' not in machine.read_text(encoding='utf-8')


def test_the_local_door_refuses_a_relative_repo_path(machine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = machine.read_bytes()
    assert devhost.main(['--machine', str(machine), 'local', 'set', 'repos.beta', 'rel/beta']) == 2
    assert 'must be an absolute path' in capsys.readouterr().err
    assert machine.read_bytes() == before


@pytest.mark.parametrize('command', ROW.refuses)
def test_the_shell_row_refuses_a_write_onto_the_file(command: str) -> None:
    assert denies([ROW], command) == machineguard.RULE_ID


@pytest.mark.parametrize('command', ROW.permits)
def test_the_shell_row_permits_reads_and_the_door(command: str) -> None:
    assert denies([ROW], command) is None


def test_the_row_pattern_names_no_machine_home(machine: Path) -> None:
    """The row is home-agnostic: the file below ANY home -- a tmp one here -- is refused."""
    assert denies([ROW], f'echo x > {machine.as_posix()}') == machineguard.RULE_ID
