"""A DARK FLEET IS AN ALARM, ONCE PER EPISODE -- every host of a platform stale, or a tick that serves nothing.

Ada 2026-10-25..27: every host's tick ran with ``serve = false`` in each account's machine file, so nothing was
claimed and no card published; ``forge queue`` printed STALE per host, and no alarm reached anyone for two days
(HPC use fell from 67% to 1%). A per-host STALE line is read only by whoever runs the queue; a platform with NO
live host is a fact any serving host can see on the forge and must sound (:func:`watch`), and a tick that serves
nothing because every repo of its ``[deploy]`` is ``serve = false`` says so itself (:func:`serve_off`).

ONE ALARM PER EPISODE: an episode starts when the condition first holds and ends when it no longer does (a host of
the platform ticks again; the tick serves a repo). The open episodes live in ``forge-fleet.json`` beside the
machine file; inside one nothing is raised again, whatever the alarm channel's own repeat window.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path

from lab_commons.compute.durable import durable_text, read_table
from lab_commons.config import config_path
from lab_commons.log import emit

from dev_lab.dev.forgealarm import FLEET, Alarm
from dev_lab.dev.forgehosts import HostCard

__all__ = ['dark_platforms', 'serve_off', 'watch']


def _state() -> Path:
    return config_path().parent / 'forge-fleet.json'


def _episode(key: str, *, on: bool, raise_: Callable[[], object]) -> bool:
    """Open *key*'s episode (raising once) while *on*; close it when not. Returns *on*."""
    path = _state()
    open_ = dict(read_table(path))
    if on and key not in open_:
        raise_()
        open_[key] = 'open'
    elif not on and key in open_:
        del open_[key]
    else:
        return on
    durable_text(path, json.dumps(open_))
    return on


def dark_platforms(cards: Iterable[HostCard], now: datetime) -> dict[str, tuple[str, ...]]:
    """Each platform whose every card is stale, with those hosts; a platform with one live host is not dark."""
    hosts: dict[str, list[HostCard]] = {}
    for card in cards:
        hosts.setdefault(card.platform, []).append(card)
    return {
        platform: tuple(sorted(card.host for card in group))
        for platform, group in hosts.items()
        if all(card.stale(now) for card in group)
    }


def watch(cards: Iterable[HostCard], now: datetime, *, alarm: Callable[[Alarm], object], repo: str) -> None:
    """Alarm once per platform going dark; close its episode when a host of it ticks again."""
    cards = tuple(cards)
    dark = dark_platforms(cards, now)
    for platform in sorted({card.platform for card in cards}):
        hosts = dark.get(platform, ())
        subject = f'every {platform} host is stale: nothing serves {platform} work'
        body = f'{", ".join(hosts)}: no tick published -- check `serve` in each ~/.config/lab-commons/config.toml'
        _episode(f'dark:{platform}', on=bool(hosts), raise_=lambda s=subject, b=body, p=platform: alarm(
            Alarm(FLEET, repo, s, b, about=p)
        ))  # fmt: skip


def serve_off(serves: Mapping[str, bool], account: str, *, alarm: Callable[[Alarm], object], repo: str) -> bool:
    """Whether a tick of *account* serves nothing (every repo in *serves* is ``serve = false``); says so loudly.

    The line is written every tick; the alarm once per episode, closed by a tick that serves a repo.
    """
    off = bool(serves) and not any(serves.values())
    if off:
        emit(
            f'[tick] ALARM {account} serves nothing: every repo is serve = false ({", ".join(sorted(serves))})',
            err=True,
        )
    subject = f'{account} serves nothing: every repo of its [deploy] is serve = false'
    body = 'set serve = true for the repos this account should serve in its ~/.config/lab-commons/config.toml'
    return _episode(f'serve-off:{account}', on=off, raise_=lambda: alarm(
        Alarm(FLEET, repo, subject, body, about=f'serve-off:{account}')
    ))  # fmt: skip
