"""A DARK FLEET REACHES A HUMAN: every host of a platform stale, or a tick that serves nothing, alarms once per episode.

Ada 2026-10-25..27: every host ticked with ``serve = false`` in each account, ``forge queue`` printed STALE per host,
and no alarm reached anyone for two days.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from lab_commons.config import CONFIG_ENV

from dev_lab.dev.forgealarm import FLEET, Alarm
from dev_lab.dev.forgefleet import dark_platforms, serve_off, watch
from dev_lab.dev.forgehosts import HostCard

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
REPO = 'https://f/o/r.git'


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'config.toml'))


def _card(host: str, platform: str, *, age_min: float) -> HostCard:
    return HostCard(host=host, login='x', platform=platform, ticked=(NOW - timedelta(minutes=age_min)).isoformat())


def test_a_platform_is_dark_only_when_every_host_of_it_is_stale() -> None:
    cards = [_card('ada-a', 'linux', age_min=60), _card('ada-b', 'linux', age_min=60)]
    cards.append(_card('box', 'windows', age_min=1))
    assert dark_platforms(cards, NOW) == {'linux': ('ada-a', 'ada-b')}
    cards.append(_card('ada-c', 'linux', age_min=1))
    assert dark_platforms(cards, NOW) == {}


def test_a_dark_platform_alarms_once_per_episode_and_clears_when_a_host_ticks_again() -> None:
    raised: list[Alarm] = []
    dark = [_card('ada-a', 'linux', age_min=60)]
    watch(dark, NOW, alarm=raised.append, repo=REPO)
    watch(dark, NOW, alarm=raised.append, repo=REPO)
    assert [(a.kind, a.about) for a in raised] == [(FLEET, 'linux')]
    assert 'ada-a' in raised[0].body
    watch([_card('ada-a', 'linux', age_min=1)], NOW, alarm=raised.append, repo=REPO)  # the episode ends
    watch(dark, NOW, alarm=raised.append, repo=REPO)  # a new one alarms again
    assert len(raised) == 2


def test_a_tick_whose_every_repo_is_serve_false_alarms_loudly_once_and_a_serving_tick_clears_it(capsys) -> None:
    raised: list[Alarm] = []
    assert serve_off({'dev-lab': False, 'motronics': False}, 'alice', alarm=raised.append, repo=REPO)
    assert serve_off({'dev-lab': False, 'motronics': False}, 'alice', alarm=raised.append, repo=REPO)
    assert [(a.kind, a.about) for a in raised] == [(FLEET, 'serve-off:alice')]
    assert 'serves nothing' in capsys.readouterr().err
    assert not serve_off({'dev-lab': False, 'motronics': True}, 'alice', alarm=raised.append, repo=REPO)
    serve_off({'dev-lab': False}, 'alice', alarm=raised.append, repo=REPO)
    assert len(raised) == 2
