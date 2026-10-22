"""A SILENT FAILURE REACHES A HUMAN: one structured line always, the configured channels too, no paging storm."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab_commons.config import CONFIG_ENV
from dev_lab.dev.forgealarm import AUTH, EVENT, Alarm, main, repeat_window, sound
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
    assert sound(ALARM, send=telegram, now=NOW + timedelta(hours=6)) == ('telegram',), 'PLANTED CONTROL: past it'


def test_the_repeat_window_is_the_receivers_declaration() -> None:
    """``[alerts] repeat_hours``: the person paged decides how often; absent, six hours."""
    sent: list[Notice] = []

    def telegram(notice: Notice) -> list[Delivery]:
        sent.append(notice)
        return [Delivery('telegram', ok=True)]

    assert repeat_window({}) == timedelta(hours=6)
    hourly = {'repeat_hours': 1}
    assert sound(ALARM, alerts=hourly, send=telegram, now=NOW) == ('telegram',)
    assert sound(ALARM, alerts=hourly, send=telegram, now=NOW + timedelta(minutes=30)) == ()
    assert sound(ALARM, alerts=hourly, send=telegram, now=NOW + timedelta(hours=1)) == ('telegram',)
    assert len(sent) == 2


def test_a_channel_that_failed_is_tried_again_next_tick() -> None:
    tries: list[bool] = []

    def flaky(_notice: Notice) -> list[Delivery]:
        tries.append(True)
        return [Delivery('telegram', ok=len(tries) > 1, detail='timeout')]

    assert sound(ALARM, send=flaky, now=NOW) == ()
    assert sound(ALARM, send=flaky, now=NOW + timedelta(minutes=5)) == ('telegram',)


def test_a_process_that_imports_no_dev_code_raises_one_through_the_cli(capsys) -> None:
    """``python -m dev_lab.dev.forgealarm <kind> <repo> <subject> <body>``: the hpc deploy's channel."""
    assert main(['run', 'https://f/o/r.git', 'the deploy refused r', 'its retired table']) == 0
    line = _line(capsys)
    assert (line['kind'], line['repo'], line['subject'], line['body']) == (
        'run',
        'https://f/o/r.git',
        'the deploy refused r',
        'its retired table',
    )
