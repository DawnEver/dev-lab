"""SSH-HOST-KEY-DECLARED: a declared endpoint's host key comes from its declaration, is checked strictly, never learned.

Measured 2026-11-20 on a new workstation: ``forge breakglass status`` and the consent door ssh'd to the declared
endpoints and died on a bare ``Host key verification failed`` -- no declaration of the server's host key existed,
the door passed no known_hosts, and the refusal named no door. Each refusal below names the rule, the declaration
and how to fill it; each has a planted control that passes.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.dev import remote
from dev_lab.ops.consent import door

HOST = 'forge.example'
TARGET = f'consent@{HOST}'
KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample'


def _recording(code: int = 0, err: str = '') -> tuple[list[tuple[list[str], str]], Callable[..., object]]:
    seen: list[tuple[list[str], str]] = []

    def run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        known = next((a.split('=', 1)[1] for a in argv if a.startswith('UserKnownHostsFile=')), '')
        seen.append((argv, Path(known).read_text(encoding='utf-8') if known else ''))
        return subprocess.CompletedProcess(argv, code, 'ok' if code == 0 else '', err)

    return seen, run


def test_a_declared_key_becomes_the_one_line_of_the_known_hosts_ssh_checks_strictly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen, run = _recording()
    monkeypatch.setattr(remote._door, 'run', run)
    assert remote.declared_piped(TARGET, '{}\n', identity=None, timeout_s=5, host_keys={HOST: KEY}) == (0, 'ok')
    ((argv, known),) = seen
    assert 'StrictHostKeyChecking=yes' in argv
    assert known == f'{HOST} {KEY}\n'


@pytest.mark.parametrize(
    ('declared', 'why'),
    [
        ({}, 'is not declared'),
        ({HOST: ''}, 'is not declared'),
        ({HOST: remote.HOST_KEY_UNFILLED}, 'placeholder'),
        ({HOST: 'AAAAC3Nz-no-type'}, 'is not a "<type> <base64>" key line'),
        ({'other.example': KEY}, 'is not declared'),
    ],
)
def test_a_missing_placeholder_or_malformed_key_is_refused_by_name_before_ssh_runs(
    monkeypatch: pytest.MonkeyPatch, declared: dict[str, str], why: str
) -> None:
    seen, run = _recording()
    monkeypatch.setattr(remote._door, 'run', run)
    with pytest.raises(remote.HostKeyUndeclared) as refused:
        remote.declared_piped(TARGET, '{}\n', identity=None, timeout_s=5, host_keys=declared)
    said = str(refused.value)
    assert said.startswith(remote.HOST_KEY_RULE)
    assert why in said
    assert remote.HOST_KEYS_DECLARATION in said
    assert 'never an ssh-keyscan' in said
    assert seen == []
    assert remote.host_key_line(TARGET, {HOST: KEY}) == f'{HOST} {KEY}'  # PLANTED CONTROL: a real key passes


def test_a_host_key_mismatch_is_named_with_its_rule_and_door(monkeypatch: pytest.MonkeyPatch) -> None:
    _seen, run = _recording(255, 'Host key verification failed.\n')
    monkeypatch.setattr(remote._door, 'run', run)
    status, said = remote.declared_piped(TARGET, '{}\n', identity=None, timeout_s=5, host_keys={HOST: KEY})
    assert status == 255
    assert f'{remote.HOST_KEY_RULE}: {HOST} presented a host key that is not the declared one' in said
    assert remote.HOST_KEYS_DECLARATION in said
    _seen, run = _recording(255, 'Connection timed out\n')  # PLANTED CONTROL: another failure is not a key wall
    monkeypatch.setattr(remote._door, 'run', run)
    assert remote.HOST_KEY_RULE not in remote.piped(TARGET, '{}\n', identity=None, timeout_s=5)[1]


def test_the_endpoint_door_checks_the_declaration_and_answers_a_placeholder_with_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen, run = _recording()
    monkeypatch.setattr(remote._door, 'run', run)
    declared = {'host_keys': {HOST: remote.HOST_KEY_UNFILLED}}
    monkeypatch.setattr(door, 'section', lambda name: declared if name == 'ssh' else {})
    status, said = door.ssh_send({'endpoint': TARGET}, {'verb': 'hello'})
    assert status == 255
    assert remote.HOST_KEY_RULE in said
    assert seen == []
    declared['host_keys'][HOST] = KEY  # PLANTED CONTROL: the filled declaration reaches ssh, strictly
    assert door.ssh_send({'endpoint': TARGET}, {'verb': 'hello'}) == (0, 'ok')
    assert seen[-1][1] == f'{HOST} {KEY}\n'


def test_a_host_tables_own_known_hosts_file_is_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A server's root door names its own file ([ops.consent_client] known_hosts); that option stays."""
    own = tmp_path / 'kh'
    own.write_text(f'{HOST} {KEY}\n', encoding='utf-8')
    seen, run = _recording()
    monkeypatch.setattr(remote._door, 'run', run)
    monkeypatch.setattr(door, 'section', lambda _name: {})
    assert door.ssh_send({'endpoint': TARGET, 'known_hosts': str(own)}, {'verb': 'hello'}) == (0, 'ok')
    assert f'UserKnownHostsFile={own}' in seen[0][0]
