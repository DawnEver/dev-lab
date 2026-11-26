"""A CODE GIVEN IN ADVANCE IS THE FIRST REQUEST: no network round trip runs between the call and the code.

Measured 2026-11-26: ``forge breakglass open --preflight`` took 30 s, and ``open --code`` re-ran the issuer
preflight before it sent the code -- four TOTP codes in a row arrived outside their 30 s step and were refused,
with the clock within 2 s of the server's. Now a green receipt of the SAME request (action, subject AND params)
younger than :data:`~dev_lab.ops.consent.door.RECEIPT_FRESH_S` sends the code first; the preflight re-runs only to
REPORT a failure. Without such a receipt the door refuses before the code is sent, naming the ``--preflight`` door.
A plan's code waits on no handshake either: its recorded green is read locally.

The fake issuer below charges every request :data:`LATENCY_S` of a fake clock and records where on that clock the
code arrived, relative to the start of the call. PLANTED CONTROLS: each refusal is followed by the same call with
the fault removed, which spends the very code the refusal kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from _ops_fixtures import NOW, RFC_KEY, code
from test_ops_consent_door import Wire

from dev_lab.dev import sshholdplan
from dev_lab.dev.forgebreakglass import wave_main
from dev_lab.dev.sshholdwire import HoldRefused
from dev_lab.ops.consent.client import grant, grant_plan, preflight
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.door import (
    CODE_PREFLIGHT_FRESH_S,
    PLAN_PREFLIGHT_DOOR,
    PREFLIGHT_DOOR,
    RECEIPT_FRESH_S,
    record_preflight,
)
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consent.plan import parsed

#: What one request to the issuer costs on the fake clock: the measured preflight was ~30 s, a TOTP step is 30 s.
LATENCY_S = 15.0
WAVE = {'action': 'breakglass.wave', 'subject': 'w', 'params': {'hours': 1.0, 'max_merges': 1}}
_CODE_VERBS = frozenset({'issue', 'issue-plan'})


class Clocked(Wire):
    """The issuer, each request costing :data:`LATENCY_S`; ``arrived`` is where the code landed on that clock."""

    def __init__(self, issuer: Issuer, *, old: bool = False) -> None:
        """*old* refuses ``hello`` as an issuer predating it (:class:`Wire`)."""
        super().__init__(issuer, old=old)
        self.clock, self.arrived = 0.0, cast('float | None', None)

    def __call__(self, table: object, request: dict[str, Any]) -> tuple[int, str]:
        if request['verb'] in _CODE_VERBS and self.arrived is None:
            self.arrived = self.clock
        self.clock += LATENCY_S
        return super().__call__(table, request)


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


def _grant(tmp_path: Path, table: dict[str, Any], wire: Clocked, request: dict[str, Any] = WAVE) -> Path:
    return grant(_request(tmp_path, request), table=table, code=code(0), tty=False, send=wire, home=tmp_path,
                 now=lambda: NOW)  # fmt: skip


def test_a_fresh_receipt_makes_the_code_the_first_request(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    preflight(WAVE, table=table, send=Wire(issuer), home=tmp_path, now=NOW - RECEIPT_FRESH_S + 60)
    wire = Clocked(issuer)
    written = _grant(tmp_path, table, wire)
    assert json.loads(written.read_text(encoding='utf-8'))['action'] == 'breakglass.wave'
    assert wire.arrived == 0.0
    assert wire.sent == ['issue']


@pytest.mark.parametrize('age', [None, RECEIPT_FRESH_S + 1], ids=['missing', 'stale'])
def test_no_fresh_receipt_refuses_without_spending_the_code(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path, age: float | None
) -> None:
    if age is not None:
        preflight(WAVE, table=table, send=Wire(issuer), home=tmp_path, now=NOW - age)
    wire = Clocked(issuer)
    with pytest.raises(ConsentRefused, match='no fresh preflight') as refused:
        _grant(tmp_path, table, wire)
    assert PREFLIGHT_DOOR in str(refused.value)
    assert wire.sent == []
    assert wire.arrived is None
    preflight(WAVE, table=table, send=Wire(issuer), home=tmp_path, now=NOW)  # PLANTED CONTROL: the same code is
    assert _grant(tmp_path, table, wire).is_file()  # unspent, and a fresh receipt sends it first
    assert wire.sent == ['issue']


def test_a_receipt_for_other_params_does_not_admit_the_code(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    """The breakglass plan is its hours and max-merges: a green for 1 h does not send a code asking for 2 h."""
    preflight(WAVE, table=table, send=Wire(issuer), home=tmp_path, now=NOW)
    wire = Clocked(issuer)
    wider = WAVE | {'params': {'hours': 2.0, 'max_merges': 1}}
    with pytest.raises(ConsentRefused, match='no fresh preflight') as refused:
        _grant(tmp_path, table, wire, wider)
    assert "'hours': 1.0" in str(refused.value)
    assert wire.sent == []
    assert _grant(tmp_path, table, wire).is_file()  # PLANTED CONTROL: the params preflighted


def test_a_refused_code_is_reported_with_the_preflight_run_after_it(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path
) -> None:
    """The issuer since replaced by one this client cannot speak to: the code went first, the diagnosis follows."""
    preflight(WAVE, table=table, send=Wire(issuer), home=tmp_path, now=NOW)
    wire = Clocked(issuer, old=True)
    wire.issuer = Issuer(
        tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test issuer', lambda: NOW + 3600
    )  # fmt: skip -- an hour on: the code is outside its window there
    with pytest.raises(ConsentRefused) as refused:
        _grant(tmp_path, table, wire)
    assert wire.sent == ['issue', 'hello']
    assert wire.arrived == 0.0
    assert 'the preflight run after it' in str(refused.value)


def test_breakglass_open_code_after_its_preflight_sends_the_code_first(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server_sent: list[dict[str, Any]] = []

    def server(_t: object, request: dict[str, Any]) -> tuple[int, str]:
        server_sent.append(request)
        return 0, 'ok'

    wire = Clocked(issuer)

    def run(*argv: str) -> int:
        return wave_main(
            list(argv), table={'endpoint': 'bg@forge'}, send=server, home=tmp_path,
            preflight_=lambda request, **kw: preflight(request, table=table, send=Wire(issuer), now=NOW, **kw),
            grant_=lambda path, **kw: grant(path, table=table, tty=False, send=wire, now=lambda: NOW, **kw),
        )  # fmt: skip

    assert run('open', '--preflight', '--hours', '1', '--max-merges', '1') == 0
    assert 'sends the code first' in capsys.readouterr().out
    assert run('open', '--code', code(0), '--hours', '2', '--max-merges', '1') == 2
    assert PREFLIGHT_DOOR in capsys.readouterr().err
    assert wire.sent == []
    assert run('open', '--code', code(0), '--hours', '1', '--max-merges', '1') == 0  # PLANTED CONTROL
    assert wire.sent == ['issue']
    assert wire.arrived == 0.0
    assert server_sent[-1]['action'] == 'open'


_PLAN = {'hosts': ['ops@h.example'], 'grants': [{'host': 'ops@h.example', 'action': 'ops.config', 'subject': 'a' * 64}]}


def _plan(tmp_path: Path) -> Path:
    path = tmp_path / 'p.plan.json'
    path.write_text(json.dumps(_PLAN), encoding='utf-8')
    return path


def test_a_plan_code_after_a_green_preflight_is_the_first_request(
    issuer: Issuer, table: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr('dev_lab.ops.consent.door.unregistered', lambda _plan: [])
    monkeypatch.setattr('dev_lab.ops.consent.client.requested', lambda request: request)
    found, wire = parsed(_PLAN), Clocked(issuer)
    with pytest.raises(ConsentRefused, match='no green preflight'):
        grant_plan(_plan(tmp_path), found.digest, code(0), 'ops@h.example', table=table, send=wire, home=tmp_path,
                   now=lambda: NOW)  # fmt: skip
    assert wire.sent == []
    record_preflight(found, home=tmp_path, now=NOW)
    written = grant_plan(_plan(tmp_path), found.digest, code(0), 'ops@h.example', table=table, send=wire,
                         home=tmp_path, now=lambda: NOW)  # fmt: skip
    assert len(written) == 1
    assert wire.sent == ['issue-plan']
    assert wire.arrived == 0.0


def test_sshhold_refuses_a_given_code_without_a_fresh_green_instead_of_re_running(tmp_path: Path) -> None:
    """A re-run costs the code its window; a given code is refused BEFORE it, naming the preflight door."""
    plan = _plan(tmp_path)
    record_preflight(parsed(_PLAN), home=tmp_path / 'home', now=NOW - CODE_PREFLIGHT_FRESH_S - 1)
    reran: list[str] = []

    def offered(*, code_given: bool) -> str:
        return sshholdplan.offered(plan, None, code_given=code_given, rerun=lambda _p, _s: reran.append('x') or [],
                                   held=lambda _d: False, home=tmp_path / 'home', now=NOW)  # fmt: skip

    with pytest.raises(HoldRefused, match='no code used') as refused:
        offered(code_given=True)
    assert PLAN_PREFLIGHT_DOOR in str(refused.value)
    assert reran == []
    offered(code_given=False)  # PLANTED CONTROL: a code asked at the prompt comes after the re-run
    assert reran == ['x']
