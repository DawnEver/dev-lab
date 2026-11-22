"""SSH-HOST-KEY-DECLARED on the plan doors: a plan host and a held session check the DECLARED host key, by name.

Measured 2026-11-22 on a new workstation: ``planrun preflight`` said ``host ops@<forge>: UNREACHABLE (Host key
verification failed.)`` while the consent issuer door to the SAME host was green -- the plan's ssh passed no
declared key, so it fell back to a known_hosts this machine never filled, and the line named no door. The plan
remote and the hold now resolve the key through :func:`dev_lab.dev.remote.host_key_options`, the one resolver.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.dev import planremote, planrunpreflight, planrunsteps, remote, sshhold, sshholdwire
from dev_lab.ops.consent.plan import parsed

HOST = 'forge.example'
DEST = f'ops@{HOST}'
KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample'
MISMATCH = 'Host key verification failed.\n'


def _recording(code: int = 0, err: bytes = b'') -> tuple[list[tuple[list[str], str]], Callable[..., object]]:
    seen: list[tuple[list[str], str]] = []

    def run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[bytes]:
        known = next((a.split('=', 1)[1] for a in argv if a.startswith('UserKnownHostsFile=')), '')
        seen.append((argv, Path(known).read_text(encoding='utf-8') if known else ''))
        return subprocess.CompletedProcess(argv, code, b'', err)

    return seen, run


def _declare(monkeypatch: pytest.MonkeyPatch, keys: dict[str, str]) -> None:
    monkeypatch.setattr(remote, 'section', lambda name: {'host_keys': keys} if name == 'ssh' else {})


def test_a_plan_host_is_checked_strictly_against_its_declared_key_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    seen, run = _recording()
    monkeypatch.setattr(planremote._door, 'run', run)
    _declare(monkeypatch, {HOST: KEY})
    assert planremote.SshRemote(DEST).run('true') == ('', 0)
    ((argv, known),) = seen
    assert 'StrictHostKeyChecking=yes' in argv
    assert known == f'{HOST} {KEY}\n'


def test_an_undeclared_plan_host_is_refused_before_ssh_runs_naming_the_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PLANTED CONTROL of the test above: the same call with no declaration never reaches ssh."""
    seen, run = _recording()
    monkeypatch.setattr(planremote._door, 'run', run)
    _declare(monkeypatch, {'other.example': KEY})
    with pytest.raises(sshholdwire.HoldRefused) as refused:
        planremote.SshRemote(DEST).run('true')
    assert seen == []
    said = str(refused.value)
    assert remote.HOST_KEY_RULE in said
    assert f'{remote.HOST_KEYS_DECLARATION} "{HOST}"' in said
    with pytest.raises(sshholdwire.HoldRefused, match=remote.HOST_KEY_RULE):
        planremote.SshRemote(DEST).put('/srv/x', 'text')
    assert seen == []


def test_a_presented_key_that_is_not_the_declared_one_is_named_with_its_door(monkeypatch: pytest.MonkeyPatch) -> None:
    _seen, run = _recording(255, MISMATCH.encode())
    monkeypatch.setattr(planremote._door, 'run', run)
    _declare(monkeypatch, {HOST: KEY})
    said, status = planremote.SshRemote(DEST).run('true')
    assert status == 255
    assert remote.HOST_KEY_RULE in said
    assert remote.HOST_KEYS_DECLARATION in said
    _seen, run = _recording(255, b'Connection timed out\n')  # PLANTED CONTROL: another failure is not a key wall
    monkeypatch.setattr(planremote._door, 'run', run)
    assert remote.HOST_KEY_RULE not in planremote.SshRemote(DEST).run('true')[0]


PLAN = parsed({'hosts': [DEST], 'grants': [{'host': DEST, 'action': 'ops.config', 'subject': 'a' * 64}]})
STEPS = planrunsteps.Steps((
    planrunsteps.Step(('config', 'apply', '--from', '/srv/c.toml'), DEST, '/etc/dev-lab/s.toml', '/usr/bin/python3'),
))  # fmt: skip


class _Wall:
    """A host that answers every command with one ssh failure, or refuses before ssh."""

    def __init__(self, said: str, *, raises: bool = False) -> None:
        self.said, self.raises = said, raises

    def run(self, _command: str, _stdin: bytes | None = None) -> tuple[str, int]:
        if self.raises:
            raise sshholdwire.HoldRefused(self.said)
        return self.said, 255

    def put(self, _path: str, _text: str) -> None:
        raise AssertionError


def _host_line(wall: _Wall) -> tuple[bool, str]:
    green, lines = planrunpreflight.preflight(PLAN, STEPS, lambda _dest: wall, machine=lambda _table: {})
    return green, next(line for line in lines if line.startswith(f'host {DEST}:'))


@pytest.mark.parametrize('raises', [False, True])
def test_a_host_key_wall_blocks_the_preflight_before_a_code_and_names_its_door(*, raises: bool) -> None:
    """A code spent on a host whose key cannot be checked is lost: the preflight is not green, and says why."""
    said = remote.named(DEST, MISMATCH) if not raises else f'{remote.HOST_KEY_RULE}: the ssh host key of {HOST} ...'
    green, line = _host_line(_Wall(said, raises=raises))
    assert not green
    assert line.startswith(f'host {DEST}: BLOCKED -- ')
    assert remote.HOST_KEY_RULE in line


def test_a_host_that_only_needs_a_hold_stays_unreachable_and_does_not_block() -> None:
    """PLANTED CONTROL: a second-factor refusal is the ordinary no-hold case, not a key wall."""
    _green, line = _host_line(_Wall(f'{DEST}: Permission denied (keyboard-interactive).\n'))
    assert line.startswith(f'host {DEST}: UNREACHABLE (')
    assert remote.HOST_KEY_RULE not in line


def test_the_hold_opens_a_declared_host_on_its_declared_key_and_an_undeclared_one_plainly() -> None:
    table = {'jump': {DEST: 'ops@bastion.example'}, 'host_keys': {HOST: KEY}}
    words = sshhold.route(DEST, table=table)
    assert words[:3] == ('ssh', '-J', 'ops@bastion.example')
    assert 'StrictHostKeyChecking=yes' in words
    known = next(w.split('=', 1)[1] for w in words if w.startswith('UserKnownHostsFile='))
    assert Path(known).read_text(encoding='utf-8') == f'{HOST} {KEY}\n'
    assert sshhold.route('dev@cluster.example', table=table) == ('ssh',)  # PLANTED CONTROL: undeclared, ssh's default
    with pytest.raises(sshholdwire.HoldRefused, match=remote.HOST_KEY_RULE):
        sshhold.route(DEST, table={'host_keys': {HOST: remote.HOST_KEY_UNFILLED}})
