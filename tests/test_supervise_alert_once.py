"""AN ALERT IS RENDERED ONCE (#62): a component's Notice reaches the channels as itself, never re-wrapped.

The 2026-11-02 19:02 Gitea alert carried ``**``, backticks and empty bullets because the pressure component
handed the loop the rendered Markdown of its Notice as a message, and the loop wrapped it in a second Notice.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from dev_lab.supervise import hostalarms, loop
from dev_lab.supervise.alert import Delivery
from dev_lab.supervise.component import CheckContext, Registry
from dev_lab.supervise.components import pressure as component
from dev_lab.supervise.components.pressure import HostPressure
from dev_lab.supervise.notice import Notice, headline, markdown, telegram_html
from dev_lab.supervise.pressure import Finding, Measured
from dev_lab.supervise.verdict import Anomaly, Severity

if TYPE_CHECKING:
    from dev_lab.supervise.process.base import ProcessManager

NOW = datetime(2026, 11, 2, 19, 2, tzinfo=UTC)
CPU = Measured(
    findings=[
        Finding(
            'psi:cpu:some',
            'warning',
            'cpu pressure some 54.8% (threshold 50.0%)',
            metric='cpu pressure some',
            value='54.8%',
            threshold='50.0%',
        )
    ]
)
HEADLINE = 'WARNING · Gitea · cpu pressure some 54.8% (threshold 50.0%)'


class _Capture:
    def __init__(self) -> None:
        self.sent: list[Notice] = []

    def send(self, notice: Notice) -> list[Delivery]:
        self.sent.append(notice)
        return [Delivery('telegram', ok=True)]


def _through_the_loop(monkeypatch: pytest.MonkeyPatch) -> Notice:
    monkeypatch.setattr(component, 'measure', lambda *_a, **_k: CPU)
    monkeypatch.setattr(component, 'host_label', lambda *_a, **_k: 'Gitea')
    ctx = CheckContext(
        config={'owner': hostalarms.INTEGRATOR},
        shared={},
        state={},
        project=Path(),
        manager=cast('ProcessManager', None),
    )
    anomalies = HostPressure().check(ctx).anomalies
    for one in anomalies:
        one.source = f'host_pressure.{one.kind}'
    notifier = _Capture()
    loop._notify(
        anomalies, Registry(), config={'notify': {'host_label': 'Gitea'}}, state={}, clock=NOW, notifier=notifier
    )
    (notice,) = notifier.sent
    return notice


def test_a_cpu_pressure_alert_through_the_loop_reads_once_in_markdown_and_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Golden: the headline once, no literal ``**`` or backticks in Telegram, no empty bullet in either."""
    notice = _through_the_loop(monkeypatch)
    assert headline(notice) == HEADLINE
    assert not notice.title.startswith('host_pressure')
    text = markdown(notice)
    assert text.splitlines()[0] == '**WARNING** · Gitea · cpu pressure some 54.8% (threshold 50.0%)'
    assert text.count('cpu pressure some') == 1
    assert not re.search(r'^- *$', text, re.MULTILINE)
    assert text.count('**WARNING**') == 1
    tg = telegram_html(notice)
    assert tg.splitlines()[0] == '<b>WARNING</b> · Gitea · cpu pressure some 54.8% (threshold 50.0%)'
    outside_code = re.sub(r'<pre>.*?</pre>|<code>.*?</code>', '', tg, flags=re.DOTALL)
    assert '**' not in outside_code
    assert '`' not in outside_code
    assert not re.search('^\N{BULLET} *$', tg, re.MULTILINE)
    assert tg.count('cpu pressure some') == 1
    assert '<pre>python -m dev_lab.dev.branchset --apply' in tg


def test_planted_a_rendered_notice_handed_in_as_a_message_is_refused() -> None:
    """PLANTED CONTROL: the 19:02 defect's input -- markdown() as a message -- cannot be built into an Anomaly."""
    rendered = markdown(Notice(title='cpu pressure some', value='54.8%', threshold='50.0%', host='Gitea'))
    with pytest.raises(ValueError, match='rendered'):
        Anomaly(kind='pressure_psi:cpu:some', severity=Severity.WARNING, message=rendered)
    plain = Anomaly(kind='pressure_psi:cpu:some', severity=Severity.WARNING, message='cpu pressure some 54.8%')
    assert plain.message == 'cpu pressure some 54.8%'
