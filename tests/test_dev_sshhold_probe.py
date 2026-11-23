"""THE KEY IS ASKED BEFORE THE CODE: a host that refuses this machine's public key spends no code.

Measured 2026-11-22: ``sshhold open <user@host>`` to a key + second-factor host read the user's code and spent it on
``Permission denied (publickey)`` -- the key had never been placed on the account. ssh says which half is missing
with no code at all: a BatchMode login ends ``(keyboard-interactive)`` when the key was accepted and ``(publickey)``
when it was not. The open probes that first; a plan's preflight reads the same line of its own key-only ssh.

PLANTED CONTROLS: a host that accepted the key and wants the code, and one ssh could not reach, both go on to the
open; a plan host that wants only the code is still offered.
"""

from __future__ import annotations

import subprocess

import pytest
from test_dev_planrun import PLAN, STEPS, FakeHost, secret_here

from dev_lab.dev import planrunpreflight, sshhold, sshholdprobe
from dev_lab.dev.sshholdwire import HoldRefused

__all__ = ['secret_here']

DEST = 'alice@login.example'
KEY_REFUSED = f'{DEST}: Permission denied (publickey).'
WANTS_CODE = f'{DEST}: Permission denied (keyboard-interactive).'
EITHER = f'{DEST}: Permission denied (publickey,keyboard-interactive).'
NO_ROUTE = 'ssh: connect to host login.example port 22: Connection timed out'


def _ssh(status: int, said: str, seen: list[list[str]] | None = None) -> sshholdprobe.Run:
    def run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        if seen is not None:
            seen.append(argv)
        return subprocess.CompletedProcess(argv, status, '', said)

    return run


@pytest.mark.parametrize(
    ('said', 'refused'),
    [(KEY_REFUSED, True), (WANTS_CODE, False), (EITHER, False), (NO_ROUTE, False), ('', False)],
)
def test_only_a_denial_that_offers_the_key_and_no_code_method_is_a_refused_key(said: str, *, refused: bool) -> None:
    assert bool(sshholdprobe.key_refused(said)) is refused


def test_the_probe_rides_the_opens_own_ssh_words_in_batch_mode_and_refuses_a_refused_key() -> None:
    seen: list[list[str]] = []
    route = ('ssh', '-J', 'alice@bastion.example', '-o', 'StrictHostKeyChecking=yes')
    with pytest.raises(HoldRefused, match='no code was read') as refused:
        sshholdprobe.probe(DEST, route, run=_ssh(255, KEY_REFUSED, seen))
    assert seen[0][: len(route)] == list(route)
    assert 'BatchMode=yes' in seen[0]
    assert seen[0][-2:] == [DEST, 'true']
    said = str(refused.value)
    assert 'Permission denied (publickey)' in said
    assert 'python -m dev_lab.dev.hpcaccount keys' in said
    assert 'portal' in said
    for status, answer in ((255, WANTS_CODE), (255, NO_ROUTE), (1, KEY_REFUSED)):  # the controls
        sshholdprobe.probe(DEST, route, run=_ssh(status, answer))


def test_a_key_only_host_is_refused_before_any_code_naming_its_read_door() -> None:
    """Measured 2026-11-23: an open on a KEY-ONLY account asked a code and died reading it (EOFError)."""
    with pytest.raises(HoldRefused, match='KEY-ONLY host needs no code') as refused:
        sshholdprobe.probe(DEST, ('ssh',), run=_ssh(0, ''))
    assert 'python -m dev_lab.dev.hpcaccount look --account' in str(refused.value)


def test_a_probe_that_cannot_run_leaves_the_open_to_say_what_ssh_says() -> None:
    def gone(_argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        msg = 'ssh'
        raise FileNotFoundError(msg)

    sshholdprobe.probe(DEST, ('ssh',), run=gone)


def test_open_reads_no_code_for_a_host_that_refuses_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: the same open against a host that wants the code reads it and opens."""
    opened: list[str] = []
    answer = [KEY_REFUSED]
    monkeypatch.setattr(sshhold, 'section', lambda _name: {})
    monkeypatch.setattr(sshhold, 'open_session', lambda dest, *_a, **_k: opened.append(dest) or f'{dest}: open')

    def answered(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        return _ssh(255, answer[0])(argv)

    monkeypatch.setattr(sshholdprobe._door, 'run', answered)
    monkeypatch.setattr(sshhold, 'given_code', lambda _code: pytest.fail('the code must not be read'))
    assert sshhold.main(['open', DEST, '--hours', '1', '--code', '123456']) == 2
    assert "does not admit this machine's public key" in capsys.readouterr().err
    assert opened == []
    answer[0] = WANTS_CODE
    monkeypatch.setattr(sshhold, 'given_code', lambda code: code)
    assert sshhold.main(['open', DEST, '--hours', '1', '--code', '123456']) == 0
    assert opened == [DEST]


def test_a_plan_host_that_refuses_the_key_is_blocked_and_one_that_wants_the_code_is_not() -> None:
    host = FakeHost()
    host.ready = (255, KEY_REFUSED)
    green, lines = planrunpreflight.preflight(PLAN, STEPS, lambda _dest: host)
    assert not green
    assert lines[0].startswith('host ')
    assert 'BLOCKED' in lines[0]
    assert 'its public key is refused' in lines[0]
    assert 'hpcaccount keys' in lines[0]
    waiting = FakeHost()  # the control: the key was accepted, the code is what opens it
    waiting.ready = (255, WANTS_CODE)
    _, said = planrunpreflight.preflight(PLAN, STEPS, lambda _dest: waiting)
    assert 'UNREACHABLE' in said[0]
    assert 'BLOCKED' not in said[0]
