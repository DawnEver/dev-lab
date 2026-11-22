"""A DEAD HOLD IS NEVER "REUSED": a held session counts only while its ssh connection still runs.

Incident 2026-11-22, and it cost a code: ``sshhold open --plan`` printed ``held session reused (no code sent)`` for
a host whose hold had ended -- the holder process still answered ``ping``, its ssh connection was gone. The code
went to the plan's grants alone, nothing opened the host, and the run met ``UNREACHABLE``. ``ping`` now answers for
the CONNECTION (the holder's ssh child), a dead hold's record is removed, and the host is opened with the code in
hand, in the same call.

End to end against the real holder process and the fake ssh, whose process this test kills behind the holder's back.
PLANTED CONTROL: the same plan open over the LIVE hold reuses it and sends it no code.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest
from test_dev_sshhold import CODE, FAKE

from dev_lab.dev import sshhold, sshholdplan, sshholdstate, sshholdwire

DEST = 'ops@fake.example'


def _plan(tmp_path: Path) -> Path:
    plan = tmp_path / 'plan.json'
    grant = {'host': DEST, 'action': 'ops.config', 'subject': 'a' * 64}
    plan.write_text(json.dumps({'hosts': [DEST], 'grants': [grant]}), encoding='utf-8')
    return plan


def _planned(plan: Path) -> tuple[list[str], list[str]]:
    """``open_planned`` with a scripted grant: ``(the hosts the code was sent to, its lines)``."""
    sent: list[str] = []

    def opener(dest: str, *_given: object, **_route: object) -> str:
        sent.append(dest)
        return f'{dest}: open'

    _, lines = sshholdplan.open_planned(
        1, CODE, plan, 'abc', grant=lambda *_a: [], routes=lambda _dest: FAKE, opener=opener
    )
    return sent, lines


def _kill_the_connection(pid_file: Path) -> None:
    os.kill(int(pid_file.read_text(encoding='utf-8')), signal.SIGTERM)


def _until(done: object, what: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if done():
            return
        time.sleep(0.2)
    pytest.fail(f'never happened: {what}')


def test_a_hold_whose_connection_ended_is_opened_with_the_code_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('FAKESSH_CODE', CODE)
    monkeypatch.setenv('FAKESSH_PID_OUT', str(tmp_path / 'ssh.pid'))
    plan = _plan(tmp_path)
    sshhold.open_session(DEST, 1.0, CODE, ssh=FAKE)
    try:
        session = sshholdstate.read_session(DEST)
        assert session is not None
        assert sshholdwire.held(DEST)
        sent, lines = _planned(plan)  # the PLANTED control: a live hold is reused, the code is not sent to it
        assert sent == []
        assert lines[-1] == f'{DEST}: held session reused (no code sent)'
        _kill_the_connection(tmp_path / 'ssh.pid')
        _until(lambda: not sshholdwire.ping(session), 'the holder said its connection is gone')
        sent, lines = _planned(plan)
        assert sent == [DEST], lines
        assert lines[-1] == f'{DEST}: open'
        assert sshholdstate.read_session(DEST) is None, "the dead hold's record is removed"
    finally:
        if sshholdstate.read_session(DEST) is not None:
            sshhold.close_session(DEST)


def test_the_record_of_a_holder_that_is_gone_is_removed_and_the_host_is_not_held() -> None:
    sshholdstate.write_session(sshholdstate.Session(DEST, 1, 1, 'x', 0.0, 9e12))
    assert not sshholdwire.held(DEST)
    assert sshholdstate.read_session(DEST) is None


def test_the_plan_door_clears_a_dead_hold_before_it_preflights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Green then means: reached through a live hold, or a host the code will open."""
    sshholdstate.write_session(sshholdstate.Session(DEST, 1, 1, 'x', 0.0, 9e12))
    seen: list[bool] = []
    monkeypatch.setattr(sshholdplan, 'reproved', lambda *_a: seen.append(sshholdstate.read_session(DEST) is None) or [])
    sshholdplan.offered(_plan(tmp_path))
    assert seen == [True]
