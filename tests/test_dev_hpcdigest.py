"""The daily HPC digest: once a UTC day after the declared hour, ONE message, a dated row, a failed send retried.

Planted controls: an undeclared machine file and a tick before the hour send nothing; a second tick the same day
sends nothing; a failed send IS retried; a channel's reply (Telegram echoes the chat) is never stored. A non-poller
tick never reaches the step: tests/test_dev_forgeserve.py (the lease tests).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Never

import pytest
from lab_commons.hpc.cluster import Unreachable
from lab_commons.hpc.grants import Budget, Grant

from dev_lab.dev import hpcdigest
from dev_lab.dev.forgehosts import HostCard
from dev_lab.supervise.alert import Delivery
from dev_lab.supervise.notice import Notice, telegram_html

NOON = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
USAGE = {
    'jobs': 12,
    'core_hours': 340.5,
    'cpu_efficiency': 0.82,
    'states': {'COMPLETED': 9, 'FAILED': 1, 'OUT_OF_MEMORY': 1, 'TIMEOUT': 1, 'RUNNING': 0},
}
SACCT = '201|sweep|COMPLETED|4|14400|03:00:00|4G|\n202|sweep|TIMEOUT|2|7200|00:30:00|4G|\n'
QUOTA = 'Disk quotas for user x:\n     /dev/x 5000 0 10000 0 300 0 1000 0\n'
LEDGER = 'COMPLETED|4|60|36000000\nRUNNING|8|600|0\n'


def _card(host: str = 'c/svc', usage: dict | None = USAGE) -> HostCard:
    facts = {'usage': usage, 'quota_use': {'bytes': 0.41, 'files': 0.93}} if usage is not None else {}
    return HostCard(host=host, login='l', platform='linux', ticked=NOON.isoformat(), facts=facts, role='verification')


def _grant(user: str, *, billed: bool = False) -> Grant:
    budget = Budget(20000, '2026-08-01', '2027-08-01') if billed else None
    return Grant(user, ('h',), 'acct', billed=billed, budget=budget, role='research', cluster_name='c')


class _Channel:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[Notice] = []

    def __call__(self, notice: Notice) -> list[Delivery]:
        self.sent.append(notice)
        return [Delivery('telegram', ok=self.ok, detail='{"result": {"chat": {"id": 424242}}}')]


def _runner(answers: dict[str, str]) -> Callable[[str, str | None], str]:
    def run(command: str, _stdin: str | None) -> str:
        return next(out for key, out in answers.items() if command.startswith(key))

    return run


def _step(
    tmp_path: Path,
    channel: Callable[[Notice], list[Delivery]],
    *,
    now: datetime = NOON,
    table: dict | None = None,
    **kw: object,
) -> tuple[hpcdigest.Sent | None, list[str]]:
    said: list[str] = []
    out = hpcdigest.step(
        kw.pop('cards', [_card()]),
        say=said.append,
        now=now,
        table={'hour_utc': 7} if table is None else table,
        path=tmp_path / hpcdigest.STORE_NAME,
        send=channel,
        grants=kw.pop('grants', list),
        **kw,
    )
    return out, said


def test_the_first_poller_tick_after_the_hour_sends_one_message_and_records_the_day(tmp_path: Path) -> None:
    channel = _Channel()
    out, said = _step(tmp_path, channel)
    assert out is not None
    assert out.sent
    assert len(channel.sent) == 1
    rows = hpcdigest.read_rows(tmp_path / hpcdigest.STORE_NAME)
    assert [r['day'] for r in rows] == ['2026-11-15']
    assert rows[0]['accounts']['c/svc']['core_hours'] == pytest.approx(340.5, abs=1e-9)
    assert said == ['[serve] hpc digest sent for 1 account(s): telegram ok']


def test_planted_control_a_second_tick_the_same_day_sends_nothing(tmp_path: Path) -> None:
    channel = _Channel()
    _step(tmp_path, channel)
    out, said = _step(tmp_path, channel, now=NOON.replace(hour=23))
    assert out is None
    assert said == []
    assert len(channel.sent) == 1
    again, _said = _step(tmp_path, channel, now=NOON.replace(day=16, hour=7))
    assert again is not None
    assert len(channel.sent) == 2, 'the next day sends again'


@pytest.mark.parametrize(('table', 'hour'), [({}, 12), ({'hour_utc': 7}, 6)])
def test_planted_control_undeclared_or_before_the_hour_sends_nothing(tmp_path: Path, table: dict, hour: int) -> None:
    channel = _Channel()
    out, _said = _step(tmp_path, channel, table=table, now=NOON.replace(hour=hour))
    assert out is None
    assert channel.sent == []
    assert not (tmp_path / hpcdigest.STORE_NAME).exists()


def test_a_failed_send_is_recorded_said_and_retried_next_tick(tmp_path: Path) -> None:
    out, said = _step(tmp_path, _Channel(ok=False))
    assert out is not None
    assert not out.sent
    assert 'ALARM hpc digest NOT sent (telegram FAILED)' in said[0]
    again, _said = _step(tmp_path, _Channel(), now=NOON.replace(minute=5))
    assert again is not None
    assert again.sent, 'an unsent day is retried'
    rows = hpcdigest.read_rows(tmp_path / hpcdigest.STORE_NAME)
    assert [r['sent'] for r in rows] == [False, True]
    assert '424242' not in (tmp_path / hpcdigest.STORE_NAME).read_text(encoding='utf-8'), 'no reply is stored'


def test_no_channel_enabled_is_a_failed_send(tmp_path: Path) -> None:
    out, said = _step(tmp_path, lambda _n: [])
    assert out is not None
    assert not out.sent
    assert '(no channel)' in said[0]


def test_core_hours_show_the_delta_against_the_last_sent_day(tmp_path: Path) -> None:
    _step(tmp_path, _Channel(), now=NOON.replace(day=14))
    channel = _Channel()
    _step(tmp_path, channel, cards=[_card(usage={**USAGE, 'core_hours': 400.0})])
    line = channel.sent[0].findings[0]
    assert '400.0 core-h (+59.5)' in line
    assert 'failed 1 out_of_memory 1 timeout 1' in line
    assert 'storage 41%, files 93%' in line


def test_an_account_with_no_card_is_read_with_the_one_sacct_parser_and_a_billed_one_shows_its_burn() -> None:
    run = _runner({'sacct -n -P -S now-24hours': SACCT, '/usr/lpp': QUOTA, 'sacct -n -P -X': LEDGER})
    one = hpcdigest.read_grant(_grant('res', billed=True), date(2027, 2, 1), connect=lambda _g: run)
    assert one.why == ''
    assert one.usage is not None
    assert one.usage['jobs'] == 2
    assert one.usage['core_hours'] == pytest.approx(6.0, abs=1e-9)
    assert one.quota_use == {'bytes': 0.5, 'files': 0.3}
    assert one.budget is not None
    assert one.budget['spent'] == pytest.approx(10000.0, abs=1e-9)
    assert one.budget['committed'] == pytest.approx(80.0, abs=1e-9)
    line = hpcdigest.render('d', [one], {}).findings[0]
    assert 'budget 10000+80/20000 core-h (50% used, 50% of window to 2027-08-01)' in line


def test_an_account_that_cannot_be_read_is_listed_not_read_with_its_cause() -> None:
    def refuse(_grant: Grant) -> Never:
        msg = 'no login host answered'
        raise Unreachable(msg)

    one = hpcdigest.read_grant(_grant('res'), date(2026, 11, 15), connect=refuse)
    assert hpcdigest.render('d', [one], {}).findings == ('c/res: not read: no login host answered',)


def test_a_serving_account_is_read_off_its_card_once_and_a_declared_research_one_over_ssh(tmp_path: Path) -> None:
    reads: list[tuple[str, bool]] = []

    def read(grant: Grant, _today: date, *, served=None) -> hpcdigest.Account:
        reads.append((grant.user, served is not None))
        return served or hpcdigest.Account(f'c/{grant.user}', why='planted')

    channel = _Channel()
    _step(tmp_path, channel, grants=lambda: [_grant('svc'), _grant('res')], read=read)
    assert reads == [('svc', True), ('res', False)], 'a carded account is never re-read for its day'
    assert [f.split(':')[0] for f in channel.sent[0].findings] == ['c/svc [verification]', 'c/res']


def test_the_message_renders_through_the_telegram_renderer() -> None:
    notice = hpcdigest.render(
        '2026-11-15',
        [hpcdigest.Account('c/svc', 'verification', USAGE, {'bytes': 0.41, 'files': 0.93}),
         hpcdigest.Account('c/res', 'research', why='no login host answered')],
        {'c/svc': {'core_hours': 300.0}},
        host='ws',
    )  # fmt: skip
    text = telegram_html(notice)
    assert 'HPC usage 2026-11-15' in text
    assert '340.5 core-h (+40.5)' in text
    assert 'c/res: not read: no login host answered' in text
