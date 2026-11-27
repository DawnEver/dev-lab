"""MACHINE-FILE-IS-RENDERED: no write reaches the machine file but its doors; each refusal names them."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from lab_commons.config import CONFIG_ENV, config_path
from lab_commons.hostenv import HOME_ENV

from dev_lab.dev import _deny_machinefile_row, codeplace, devhost, machineguard
from dev_lab.dev.hooks import DENY_RULES, denies, rules_by_id
from dev_lab.dev.privatemarkers import load_markers, scan_text

ROW = rules_by_id(DENY_RULES)[machineguard.RULE_ID]


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(CONFIG_ENV, raising=False)  # the suite's isolation override; this fixture places the file
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


#: The file the row's examples spell (its tail at import); the suite's own override may name another.
_EXAMPLE_FILE = Path('/', *_deny_machinefile_row._PARTS)


def _shell(command: str, machine: Path = _EXAMPLE_FILE) -> str | None:
    return machineguard.judge({'tool_name': 'Bash', 'tool_input': {'command': command}}, machine=machine)


@pytest.mark.parametrize('command', ROW.refuses)
def test_the_shell_row_refuses_a_write_onto_the_file(command: str) -> None:
    """Both halves: the rendered prefilter fires, and the judge it asks refuses naming the doors."""
    assert denies([ROW], command) == machineguard.RULE_ID
    reason = _shell(command)
    assert reason is not None
    assert reason.startswith(f'{machineguard.RULE_ID}:')
    assert 'devhost local set' in reason


@pytest.mark.parametrize('command', ROW.permits)
def test_the_shell_row_permits_reads_and_the_door(command: str) -> None:
    assert _shell(command) is None


def test_the_row_pattern_names_no_machine_home(machine: Path) -> None:
    """The row is home-agnostic: the file below ANY home -- a tmp one here -- is refused."""
    assert denies([ROW], f'echo x > {machine.as_posix()}') == machineguard.RULE_ID
    assert _shell(f'echo x > {machine.as_posix()}', machine) is not None


_FAKE = 'zzfakeprivatestation'
_RENDER = (
    'import json; from dev_lab.dev.hooks import DENY_RULES, rules_by_id; '
    f'print(json.dumps(rules_by_id(DENY_RULES)[{machineguard.RULE_ID!r}].rendered()))'
)


def test_the_rendered_rules_never_carry_the_machine_file_name(tmp_path: Path) -> None:
    """dev-lab #1000: a family repo's TRACKED deny-rules.json carried the machine file's private name.

    The render under a machine file named for a fake private repo holds no trace of the name, while the judge
    still refuses a write onto that very file. PLANTED CONTROL: the private-marker scan flags a pattern that
    spells the name, so its silence on the render is a measurement.
    """
    home_dir = tmp_path / 'home'
    machine = home_dir / 'config' / f'{_FAKE}.toml'
    env = os.environ | {HOME_ENV: str(home_dir), CONFIG_ENV: str(machine)}
    done = subprocess.run(
        [sys.executable, '-c', _RENDER], env=env, capture_output=True, text=True, encoding='utf-8', check=False
    )
    assert done.returncode == 0, done.stderr
    markers = _markers_naming(tmp_path, _FAKE)
    assert _FAKE not in done.stdout
    assert scan_text(done.stdout, markers) == []
    planted = machineguard.shell_write_pattern(machineguard.machine_tail(machine))
    assert scan_text(json.dumps({'pattern': planted}), markers), 'the marker scan cannot see the name'
    assert _shell(f'echo x >> {machine.as_posix()}', machine) is not None
    assert _shell(f'echo x >> {(machine.parent / "other.toml").as_posix()}', machine) is None


def _markers_naming(tmp_path: Path, name: str) -> tuple[re.Pattern[str], ...]:
    path = tmp_path / 'private-markers'
    path.write_text(name + '\n', encoding='utf-8')
    return load_markers(path)


def test_the_admit_door_exits_one_with_the_refusal(machine: Path) -> None:
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': f'echo x > {machine.as_posix()}'}})
    out = io.BytesIO()
    assert machineguard.main(['--admit'], stdin=io.BytesIO(payload.encode()), stdout=out) == 1
    assert out.getvalue().decode().startswith(machineguard.RULE_ID)
    other = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'echo x > a/b.toml'}})
    assert machineguard.main(['--admit'], stdin=io.BytesIO(other.encode()), stdout=io.BytesIO()) == 0
