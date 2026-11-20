"""hpcaccount's one transport: a live held session carries every step; none is key-only ssh; a dead one is refused."""

from __future__ import annotations

import io
from typing import Any

import pytest
from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpcaccount import transport
from dev_lab.dev.sshholdstate import Session

_DEST = 'alice@login01.example'
_GRANT = Grant(user='alice', hosts=('login01.example', 'login02.example'), slurm_account='acct')


def _hold(monkeypatch: pytest.MonkeyPatch, *, recorded: set[str], alive: bool) -> list[tuple[str, str, Any]]:
    """Record a session for each of *recorded*; every held ``run`` lands in the returned list, every ssh refuses."""
    ran: list[tuple[str, str, Any]] = []
    monkeypatch.setattr(
        transport.sshholdstate,
        'read_session',
        lambda dest: Session(dest, 1, 2, 'tok', 0.0, 1e12) if dest in recorded else None,
    )
    monkeypatch.setattr(transport.sshholdwire, 'ping', lambda _session: alive)

    def run_command(dest: str, command: str, _timeout: float = 0, *, stdin: bytes | None = None) -> tuple[str, int]:
        ran.append((dest, command, stdin))
        return 'held-out', 0

    monkeypatch.setattr(transport.sshholdrun, 'run_command', run_command)

    def no_ssh(*_a: object, **_k: object) -> object:
        msg = 'ssh must not be opened here'
        raise AssertionError(msg)

    monkeypatch.setattr(transport, 'ssh_runner', no_ssh)
    monkeypatch.setattr(transport.remote, 'detached', no_ssh)
    return ran


def test_a_live_held_session_carries_every_read(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = _hold(monkeypatch, recorded={'alice@login02.example'}, alive=True)
    assert transport.grant_runner(_GRANT)('hostname', 'in') == 'held-out'
    assert transport.host_runner('alice@login02.example')('crontab -l') == 'held-out'
    assert ran == [('alice@login02.example', 'hostname', b'in'), ('alice@login02.example', 'crontab -l', None)]


def test_a_live_held_session_carries_the_deploy(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = _hold(monkeypatch, recorded={_DEST}, alive=True)
    log = io.StringIO()
    assert transport.start(_DEST, 'deploy', log) == 0
    assert ran == [(_DEST, 'deploy', None)]
    assert 'held-out' in log.getvalue()
    assert transport.describe(_DEST, 'deploy').startswith('held session')


def test_a_held_step_that_fails_raises_its_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _hold(monkeypatch, recorded={_DEST}, alive=True)
    monkeypatch.setattr(transport.sshholdrun, 'run_command', lambda *_a, **_k: ('nope', 3))
    with pytest.raises(RuntimeError, match='exited 3 running `false`: nope'):
        transport.host_runner(_DEST)('false')


def test_a_dead_holder_is_refused_by_name_never_re_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: a recorded session whose holder is silent neither runs nor falls back to ssh."""
    ran = _hold(monkeypatch, recorded={_DEST}, alive=False)
    for step in (lambda: transport.grant_runner(_GRANT), lambda: transport.start(_DEST, 'x', io.StringIO())):
        with pytest.raises(transport.HoldRefused, match=r'does not answer.*sshhold open alice@login01\.example'):
            step()
    assert ran == []


def test_no_held_session_is_key_only_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: with no session recorded nothing goes through the holder."""
    ran = _hold(monkeypatch, recorded=set(), alive=True)
    opened: list[str] = []

    def ssh(dest: str, _timeout: float) -> Runner:
        return lambda _command, _stdin=None: opened.append(dest) or 'ssh-out'

    monkeypatch.setattr(transport, 'ssh_runner', ssh)
    started: list[list[str]] = []
    monkeypatch.setattr(transport.remote, 'detached', lambda argv, _log: started.append(list(argv)))
    assert transport.grant_runner(_GRANT)('hostname') == 'ssh-out'
    transport.start(_DEST, 'deploy', io.StringIO())
    assert opened == ['alice@login01.example']
    assert started[0][:3] == ['ssh', '-o', 'BatchMode=yes']
    assert started[0][-2] == _DEST
    assert ran == []


def _ssh_failing(monkeypatch: pytest.MonkeyPatch, said: str) -> None:
    def failing(_dest: str, _timeout: float) -> Runner:
        def run(_command: str, _stdin: str | None = None) -> str:
            raise RuntimeError(said)

        return run

    monkeypatch.setattr(transport, 'ssh_runner', failing)


def test_a_second_factor_host_with_no_session_names_the_door(monkeypatch: pytest.MonkeyPatch) -> None:
    _hold(monkeypatch, recorded=set(), alive=True)
    _ssh_failing(monkeypatch, f'ssh could not reach {_DEST}: Permission denied (keyboard-interactive).')
    with pytest.raises(transport.HoldRefused) as refused:
        transport.grant_runner(_GRANT)('hostname')
    door = "open it first: python -m dev_lab.dev.sshhold open alice@login01.example --hours H (the user's code)"
    assert door in str(refused.value)


def test_any_other_ssh_failure_is_not_dressed_as_a_second_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the door is named only for the keyboard-interactive refusal."""
    _hold(monkeypatch, recorded=set(), alive=True)
    _ssh_failing(monkeypatch, 'ssh exited 1: no such file')
    with pytest.raises(RuntimeError) as failed:
        transport.host_runner(_DEST)('ls')
    assert not isinstance(failed.value, transport.HoldRefused)


def test_the_named_login_host_is_tried_first_and_a_failover_host_is_probed_briefly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured 2026-11-20: a credential for ``user@login02`` waited out 300 s on login01 before failing over.

    The host the dest names leads; a host failed over TO answers a :data:`transport.PROBE_S` probe first.
    PLANTED CONTROL: with no host named the declared order stands.
    """
    _hold(monkeypatch, recorded=set(), alive=True)
    opened: list[tuple[str, float, str]] = []

    def ssh(dest: str, timeout: float) -> Runner:
        def run(command: str, _stdin: str | None = None) -> str:
            opened.append((dest, timeout, command))
            if dest == 'alice@login02.example':
                said = 'down'
                raise transport.Unreachable(said)
            return 'out'

        return run

    monkeypatch.setattr(transport, 'ssh_runner', ssh)
    assert transport.ordered_targets(_GRANT, 'alice@login02') == ('alice@login02.example', 'alice@login01.example')
    assert transport.ordered_targets(_GRANT) == _GRANT.targets
    assert transport.grant_runner(_GRANT, first='alice@login02')('hostname') == 'out'
    assert opened == [
        ('alice@login02.example', 300.0, 'hostname'),
        ('alice@login01.example', transport.PROBE_S, 'true'),
        ('alice@login01.example', 300.0, 'hostname'),
    ]
    assert transport.PROBE_S < 60
