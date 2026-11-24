"""The preflight of a code: nothing asks the user for a code before the call carrying it is proven able to succeed.

Measured 2026-11-20: (a) ``breakglass open --code`` met an issuer with no version handshake, (b) the transport
said "Host key verification failed" (the workstation was never enrolled), (c) an hpc session request named a task
identity that changed minutes later. Each refusal below has its planted control: the same call, the fault removed,
passes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, RFC_KEY, code
from lab_commons.home import HOME_ENV
from test_ops_consent_door import Wire

from dev_lab.dev.forgebreakglass import wave_main
from dev_lab.ops.consent import __main__ as consent_main
from dev_lab.ops.consent.client import grant, preflight
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.door import (
    PREFLIGHT_DOOR,
    RECEIPT_FRESH_S,
    Send,
    fresh_receipts,
    receipt_path,
    require_receipt,
)
from dev_lab.ops.consent.issuer import Issuer, keygen

WAVE = {'action': 'breakglass.wave', 'subject': 'w', 'params': {'hours': 1, 'max_merges': 1}}


@pytest.fixture
def issuer(tmp_path: Path) -> Issuer:
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'consent.key')
    return Issuer(tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test issuer', lambda: NOW)


@pytest.fixture
def table(issuer: Issuer) -> dict[str, Any]:
    return {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}


def _request(tmp_path: Path, request: dict[str, Any] = WAVE) -> Path:
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request), encoding='utf-8')
    return path


def test_a_green_preflight_writes_a_receipt_keyed_by_action_and_subject(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    written = preflight(WAVE, table=table, send=Wire(issuer), home=tmp_path, now=NOW)
    assert written == receipt_path('breakglass.wave', 'w', home=tmp_path)
    assert json.loads(written.read_text(encoding='utf-8')) == {'action': 'breakglass.wave', 'subject': 'w', 'at': NOW}
    require_receipt(WAVE, home=tmp_path, now=NOW + 1)  # the control of every refusal below
    assert receipt_path('breakglass.wave', 'other', home=tmp_path) != written


def test_a_code_given_without_a_fresh_receipt_is_refused_before_any_network_call(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    """The wall names its door. PLANTED CONTROL: the same grant after a green preflight is issued."""
    wire = Wire(issuer)
    with pytest.raises(ConsentRefused, match='no fresh preflight') as refused:
        grant(_request(tmp_path), table=table, code=code(0), tty=False, send=wire, home=tmp_path, now=lambda: NOW)
    assert PREFLIGHT_DOOR in str(refused.value)
    assert wire.sent == []
    preflight(WAVE, table=table, send=wire, home=tmp_path, now=NOW - RECEIPT_FRESH_S - 1)
    with pytest.raises(ConsentRefused, match='s old'):
        grant(_request(tmp_path), table=table, code=code(0), tty=False, send=wire, home=tmp_path, now=lambda: NOW)
    assert wire.sent == ['hello']  # the stale preflight's own handshake only
    preflight(WAVE, table=table, send=wire, home=tmp_path, now=NOW)
    written = grant(_request(tmp_path), table=table, code=code(0), tty=False, send=wire, home=tmp_path,
                    now=lambda: NOW)  # fmt: skip
    assert json.loads(written.read_text(encoding='utf-8'))['action'] == 'breakglass.wave'


def test_a_receipt_for_another_subject_does_not_admit_the_code(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    preflight(WAVE | {'subject': 'another'}, table=table, send=Wire(issuer), home=tmp_path, now=NOW)
    with pytest.raises(ConsentRefused, match='no fresh preflight'):
        require_receipt(WAVE, home=tmp_path, now=NOW)


def test_a_prompt_at_a_terminal_follows_an_inline_preflight(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    """The code typed AFTER the check needs no receipt: the grant runs the preflight before it prompts."""
    asked: list[str] = []
    wire = Wire(issuer)
    grant(_request(tmp_path), table=table, tty=True, ask=lambda p: asked.append(p) or code(0), send=wire,
          home=tmp_path, now=lambda: NOW)  # fmt: skip
    assert asked
    assert wire.sent[0] == 'hello'


@pytest.mark.parametrize(
    ('said', 'door'),
    [
        ('Host key verification failed.', 'devhost enroll'),  # incident (b): the workstation was never enrolled
        ('ssh: connect to host forge port 22: Connection timed out', 'unreachable over ssh'),
    ],
)
def test_an_unreachable_issuer_is_named_by_its_transport_not_as_an_old_version(
    table: dict[str, Any], tmp_path: Path, said: str, door: str
) -> None:
    """Incident (a) read 255 as "no version handshake". PLANTED CONTROL: the green preflight above."""
    with pytest.raises(ConsentRefused, match='no code asked') as refused:
        preflight(WAVE, table=table, send=lambda _t, _r: (255, said), home=tmp_path, now=NOW)
    assert door in str(refused.value)
    assert 'version handshake' not in str(refused.value)
    assert not receipt_path('breakglass.wave', 'w', home=tmp_path).exists()


def test_a_stale_subject_is_refused_naming_how_to_write_the_request_again(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    """Incident (c). PLANTED CONTROL: the current subject is admitted."""
    task = {'action': 'task.integrator', 'subject': 'toolchain@old', 'ttl': 3600}
    subjects = {'task.integrator': lambda s: '' if s == 'toolchain@new' else f'{s} is not the open task toolchain@new'}
    with pytest.raises(ConsentRefused, match='not the open task'):
        preflight(task, table=table, send=Wire(issuer), subjects=subjects, home=tmp_path, now=NOW)
    preflight(task | {'subject': 'toolchain@new'}, table=table, send=Wire(issuer), subjects=subjects, home=tmp_path,
              now=NOW)  # fmt: skip


def test_an_action_check_that_fails_writes_no_receipt(issuer: Issuer, table: dict[str, Any], tmp_path: Path) -> None:
    def down() -> None:
        msg = 'the break-glass server does not answer'
        raise ConsentRefused(msg)

    with pytest.raises(ConsentRefused, match='break-glass server'):
        preflight(WAVE, table=table, send=Wire(issuer), checks=[down], home=tmp_path, now=NOW)
    assert fresh_receipts(home=tmp_path, now=NOW) == []
    preflight(WAVE, table=table, send=Wire(issuer), checks=[lambda: None], home=tmp_path, now=NOW)
    assert [found['action'] for found in fresh_receipts(home=tmp_path, now=NOW)] == ['breakglass.wave']


def test_consent_preflight_and_receipts_verbs(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    """``receipts`` is the narrow read a Stop hook uses: exit 0 with a fresh receipt, 1 naming the door without."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    assert consent_main.main(['receipts']) == 1
    assert PREFLIGHT_DOOR in capsys.readouterr().err
    assert consent_main.main(['preflight', str(_request(tmp_path))], table=table, send=Wire(issuer)) == 0
    assert consent_main.main(['receipts']) == 0
    assert 'breakglass.wave' in capsys.readouterr().out


def test_breakglass_open_preflight_checks_the_server_too(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Incident (b) was the break-glass server's host key. PLANTED CONTROL: a server that answers is green."""
    argv = ['open', '--preflight', '--hours', '1', '--max-merges', '1']
    server = {'endpoint': 'bg@forge'}

    def unknown_host(_t: object, _r: object) -> tuple[int, str]:
        return 255, 'Host key verification failed.'

    def run(send: Send) -> int:
        return wave_main(
            argv,
            table=server,
            send=send,
            home=tmp_path,
            preflight_=lambda request, **kw: preflight(request, table=table, send=Wire(issuer), **kw),
        )

    assert run(unknown_host) == 2
    assert 'devhost enroll' in capsys.readouterr().err
    assert fresh_receipts(home=tmp_path) == []
    assert run(lambda _t, _r: (0, 'no wave open')) == 0
    assert 'ask the user for the code' in capsys.readouterr().out
