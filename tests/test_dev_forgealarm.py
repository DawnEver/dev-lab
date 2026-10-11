"""A SILENT FAILURE REACHES A HUMAN: one structured line always, the configured channels too, no paging storm."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.dev.forgealarm import AUTH, EVENT, REPEAT, Alarm, sound
from lab_commons.supervise.alert import Delivery, Notice

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
ALARM = Alarm(AUTH, 'https://f/o/r.git', 'the forge refused the stored credential', 'remedy: auth login')


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'config.toml'))


def _line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return json.loads(capsys.readouterr().err.strip().splitlines()[-1])


def test_every_alarm_is_one_structured_line_a_consumer_routes(capsys) -> None:
    """With no channel configured the line IS the delivery -- and it carries no token, only what happened."""
    assert sound(ALARM, alerts={}, now=NOW) == ()
    line = _line(capsys)
    assert (line['event'], line['kind'], line['repo'], line['delivered'], line['repeat']) == (
        EVENT,
        AUTH,
        'https://f/o/r.git',
        [],
        False,
    )


def test_a_configured_channel_takes_it_and_a_repeat_inside_the_window_is_not_delivered_again(capsys) -> None:
    sent: list[Notice] = []

    def telegram(notice: Notice) -> list[Delivery]:
        sent.append(notice)
        return [Delivery('telegram', ok=True)]

    assert sound(ALARM, send=telegram, now=NOW) == ('telegram',)
    assert sent[0].subject == ALARM.subject
    assert sound(ALARM, send=telegram, now=NOW + timedelta(minutes=5)) == ()
    assert _line(capsys)['repeat'] is True, 'a five-minute cron does not page every five minutes'
    assert len(sent) == 1
    assert sound(ALARM, send=telegram, now=NOW + REPEAT) == ('telegram',), 'PLANTED CONTROL: past the window, again'


def test_a_channel_that_failed_is_tried_again_next_tick() -> None:
    tries: list[bool] = []

    def flaky(_notice: Notice) -> list[Delivery]:
        tries.append(True)
        return [Delivery('telegram', ok=len(tries) > 1, detail='timeout')]

    assert sound(ALARM, send=flaky, now=NOW) == ()
    assert sound(ALARM, send=flaky, now=NOW + timedelta(minutes=5)) == ('telegram',)
