"""SSHHOLD: one authenticated ssh connection held for a work session, every later command riding it.

Unit: the marker framing and its parse, the ceiling refused (never clamped), the state file, and the audit
line -- with a PLANTED code and token that must never reach it. End to end: the real holder process driving a
FAKE ``ssh`` (:file:`_sshhold_fake.py`, a python loop speaking the same marker protocol and checking the
keyboard-interactive answer through ``SSH_ASKPASS``), so no network and no bash are needed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from dev_lab.dev import sshhold, sshholdplan, sshholdprobe, sshholdrun, sshholdstate, sshholdwire
from dev_lab.dev.hpcaccount import transport
from dev_lab.dev.sshholdwire import HoldRefused

FAKE = (sys.executable, str(Path(__file__).with_name('_sshhold_fake.py')))
CODE = '481516'


def test_a_frame_runs_the_command_merged_and_ends_on_the_marker_with_its_status() -> None:
    framed = sshholdwire.frame('echo hi', 'abc')
    assert framed.startswith('( echo hi\n) </dev/null 2>&1')
    assert '__SSHHOLD_abc_%s' in framed
    assert framed.endswith('\n')


def test_the_marker_splits_the_output_from_the_status() -> None:
    assert sshholdwire.split_marker('one\ntwo\n\n__SSHHOLD_n1_7\n', 'n1') == ('one\ntwo\n', 7)
    assert sshholdwire.split_marker('one\ntwo\n', 'n1') is None
    assert sshholdwire.split_marker('x\n__SSHHOLD_other_0\n', 'n1') is None


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
    session = sshholdstate.Session(dest='ops@forge-a1', pid=12, port=4000, token='t' * 8, opened=1.0, expires=2.0)
    sshholdstate.write_session(session)
    path = sshholdstate.state_path('ops@forge-a1')
    assert path.parent == sshholdstate.state_dir()
    assert '@' not in path.name
    assert sshholdstate.read_session('ops@forge-a1') == session
    assert sshholdstate.read_session('nobody@nowhere') is None


def test_the_audit_carries_the_command_and_status_never_the_code_or_token() -> None:
    sshholdstate.audit('run', 'ops@forge-a1', command='uptime', status=0, duration_s=0.5)
    line = json.loads(sshholdstate.audit_path().read_text(encoding='utf-8').splitlines()[-1])
    assert {'time', 'dest', 'verb', 'command', 'status', 'duration_s'} <= set(line)
    assert (line['command'], line['status']) == ('uptime', 0)


def test_a_held_session_runs_commands_on_one_connection_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    dest = 'ops@fake'
    said = sshhold.open_session(dest, 1.0, CODE, ssh=FAKE)
    try:
        held = sshholdstate.read_session(dest)
        assert held is not None
        assert f'holder pid {held.pid}' in said  # the holder's own pid, never a venv launcher's
        assert sshholdrun.run_command(dest, 'echo hello', timeout_s=60) == ('hello\n', 0)
        output, status = sshholdrun.run_command(dest, f'echo again&& "{sys.executable}" -c "raise SystemExit(3)"', 60)
        assert (output, status) == ('again\n', 3)
        session = sshholdstate.read_session(dest)
        assert session is not None
        assert any(dest in line and 'left' in line for line in sshhold.status_lines())
    finally:
        sshhold.close_session(dest)
    assert sshholdstate.read_session(dest) is None
    audit = sshholdstate.audit_path().read_text(encoding='utf-8')
    assert CODE not in audit  # planted control: the code and the token were both live this run
    assert session.token not in audit
    assert [json.loads(line)['verb'] for line in audit.splitlines()] == ['open', 'run', 'run', 'close']


def test_a_wrong_code_fails_the_open_and_leaves_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    with pytest.raises(HoldRefused, match='authenticate'):
        sshhold.open_session('ops@fake', 1.0, '000000', ssh=FAKE)
    assert sshholdstate.read_session('ops@fake') is None


def test_a_dropped_connection_is_named_and_the_session_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FAKESSH_CODE', '')
    dest = 'ops@fake'
    sshhold.open_session(dest, 1.0, '', ssh=FAKE)  # an empty answer is allowed (a trusted window)
    with pytest.raises(HoldRefused, match='ssh connection ended'):
        sshholdrun.run_command(dest, '__drop__', timeout_s=60)
    assert sshholdstate.read_session(dest) is None


def test_a_dead_holder_is_reported_and_its_state_removed() -> None:
    sshholdstate.write_session(sshholdstate.Session('ops@gone', 1, 1, 'x', 0.0, 9e12))
    assert any('ops@gone' in line and 'dead' in line for line in sshhold.status_lines())
    assert sshholdstate.read_session('ops@gone') is None


def test_the_cli_refuses_hours_above_the_ceiling(capsys: pytest.CaptureFixture[str]) -> None:
    assert sshhold.main(['open', 'ops@x', '--hours', '99', '--code', '1']) == 2
    assert 'max_hours' in capsys.readouterr().err


def test_forgetting_a_session_the_other_side_is_deleting_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forgetting a session the other side is already deleting is not an error.

    Windows CI 2026-11-10: the client and the ending holder both remove the state file; the loser of that race
    gets PermissionError (delete pending), which ``unlink(missing_ok=True)`` does not cover.

    PLANTED CONTROL: any other OSError still surfaces.
    """
    sshholdstate.write_session(sshholdstate.Session('ops@race', 1, 1, 'x', 0.0, 9e12))

    def pending(*_args: object, **_kw: object) -> None:
        raise PermissionError(13, 'delete pending')

    monkeypatch.setattr(sshholdstate.Path, 'unlink', pending)
    sshholdstate.forget('ops@race')

    def broken(*_args: object, **_kw: object) -> None:
        raise OSError(5, 'I/O error')

    monkeypatch.setattr(sshholdstate.Path, 'unlink', broken)
    with pytest.raises(OSError, match='I/O'):
        sshholdstate.forget('ops@race')


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
        assert sshholdrun.run_command(dest, 'echo through', timeout_s=60) == ('through\n', 0)
    finally:
        sshhold.close_session(dest)
    argv = json.loads((tmp_path / 'argv.json').read_text(encoding='utf-8'))
    assert argv[argv.index('-J') + 1] == 'ops@bastion'
    assert argv.index('-J') < argv.index(dest)


