"""THE KEY IS ASKED BEFORE THE CODE: a host that refuses this machine's public key spends no code.

Measured 2026-11-22: ``sshhold open <user@host>`` to a key + second-factor host read the user's code and spent it on
``Permission denied (publickey)`` -- the key had never been placed on the account. ssh says which half is missing
with no code at all: a BatchMode login ends ``(keyboard-interactive)`` when the key was accepted and ``(publickey)``
when it was not. The open probes that first; a plan's preflight reads the same line of its own key-only ssh.

Measured 2026-11-24 on Cirrus: three codes were read after the probe let an empty ``Permission denied ()`` pass.
The probe now PROVES ``Authenticated using "publickey" with partial success`` for the destination itself
(``ssh -v``) and refuses everything short of it, naming the identity ssh offered and SAFE.

PLANTED CONTROLS: a host that proves partial success goes on to the open; a bastion's proof alone does not; a plan
host that wants only the code is still offered.
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
IDENTITY = '~/.ssh/id_ed25519'
#: What ``ssh -v`` says when the key was accepted and the code is what is missing (measured on Cirrus 2026-11-24).
PROVEN = (
    "debug1: Authenticating to login.example:22 as 'alice'\n"
    f'debug1: Will attempt key: {IDENTITY} ED25519 SHA256:abc\n'
    f'debug1: Offering public key: {IDENTITY} ED25519 SHA256:abc\n'
    'Authenticated using "publickey" with partial success.\n'
    'debug1: Authentications that can continue: keyboard-interactive\n'
    f'{WANTS_CODE}\n'
)
#: The key offered, the server says no more than an empty list -- no partial success.
UNPROVEN = (
    "debug1: Authenticating to login.example:22 as 'alice'\n"
    f'debug1: Offering public key: {IDENTITY} ED25519 SHA256:abc\n'
    f'{DEST}: Permission denied ().\n'
)
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


def test_the_probe_rides_the_opens_own_ssh_words_verbose_in_batch_mode_and_passes_on_proven_partial_success() -> None:
    seen: list[list[str]] = []
    route = ('ssh', '-J', 'alice@bastion.example', '-o', 'StrictHostKeyChecking=yes')
    assert IDENTITY in sshholdprobe.probe(DEST, route, run=_ssh(255, PROVEN, seen))
    assert seen[0][1 : len(route)] == list(route[1:])  # [0] is PATH's ssh: test_dev_sshhold_program
    assert {'-v', 'BatchMode=yes'} <= set(seen[0])
    assert seen[0][-2:] == [DEST, 'true']


@pytest.mark.parametrize(
    ('status', 'said', 'cause'),
    [
        (255, KEY_REFUSED, 'Permission denied (publickey)'),
        (255, UNPROVEN, 'Permission denied ()'),  # measured on Cirrus 2026-11-24: the empty list passed the old probe
        (255, WANTS_CODE, 'Permission denied (keyboard-interactive)'),  # no partial success proven: not enough
        (255, NO_ROUTE, 'Connection timed out'),
        (1, '', 'no denial line'),
    ],
)
def test_anything_short_of_proven_partial_success_refuses_before_the_code(status: int, said: str, cause: str) -> None:
    with pytest.raises(HoldRefused, match='no code was read') as refused:
        sshholdprobe.probe(DEST, ('ssh',), run=_ssh(status, said))
    text = str(refused.value)
    assert cause in text
    assert 'SAFE' in text
    assert 'publickey partial success' in text


def test_the_refusal_names_the_identity_ssh_offered_and_never_its_fingerprint() -> None:
    with pytest.raises(HoldRefused) as refused:
        sshholdprobe.probe(DEST, ('ssh',), run=_ssh(255, UNPROVEN))
    assert IDENTITY in str(refused.value)
    assert 'SHA256' not in str(refused.value)


def test_partial_success_of_a_bastion_alone_proves_nothing() -> None:
    bastion = (
        "debug1: Authenticating to bastion.example:22 as 'alice'\n"
        'Authenticated using "publickey" with partial success.\n'
    )
    with pytest.raises(HoldRefused):
        sshholdprobe.probe(DEST, ('ssh',), run=_ssh(255, bastion + UNPROVEN))
    assert sshholdprobe.probe(DEST, ('ssh',), run=_ssh(255, bastion + PROVEN))  # control: the dest's own proof


def test_a_key_only_host_is_refused_before_any_code_naming_its_read_door() -> None:
    """Measured 2026-11-23: an open on a KEY-ONLY account asked a code and died reading it (EOFError)."""
    with pytest.raises(HoldRefused, match='KEY-ONLY host needs no code') as refused:
        sshholdprobe.probe(DEST, ('ssh',), run=_ssh(0, ''))
    assert 'python -m dev_lab.dev.hpcaccount look --account' in str(refused.value)


def test_a_probe_that_cannot_run_refuses_rather_than_spend_a_code() -> None:
    def gone(_argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        msg = 'ssh'
        raise FileNotFoundError(msg)

    with pytest.raises(HoldRefused, match='no code was read'):
        sshholdprobe.probe(DEST, ('ssh',), run=gone)


def test_open_reads_no_code_until_partial_success_is_proven(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: the same open against a host that proves partial success reads the code and opens."""
    opened: list[str] = []
    answer = [UNPROVEN]
    monkeypatch.setattr(sshhold, 'section', lambda _name: {})
    monkeypatch.setattr(sshhold, 'open_session', lambda dest, *_a, **_k: opened.append(dest) or f'{dest}: open')

    def answered(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        return _ssh(255, answer[0])(argv)

    monkeypatch.setattr(sshholdprobe._door, 'run', answered)
    monkeypatch.setattr(sshhold, 'given_code', lambda _code: pytest.fail('the code must not be read'))
    assert sshhold.main(['open', DEST, '--hours', '1', '--code', '123456']) == 2
    assert 'publickey partial success' in capsys.readouterr().err
    assert opened == []
    answer[0] = PROVEN
    monkeypatch.setattr(sshhold, 'given_code', lambda code: code)
    assert sshhold.main(['open', DEST, '--hours', '1', '--code', '123456']) == 0
    assert opened == [DEST]


def test_the_probe_verb_reads_no_code_and_says_the_proof(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sshhold, 'section', lambda _name: {})
    monkeypatch.setattr(sshholdprobe._door, 'run', _ssh(255, PROVEN))
    monkeypatch.setattr(sshhold, 'given_code', lambda _code: pytest.fail('probe reads no code'))
    assert sshhold.main(['probe', DEST]) == 0
    assert IDENTITY in capsys.readouterr().out
    monkeypatch.setattr(sshholdprobe._door, 'run', _ssh(255, UNPROVEN))
    assert sshhold.main(['probe', DEST]) == 2


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
