"""THE DOOR THAT TAKES THE CODE RUNS THE PREFLIGHT ITSELF: a recorded green is a backstop, never the verdict.

User ruling 2026-11-22, five codes lost that day. ``sshhold open --plan --code C`` refused a stale plan preflight
only AFTER the code was given (its 30 s window then gone); ``consent grant --code C`` refused a lone request's
receipt older than 300 s the same way. Now each door runs the no-code preflight right before it uses the code: a
record of any age inside the 24 h backstop admits the ask, and what the host answers NOW decides.

Every refusal has its PLANTED control: the same call with the one fault removed uses the code.
"""

from __future__ import annotations

import json
import time
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, code
from lab_commons.home import HOME_ENV
from test_dev_planrun import CANDIDATE, CONF, LOCAL, PY, FakeHost, secret_here
from test_dev_planrun import PLAN as STEPPED
from test_ops_consent_door import WAVE, Wire, issuer

from dev_lab.dev import planrunoffer, sshhold, sshholdplan
from dev_lab.ops.consent.client import grant, preflight
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.door import (
    CODE_PREFLIGHT_FRESH_S,
    PREFLIGHT_FRESH_S,
    RECEIPT_FRESH_S,
    preflighted_steps,
    record_preflight,
)
from dev_lab.ops.consent.issuer import Issuer

__all__ = ['issuer', 'secret_here']

DAY_S = 24 * 3600.0
#: The lifetimes the incident met: a plan's green was valid 3600 s, a lone request's receipt 300 s.
WAS_PLAN_S, WAS_RECEIPT_S = 3600.0, 300.0
#: A recorded green just past the window in which it stands in for the door's own re-run (ruling 2026-11-23,
#: tests/test_dev_sshhold_code_freshness.py): the door re-runs the preflight, which is what these tests are about.
RERUN_AGE_S = CODE_PREFLIGHT_FRESH_S + 1.0


def test_both_lifetimes_are_the_24_h_backstop() -> None:
    assert PREFLIGHT_FRESH_S == DAY_S
    assert RECEIPT_FRESH_S == DAY_S


def _files(tmp_path: Path) -> tuple[Path, Path]:
    plan, steps = tmp_path / 'plan.json', tmp_path / 'steps.json'
    plan.write_text(json.dumps({'hosts': list(STEPPED.hosts), 'grants': [dict(g) for g in STEPPED.grants]}), 'utf-8')
    listed = [{'argv': ['config', 'apply', '--from', CANDIDATE]},
              {'argv': ['secret', 'place', '--path', '/etc/x'], 'stdin_local': LOCAL}]  # fmt: skip
    steps.write_text(json.dumps({'config': CONF, 'python': PY, 'steps': listed}), 'utf-8')
    return plan, steps


def _door(monkeypatch: pytest.MonkeyPatch, issuer: Issuer, host: FakeHost) -> list[str]:
    """``sshhold open --plan`` wired to *host* and *issuer*; the codes that reached the grant."""
    spent: list[str] = []
    monkeypatch.setattr(
        sshholdplan, 'reproved', partial(planrunoffer.reproved, remotes=lambda _dest: host, table={}, send=Wire(issuer))
    )
    monkeypatch.setattr(
        sshholdplan, 'open_planned', lambda _hours, given, *_a, **_k: spent.append(given) or (True, ['granted'])
    )
    return spent


def _open(plan: Path, *more: str) -> int:
    return sshhold.main(['open', '--hours', '1', '--code', code(0), '--plan', str(plan), '--digest', 'abc', *more])


def test_a_plan_whose_host_blocks_now_refuses_before_the_code_is_used(
    issuer: Issuer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The recorded green is past the code window and the host has since lost its consent key: no code used.

    PLANTED CONTROL: the same open against the green host hands the code to the grant.
    """
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    plan, steps = _files(tmp_path)
    record_preflight(STEPPED, steps=steps, now=time.time() - RERUN_AGE_S)
    host = FakeHost()
    host.ready = (1, '[ops consent] not ready: no consent key')
    spent = _door(monkeypatch, issuer, host)
    assert _open(plan) == 2
    said = capsys.readouterr().err
    assert 'no code used' in said
    assert 'no consent key' in said
    assert spent == []
    assert host.commands, 'the door asked the host itself'
    spent = _door(monkeypatch, issuer, FakeHost())
    assert _open(plan) == 0
    assert spent == [code(0)]


def test_a_green_older_than_the_old_hour_still_takes_the_code_when_the_host_is_green_now(
    issuer: Issuer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The incident's own shape: a green 31161 s old. The door preflights now, and the code is used, not lost.

    PLANTED CONTROL: past the 24 h backstop with NO steps file to run, the door refuses -- it cannot check.
    """
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    plan, steps = _files(tmp_path)
    assert WAS_PLAN_S < 31161 < PREFLIGHT_FRESH_S
    record_preflight(STEPPED, steps=steps, now=time.time() - 31161)
    host = FakeHost()
    spent = _door(monkeypatch, issuer, host)
    assert _open(plan) == 0
    assert spent == [code(0)]
    assert host.commands
    assert preflighted_steps(STEPPED) == steps.resolve()  # re-recorded by the door's own green
    record_preflight(STEPPED, now=time.time() - RERUN_AGE_S)  # a record naming no steps file: nothing to run
    spent = _door(monkeypatch, issuer, FakeHost())
    assert _open(plan) == 2
    said = capsys.readouterr().err
    assert 'no code used' in said
    assert '--steps' in said
    assert spent == []
    assert _open(plan, '--steps', str(steps)) == 0  # naming the steps file is the door
    assert spent == [code(0)]


def _table(issuer: Issuer) -> dict[str, Any]:
    return {'endpoint': 'consent@forge', 'public_key': public_text(issuer.public())}


def _request(tmp_path: Path) -> Path:
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(WAVE), encoding='utf-8')
    return path


def test_a_lone_code_given_past_the_old_five_minutes_is_used_when_the_issuer_is_green_now(
    issuer: Issuer, tmp_path: Path
) -> None:
    table, wire = _table(issuer), Wire(issuer)
    preflight(WAVE, table=table, send=wire, home=tmp_path, now=NOW - 2 * WAS_RECEIPT_S)
    written = grant(_request(tmp_path), table=table, code=code(0), tty=False, send=wire, home=tmp_path,
                    now=lambda: NOW)  # fmt: skip
    assert json.loads(written.read_text(encoding='utf-8'))['action'] == 'breakglass.wave'
    assert wire.sent == ['hello', 'hello', 'issue']  # the preflight's, the door's own, then the code


def test_a_lone_code_is_not_sent_when_the_doors_own_preflight_is_blocked_now(issuer: Issuer, tmp_path: Path) -> None:
    """The receipt is fresh; the issuer has since been replaced by one this client cannot redeem with.

    PLANTED CONTROL: the test above -- the same grant with the issuer answering is issued.
    """
    table = _table(issuer)
    preflight(WAVE, table=table, send=Wire(issuer), home=tmp_path, now=NOW)
    skewed = Wire(issuer, old=True)
    read: list[str] = []
    with pytest.raises(ConsentRefused, match='no code used -- the preflight is not green now') as refused:
        grant(_request(tmp_path), table=table, tty=False, read=lambda: read.append('read') or code(0), send=skewed,
              home=tmp_path, now=lambda: NOW)  # fmt: skip
    assert 'no code asked' not in str(refused.value)
    assert skewed.sent == ['hello']
    assert read == [], 'the code was never read off stdin'