def test_a_bastion_that_refuses_the_code_fails_the_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Planted control: the host would accept the code but the bastion's secret differs, so nothing opens."""
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    monkeypatch.setenv('FAKESSH_JUMP_CODE', '999999')
    with pytest.raises(HoldRefused, match='authenticate'):
        sshhold.open_session('ops@inner', 1.0, CODE, ssh=(*FAKE, '-J', 'ops@bastion'))
    assert sshholdstate.read_session('ops@inner') is None


def test_the_cli_jump_rides_both_the_plain_and_the_planned_open(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(sshhold, 'section', lambda _name: {})  # no declared route: the flag alone decides
    monkeypatch.setattr(sshhold, 'open_session', lambda *_a, ssh: seen.append(ssh) or 'opened')
    monkeypatch.setattr(sshholdplan, 'offered', lambda _plan, _steps, **_k: 'preflight: green')
    monkeypatch.setattr(sshholdprobe, 'probe', lambda _dest, _ssh: 'proven')  # its own test: test_dev_sshhold_probe
    monkeypatch.setattr(
        sshholdplan,
        'open_planned',
        lambda *_a, routes, **_k: seen.append(routes('ops@inner')) or (True, ['granted', 'opened']),
    )
    assert sshhold.main(['open', 'ops@inner', '--hours', '1', '--code', CODE, '--jump', 'ops@bastion']) == 0
    plan = ['--plan', 'plan.json', '--digest', 'abc']
    assert sshhold.main(['open', '--hours', '1', '--code', CODE, '--jump', 'ops@bastion', *plan]) == 0
    assert sshhold.main(['open', 'ops@inner', '--hours', '1', '--code', CODE]) == 0
    assert seen == [('ssh', '-J', 'ops@bastion'), ('ssh', '-J', 'ops@bastion'), ('ssh',)]


def test_each_plan_host_opens_on_the_route_the_machine_file_declares_for_it(tmp_path: Path) -> None:
    """One plan, two hosts: the inner one through its declared bastion, the other direct -- never one route for both.

    PLANTED CONTROL: with no declaration both open direct, so the bastion comes from the table and nothing else.
    """
    plan = tmp_path / 'plan.json'
    hosts = ['ops@direct.example', 'ops@inner.example']
    grants = [{'host': host, 'action': 'ops.config', 'subject': c * 64} for host, c in zip(hosts, 'ab', strict=True)]
    plan.write_text(json.dumps({'hosts': hosts, 'grants': grants}), encoding='utf-8')
    table = {'jump': {'ops@inner.example': 'ops@bastion.example'}}

    def opened(declared: dict[str, object]) -> dict[str, tuple[str, ...]]:
        seen: dict[str, tuple[str, ...]] = {}
        sshholdplan.open_planned(
            1, CODE, plan, 'abc', grant=lambda *_a: [], routes=lambda dest: sshhold.route(dest, table=declared),
            opener=lambda dest, *_a, ssh: seen.setdefault(dest, ssh) and f'{dest}: open', held=lambda _d: False,
        )  # fmt: skip
        return seen

    assert opened(table) == {hosts[0]: ('ssh',), hosts[1]: ('ssh', '-J', 'ops@bastion.example')}
    assert opened({}) == {hosts[0]: ('ssh',), hosts[1]: ('ssh',)}
    assert sshhold.route(hosts[1], 'ops@flag.example', table) == ('ssh', '-J', 'ops@bastion.example'), 'declared wins'
    assert sshhold.route(hosts[0], 'ops@flag.example', table) == ('ssh', '-J', 'ops@flag.example')


def test_a_runs_stdin_rides_heredoc_data_and_the_audit_keeps_only_its_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = b'bot-token-PLANTED-9c1e\nno trailing newline'
    sent: list[str] = []
    monkeypatch.setattr(
        sshholdrun, '_exchange', lambda _d, command, _t: sent.append(command) or {'output': '', 'status': 0}
    )
    assert sshholdrun.run_command('ops@fake', 'sudo -n place', stdin=secret) == ('', 0)
    script = sent[0]
    head, data, end = script.split('\n', 2)[0], script.split('\n')[1:-1], script.split('\n')[-1]
    assert head == f"base64 -d <<'{end}' | {{ sudo -n place; }}"  # the data is heredoc DATA, never the command line
    assert base64.b64decode(''.join(data)) == secret  # exact bytes, no added newline
    line = json.loads(sshholdstate.audit_path().read_text(encoding='utf-8').splitlines()[-1])
    assert line['command'] == 'sudo -n place'
    assert line['stdin_sha256'] == hashlib.sha256(secret).hexdigest()[:12]
    assert b'PLANTED' not in sshholdstate.audit_path().read_bytes()
    assert 'PLANTED' not in script  # base64: not even the plain text rides the stream


def test_no_held_session_names_the_door_for_each_host_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """User ruling 2026-11-11: a key-only host never needs a code, so the refusal names both doors."""
    monkeypatch.setattr(sshholdwire, 'read_session', lambda _dest: None)
    with pytest.raises(HoldRefused) as refused:
        sshhold.close_session('alice@hpclogin01.example.org')
    text = str(refused.value)
    assert 'key-only' in text
    assert 'python -m lab_commons.hpc' in text
    assert 'sshhold open alice@hpclogin01.example.org --hours N --code <code>' in text
    assert 'the code the user gives' not in text


def test_a_plan_naming_an_action_this_client_lacks_is_refused_before_the_code_is_sent(tmp_path) -> None:
    plan = tmp_path / 'plan.json'
    unknown = {'host': 'ops@h', 'action': 'ops.not.yet.known', 'subject': 'c'}
    plan.write_text(json.dumps({'hosts': ['ops@h'], 'grants': [unknown]}))
    sent: list[str] = []
    with pytest.raises(sshholdwire.HoldRefused, match='not a consent action; the registered ones are'):
        sshholdplan.open_planned(
            1, CODE, plan, 'abc', grant=lambda *_a: sent.append('granted') or [], routes=sshhold.route, opener=str
        )
    assert sent == []


def test_a_holder_busy_with_a_long_run_still_answers_and_is_never_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    """A holder running one long command still answers a ping, so it is never read as dead.

    Measured 2026-11-20 (twice): a deploy rode the held session for minutes; meanwhile every ping -- the fleet's
    ``held``, ``sshhold status`` -- waited behind it, timed out, and ``status`` then DELETED the live session's
    state: the holder lived on, unreachable, and the next door read it as gone. PLANTED CONTROL: once closed,
    the ping is refused.
    """
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    dest = 'ops@fake-busy'
    sshhold.open_session(dest, 1.0, CODE, ssh=FAKE)
    slow = f'echo busy&& "{sys.executable}" -c "import time; time.sleep(9)"'
    running = threading.Thread(target=lambda: sshholdrun.run_command(dest, slow, timeout_s=60), daemon=True)
    try:
        running.start()
        time.sleep(2)  # the run is in flight
        session = sshholdstate.read_session(dest)
        assert session is not None
        assert running.is_alive(), 'the long run is still in flight'
        assert sshholdwire.ping(session), 'a busy holder answers'
        assert any(dest in line and 'left' in line for line in sshhold.status_lines())
        assert sshholdstate.read_session(dest) is not None, 'status never forgets a live, busy holder'
        running.join(30)
    finally:
        sshhold.close_session(dest)
    assert not sshholdwire.ping(session)


def test_a_command_that_reads_stdin_never_swallows_the_next_frame() -> None:
    """The held shell reads its commands from stdin, so a command must never read that stream.

    Measured 2026-11-20 (Cirrus): a placement's remote step read stdin -- the held ``bash -s`` stream -- and ate every
    later frame and its marker; the session hung until its timeout closed it. A frame without data runs with stdin
    from /dev/null. PLANTED CONTROL: data sent as a frame's stdin still reaches the command.
    """
    bash = shutil.which('bash')
    assert bash, 'the held remote shell is bash'
    stream = sshholdwire.frame('cat', 'one') + sshholdwire.frame('echo second', 'two')
    done = subprocess.run([bash, '--noprofile', '--norc', '-s'], input=stream, capture_output=True, text=True,
                          encoding='utf-8', timeout=30, check=False)  # fmt: skip
    assert sshholdwire.split_marker(done.stdout.split('__SSHHOLD_one_0\n', 1)[1], 'two') == ('second\n', 0)
    fed = sshholdrun.stdin_script('cat', b'data-line\n', '__END_X')
    piped = subprocess.run([bash, '--noprofile', '--norc', '-s'], input=sshholdwire.frame(fed, 'three'),
                           capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)  # fmt: skip
    assert sshholdwire.split_marker(piped.stdout, 'three') == ('data-line\n', 0)


def test_a_compound_command_reads_all_of_its_stdin_through_the_held_shell() -> None:
    """The heredoc pipes into the WHOLE command, not only its first simple command.

    Measured 2026-11-20 (Cirrus): the placement's ``umask 077 && IFS= read -r line && printf ...`` piped only into
    ``umask``; ``read`` read the session's own stream (swallowing frames), then, with stdin /dev/null, nothing --
    exit 1 with no output. PLANTED CONTROL: a single simple command still reads its data.
    """
    bash = shutil.which('bash')
    assert bash, 'the held remote shell is bash'

    def held(command: str, data: bytes) -> tuple[str, int] | None:
        framed = sshholdwire.frame(sshholdrun.stdin_script(command, data, '__END_Y'), 'n')
        done = subprocess.run([bash, '--noprofile', '--norc', '-s'], input=framed, capture_output=True, text=True,
                              encoding='utf-8', timeout=30, check=False)  # fmt: skip
        return sshholdwire.split_marker(done.stdout, 'n')

    assert held('umask 077 && IFS= read -r line && printf "%s\n" "$line"', b'secret-line\n') == ('secret-line\n', 0)
    assert held('cat', b'one\n') == ('one\n', 0)


def test_a_failed_held_command_names_itself_and_says_when_it_printed_nothing() -> None:
    """``exited 1:`` and nothing else teaches nothing; the refusal names the command and its empty output."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(transport.sshholdrun, 'run_command', lambda *_a, **_k: ('', 1))
        with pytest.raises(RuntimeError) as refused:
            transport._held_runner('u@h', 5)('umask 077 && IFS= read -r line', None)
    said = str(refused.value)
    assert 'exited 1' in said
    assert 'umask 077 && IFS= read -r line' in said
    assert '(no output)' in said


def test_a_dest_without_its_user_is_refused_before_the_code_is_spent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dest names its account; without one nothing is opened and no code is read.

    Measured 2026-11-20: ``open login.cirrus...`` logged in as the LOCAL user, the key was refused, and the user's one
    TOTP code was spent on it. PLANTED CONTROL: the same host with its user reaches the opener.
    """
    opened: list[str] = []
    monkeypatch.setattr(sshhold, 'open_session', lambda dest, *_a, **_k: opened.append(dest) or f'{dest}: open')
    monkeypatch.setattr(sshhold, 'given_code', lambda _code: pytest.fail('the code must not be read'))
    assert sshhold.main(['open', 'login.example', '--hours', '1']) == 2
    assert '<user>@login.example' in capsys.readouterr().err
    assert opened == []
    monkeypatch.setattr(sshhold, 'given_code', lambda code: code or '1')
    monkeypatch.setattr(sshholdprobe, 'probe', lambda _dest, _ssh: 'proven')
    assert sshhold.main(['open', 'alice@login.example', '--hours', '1', '--code', '1']) == 0
    assert opened == ['alice@login.example']


def test_a_frame_leaves_no_state_in_the_held_shell_for_the_next_one() -> None:
    """Each held command runs in its own subshell: an ``export`` or ``cd`` never outlives it.

    Measured 2026-11-20 (Cirrus): the credential placement's verify step exported GIT_CONFIG_COUNT/KEY/VALUE (helper
    reset to the staged file) into the held ``bash -s``; every later command in the session -- the deploy's fetches
    -- ran with the helper emptied and failed "could not read Username". PLANTED CONTROL: within one frame the
    export still applies.
    """
    bash = shutil.which('bash')
    assert bash, 'the held remote shell is bash'
    stream = sshholdwire.frame('export HELD_PROBE=leaked && echo "in:$HELD_PROBE"', 'a') + sshholdwire.frame(
        'echo "after:${HELD_PROBE:-clean}"', 'b'
    )
    done = subprocess.run([bash, '--noprofile', '--norc', '-s'], input=stream, capture_output=True, text=True,
                          encoding='utf-8', timeout=30, check=False)  # fmt: skip
    first, rest = done.stdout.split('__SSHHOLD_a_0\n', 1)
    assert first.strip() == 'in:leaked'
    assert sshholdwire.split_marker(rest, 'b') == ('after:clean\n', 0)
