"""SSHHOLD: one authenticated ssh connection held for a work session, every later command riding it.

Unit: the marker framing and its parse, the ceiling refused (never clamped), the state file, and the audit
line -- with a PLANTED code and token that must never reach it. End to end: the real holder process driving a
FAKE ``ssh`` (:file:`_sshhold_fake.py`, a python loop speaking the same marker protocol and checking the
keyboard-interactive answer through ``SSH_ASKPASS``), so no network and no bash are needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dev_lab.dev import sshhold
from dev_lab.dev.sshhold import HoldRefused

FAKE = (sys.executable, str(Path(__file__).with_name('_sshhold_fake.py')))
CODE = '481516'


def test_a_frame_runs_the_command_merged_and_ends_on_the_marker_with_its_status() -> None:
    framed = sshhold.frame('echo hi', 'abc')
    assert framed.startswith('{ echo hi\n} 2>&1')
    assert '__SSHHOLD_abc_%s' in framed
    assert framed.endswith('\n')


def test_the_marker_splits_the_output_from_the_status() -> None:
    assert sshhold.split_marker('one\ntwo\n\n__SSHHOLD_n1_7\n', 'n1') == ('one\ntwo\n', 7)
    assert sshhold.split_marker('one\ntwo\n', 'n1') is None
    assert sshhold.split_marker('x\n__SSHHOLD_other_0\n', 'n1') is None


def test_hours_above_the_ceiling_are_refused_never_clamped() -> None:
    sshhold.check_hours(2.0, 2.0)
    with pytest.raises(HoldRefused, match=r'max_hours'):
        sshhold.check_hours(2.5, 2.0)
    with pytest.raises(HoldRefused):
        sshhold.check_hours(0.0, 2.0)


def test_the_ceiling_reads_the_machine_file_and_defaults_to_the_ruled_four_hours() -> None:
    assert sshhold.ceiling({}) == sshhold.DEFAULT_MAX_HOURS == 4.0  # user ruling 2026-11-09
    assert sshhold.ceiling({'max_hours': 6}) == 6.0


def test_the_state_file_round_trips_and_names_the_dest_safely() -> None:
    session = sshhold.Session(dest='ops@forge-a1', pid=12, port=4000, token='t' * 8, opened=1.0, expires=2.0)
    sshhold.write_session(session)
    path = sshhold.state_path('ops@forge-a1')
    assert path.parent == sshhold.state_dir()
    assert '@' not in path.name
    assert sshhold.read_session('ops@forge-a1') == session
    assert sshhold.read_session('nobody@nowhere') is None


def test_the_audit_carries_the_command_and_status_never_the_code_or_token() -> None:
    sshhold.audit('run', 'ops@forge-a1', command='uptime', status=0, duration_s=0.5)
    line = json.loads(sshhold.audit_path().read_text(encoding='utf-8').splitlines()[-1])
    assert {'time', 'dest', 'verb', 'command', 'status', 'duration_s'} <= set(line)
    assert (line['command'], line['status']) == ('uptime', 0)


def test_a_held_session_runs_commands_on_one_connection_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    dest = 'ops@fake'
    said = sshhold.open_session(dest, 1.0, CODE, ssh=FAKE)
    try:
        held = sshhold.read_session(dest)
        assert held is not None
        assert f'holder pid {held.pid}' in said  # the holder's own pid, never a venv launcher's
        assert sshhold.run_command(dest, 'echo hello', timeout_s=60) == ('hello\n', 0)
        output, status = sshhold.run_command(dest, f'echo again&& "{sys.executable}" -c "raise SystemExit(3)"', 60)
        assert (output, status) == ('again\n', 3)
        session = sshhold.read_session(dest)
        assert session is not None
        assert any(dest in line and 'left' in line for line in sshhold.status_lines())
    finally:
        sshhold.close_session(dest)
    assert sshhold.read_session(dest) is None
    audit = sshhold.audit_path().read_text(encoding='utf-8')
    assert CODE not in audit  # planted control: the code and the token were both live this run
    assert session.token not in audit
    assert [json.loads(line)['verb'] for line in audit.splitlines()] == ['open', 'run', 'run', 'close']


def test_a_wrong_code_fails_the_open_and_leaves_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    with pytest.raises(HoldRefused, match='authenticat'):
        sshhold.open_session('ops@fake', 1.0, '000000', ssh=FAKE)
    assert sshhold.read_session('ops@fake') is None


def test_a_dropped_connection_is_named_and_the_session_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FAKESSH_CODE', '')
    dest = 'ops@fake'
    sshhold.open_session(dest, 1.0, '', ssh=FAKE)  # an empty answer is allowed (a trusted window)
    with pytest.raises(HoldRefused, match='ssh connection ended'):
        sshhold.run_command(dest, '__drop__', timeout_s=60)
    assert sshhold.read_session(dest) is None


def test_a_dead_holder_is_reported_and_its_state_removed() -> None:
    sshhold.write_session(sshhold.Session('ops@gone', 1, 1, 'x', 0.0, 9e12))
    assert any('ops@gone' in line and 'dead' in line for line in sshhold.status_lines())
    assert sshhold.read_session('ops@gone') is None


def test_the_cli_refuses_hours_above_the_ceiling(capsys: pytest.CaptureFixture[str]) -> None:
    assert sshhold.main(['open', 'ops@x', '--hours', '99', '--code', '1']) == 2
    assert 'max_hours' in capsys.readouterr().err
