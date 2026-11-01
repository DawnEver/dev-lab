"""A PRESSED HOST TELLS ITS AGENTS AND ITS HUMANS (D54): one state, one formatter, a rate-limited hook."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from dev_lab.dev import forgeservesteps, hostalarm
from dev_lab.dev.agent_guard import PRESSURE_COMMAND, WIRING
from dev_lab.dev.forgealarm import PRESSURE, Alarm, sound
from dev_lab.supervise import hostalarms
from dev_lab.supervise.alert import Delivery, Notice
from dev_lab.supervise.component import CheckContext
from dev_lab.supervise.components import pressure as component
from dev_lab.supervise.components.pressure import HostPressure
from dev_lab.supervise.pressure import DOORS, Finding, Measured

if TYPE_CHECKING:
    from dev_lab.supervise.process.base import ProcessManager

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
CONSUMER = '/home/runner/.claude/worktrees/stale-lane  41.00 GB  owned'
PRESSED = Measured(findings=[Finding('disk:/', 'critical', '/ 98.0% used, 2.0 GB free', (CONSUMER,))])


def _pressed(now: datetime = NOW) -> dict[str, Any]:
    return hostalarms.record(PRESSED, host='gitea', owner=hostalarms.INTEGRATOR, now=now)


def _hook(session: str, now: datetime, capsys: pytest.CaptureFixture[str]) -> str:
    payload = json.dumps({'session_id': session, 'hook_event_name': 'UserPromptSubmit'})
    assert hostalarm.hook(io.StringIO(payload), now=now) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out)['hookSpecificOutput']['additionalContext'] if out else ''


def test_the_hook_reminds_once_is_silent_within_the_window_and_reminds_again_after_it(capsys) -> None:
    """PLANTED CONTROLS: the second call inside 30 minutes is silent; the one past it, and another session, speak."""
    _pressed()
    first = _hook('s1', NOW, capsys)
    assert 'HOST-PRESSURE CRITICAL on gitea' in first
    assert CONSUMER in first
    assert DOORS[0] in first
    assert 'the integrator' in first
    assert _hook('s1', NOW + timedelta(minutes=29), capsys) == ''
    assert _hook('s2', NOW + timedelta(minutes=29), capsys) != ''
    assert _hook('s1', NOW + hostalarm.REMIND_EVERY + timedelta(seconds=1), capsys) == first


def test_the_hook_is_silent_on_a_host_that_is_not_pressed(capsys) -> None:
    hostalarms.record(Measured(), host='ws', now=NOW)
    assert _hook('s1', NOW, capsys) == ''


def test_a_cleared_alarm_leaves_and_a_held_one_keeps_its_first_seen() -> None:
    _pressed(NOW)
    held = _pressed(NOW + timedelta(hours=1))['alarms']['disk:/']
    assert (held['first_seen'], held['last_seen']) == (NOW.isoformat(), (NOW + timedelta(hours=1)).isoformat())
    assert hostalarms.record(Measured(), host='gitea', now=NOW)['alarms'] == {}


def test_post_commit_prints_the_hook_s_own_lines(capsys) -> None:
    """One reader, one formatter: post-commit's text is the hook's text."""
    state = _pressed()
    assert hostalarm.main(['check']) == 0
    assert capsys.readouterr().out.strip() == '\n'.join(hostalarms.lines(state))


def test_the_forge_tick_sounds_each_alarm_as_a_pressure_alarm(tmp_path: Path) -> None:
    """Control: an unpressed reading sounds nothing."""
    raised: list[Alarm] = []
    hostalarm.step(tmp_path, 'r', who='ws1', alarm=raised.append, table={}, measuring=lambda *_a, **_k: PRESSED)
    assert [(a.kind, a.about) for a in raised] == [(PRESSURE, 'disk:/')]
    assert CONSUMER in raised[0].body
    quiet: list[Alarm] = []
    hostalarm.step(tmp_path, 'r', who='ws1', alarm=quiet.append, table={}, measuring=lambda *_a, **_k: Measured())
    assert quiet == []


def test_the_humans_get_it_through_the_notifier_and_never_a_credential() -> None:
    """The [alerts] table holds a token, a chat id and a password; the notice carries none of them."""
    secrets = ('tok-SECRET-123', 'chat-SECRET-456', 'pw-SECRET-789')
    alerts = {
        'telegram': {'enabled': True, 'token': secrets[0], 'chat': secrets[1]},
        'email': {'enabled': True, 'password': secrets[2]},
    }
    sent: list[Notice] = []

    def send(notice: Notice) -> list[Delivery]:
        sent.append(notice)
        return [Delivery('telegram', ok=True)]

    raised: list[Alarm] = []
    hostalarm.step(Path(), 'r', who='gitea', alarm=raised.append, table={}, measuring=lambda *_a, **_k: PRESSED)
    assert sound(raised[0], alerts=alerts, send=send, now=NOW) == ('telegram',)
    (notice,) = sent
    assert CONSUMER in notice.body
    assert not any(s in notice.as_text() for s in secrets)


def test_a_reading_that_fails_is_said_never_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> None:
        why = 'no /proc'
        raise OSError(why)

    monkeypatch.setattr(hostalarm, 'step', broken)
    said: list[str] = []
    forgeservesteps.pressed(Path(), 'r', who='h', say=said.append, alarm=lambda _a: None)
    assert said == ['[serve] the host-pressure reading did not run: no /proc']


def test_the_hook_is_wired_after_shell_calls_and_on_each_prompt() -> None:
    wired = {(w.event, w.on_shells) for w in WIRING if w.command == PRESSURE_COMMAND}
    assert wired == {('PostToolUse', True), ('UserPromptSubmit', False)}


def test_supervision_convicts_and_records_the_same_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    """The component writes the host state the hook reads, and its anomaly message is that state's text."""
    monkeypatch.setattr(component, 'measure', lambda *_a, **_k: PRESSED)
    ctx = CheckContext(
        config={'owner': 'agents'}, shared={}, state={}, project=Path(), manager=cast('ProcessManager', None)
    )
    (anomaly,) = HostPressure().check(ctx).anomalies
    assert anomaly.signature == 'pressure:disk:/'
    assert anomaly.message == hostalarms.lines(hostalarms.read())[0]
