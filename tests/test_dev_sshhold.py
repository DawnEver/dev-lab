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


def test_forgetting_a_session_the_other_side_is_deleting_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forgetting a session the other side is already deleting is not an error.

    Windows CI 2026-11-10: the client and the ending holder both remove the state file; the loser of that race
    gets PermissionError (delete pending), which ``unlink(missing_ok=True)`` does not cover.

    PLANTED CONTROL: any other OSError still surfaces.
    """
    sshhold.write_session(sshhold.Session('ops@race', 1, 1, 'x', 0.0, 9e12))

    def pending(*_args: object, **_kw: object) -> None:
        raise PermissionError(13, 'delete pending')

    monkeypatch.setattr(sshhold.Path, 'unlink', pending)
    sshhold.forget('ops@race')

    def broken(*_args: object, **_kw: object) -> None:
        raise OSError(5, 'I/O error')

    monkeypatch.setattr(sshhold.Path, 'unlink', broken)
    with pytest.raises(OSError, match='I/O'):
        sshhold.forget('ops@race')


def test_a_quiet_session_lives_to_its_ceiling_and_the_ceiling_still_ends_it() -> None:
    """MEASURED 2026-11-10: ``open --hours 4`` expired 1800 s after the last ``run`` -- a default idle limit.

    No idle limit unless the machine file names one. PLANTED CONTROLS: the ceiling ends a session; a configured
    ``idle_minutes`` still ends a quiet one.
    """
    assert sshhold.idle_s({}) is None
    assert not sshhold.session_over(now=100.0, expires=200.0, quiet_s=31 * 60, idle=sshhold.idle_s({}))
    assert sshhold.session_over(now=200.0, expires=200.0, quiet_s=0, idle=None), 'PLANTED CONTROL: the ceiling'
    idle = sshhold.idle_s({'idle_minutes': 45})
    assert idle == 45 * 60
    assert sshhold.session_over(now=100.0, expires=200.0, quiet_s=46 * 60, idle=idle), 'a configured idle ends it'
    assert not sshhold.session_over(now=100.0, expires=200.0, quiet_s=44 * 60, idle=idle)


def test_one_code_answers_both_hops_of_a_jump_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A ProxyJump session asks the bastion's pam_oath and then the host's; ONE code answers both.

    Assumption (user ruling 2026-11-04): the bastion and the host share one TOTP secret. Each pam_oath records the
    step IT accepted, so the same code is spent once on each host and never twice on either.
    """
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    monkeypatch.setenv('FAKESSH_ARGV_OUT', str(tmp_path / 'argv.json'))
    dest = 'ops@inner'
    sshhold.open_session(dest, 1.0, CODE, ssh=(*FAKE, '-J', 'ops@bastion'))
    try:
        assert sshhold.run_command(dest, 'echo through', timeout_s=60) == ('through\n', 0)
    finally:
        sshhold.close_session(dest)
    argv = json.loads((tmp_path / 'argv.json').read_text(encoding='utf-8'))
    assert argv[argv.index('-J') + 1] == 'ops@bastion'
    assert argv.index('-J') < argv.index(dest)


def test_a_bastion_that_refuses_the_code_fails_the_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Planted control: the host would accept the code but the bastion's secret differs, so nothing opens."""
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    monkeypatch.setenv('FAKESSH_JUMP_CODE', '999999')
    with pytest.raises(HoldRefused, match='authenticat'):
        sshhold.open_session('ops@inner', 1.0, CODE, ssh=(*FAKE, '-J', 'ops@bastion'))
    assert sshhold.read_session('ops@inner') is None


def test_the_cli_jump_rides_both_the_plain_and_the_planned_open(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(sshhold, 'open_session', lambda *_a, ssh: seen.append(ssh) or 'opened')
    monkeypatch.setattr(sshhold, 'open_planned', lambda *_a, ssh: seen.append(ssh) or ['granted', 'opened'])
    assert sshhold.main(['open', 'ops@inner', '--hours', '1', '--code', CODE, '--jump', 'ops@bastion']) == 0
    plan = ['--plan', 'plan.json', '--digest', 'abc']
    assert sshhold.main(['open', 'ops@inner', '--hours', '1', '--code', CODE, '--jump', 'ops@bastion', *plan]) == 0
    assert sshhold.main(['open', 'ops@inner', '--hours', '1', '--code', CODE]) == 0
    assert seen == [('ssh', '-J', 'ops@bastion'), ('ssh', '-J', 'ops@bastion'), ('ssh',)]
