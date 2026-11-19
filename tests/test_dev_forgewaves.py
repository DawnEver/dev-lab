"""A break-glass wave awaiting review reaches each session once, through the feed, never as an issue (2026-11-19)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import forgewaves

_TABLE = {'endpoint': 'ops@host'}
_STATUS = (
    'wave 20261119T1: audit, 3 merge(s)\nwave 20261118T9: acknowledged, 2 merge(s)\nwave 20261119T2: open, 1 merge(s)'
)


@pytest.fixture(autouse=True)
def _feed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(forgewaves, 'feed_dir', lambda: tmp_path)


def test_only_a_wave_in_audit_is_awaiting() -> None:
    """PLANTED CONTROL: an acknowledged wave and an open one are not awaiting review."""
    assert forgewaves.awaiting(_STATUS) == {'20261119T1': 3}


def test_each_session_is_told_each_wave_once() -> None:
    asked = []
    assert forgewaves.refresh(lambda _t, r: asked.append(r) or (0, _STATUS), table=_TABLE, now=10_000.0)
    assert asked == [{'action': 'status'}]
    first = forgewaves.news('s1')
    assert len(first) == 1
    assert 'forge breakglass ack 20261119T1' in first[0]
    assert forgewaves.news('s1') == [], 'told once'
    assert len(forgewaves.news('s2')) == 1, 'another session is told too'


def test_the_endpoint_is_asked_at_most_every_period_and_never_without_one() -> None:
    calls = []
    send = lambda _t, r: calls.append(r) or (0, _STATUS)  # noqa: E731
    assert forgewaves.refresh(send, table=_TABLE, now=10_000.0)
    assert not forgewaves.refresh(send, table=_TABLE, now=10_000.0 + forgewaves.EVERY_S - 1)
    assert forgewaves.refresh(send, table=_TABLE, now=10_000.0 + forgewaves.EVERY_S)
    assert len(calls) == 2
    assert not forgewaves.refresh(send, table={}, now=99_999.0), 'no [breakglass] endpoint: nothing asked'
    assert len(calls) == 2


def test_a_failed_ask_keeps_the_last_answer() -> None:
    forgewaves.refresh(lambda _t, _r: (0, _STATUS), table=_TABLE, now=10_000.0)
    forgewaves.refresh(lambda _t, _r: (1, 'unreachable'), table=_TABLE, now=20_000.0)
    assert len(forgewaves.news('s3')) == 1
