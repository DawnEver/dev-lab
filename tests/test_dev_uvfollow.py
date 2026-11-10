"""UV ON A HOST FOLLOWS THE PIN wherever dev-lab installs or ticks a host -- not only where a lock is written.

Measured 2026-11-09: the pin was 0.13.7, the newest release; a cloud host ran 0.12.5, a cluster account's was
unknown -- the serve relock moved the pin and nothing moved those hosts. Each place now calls the one follower
(:func:`dev_lab.dev._dep_project.follow_pin`, through :mod:`dev_lab.dev.uvfollow`), and ``family check`` names a
pin lagging the newest release.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dev_lab.dev import uvfollow
from dev_lab.dev.family import watch
from dev_lab.dev.hpcaccount import checks, tick
from dev_lab.ops import upgrade


def _recorder(said: str) -> tuple[list[tuple[str, str]], object]:
    calls: list[tuple[str, str]] = []

    def follow(uv: str, version: str) -> str:
        calls.append((uv, version))
        return said

    return calls, follow


def test_a_cluster_tick_moves_the_hosts_uv_to_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """On the kit's tick only (the host checkout's one writer). PLANTED CONTROL: another repo's tick never does."""
    calls, follow = _recorder('')
    monkeypatch.setattr(tick, 'follow_pin', follow)
    monkeypatch.setattr(tick.shutil, 'which', lambda _name: '/opt/tools/uv')
    assert tick.follow_uv('dev-lab') == ''
    assert calls == [('/opt/tools/uv', tick.uv_version())]
    assert tick.follow_uv('some-repo') == ''
    assert len(calls) == 1


def test_a_cluster_deploy_moves_a_present_uv_to_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, follow = _recorder('uv 0.12.5 at /u/uv did not follow to 0.13.7')
    monkeypatch.setattr(checks, 'follow_pin', follow)
    monkeypatch.setattr(checks.shutil, 'which', lambda _name: '/u/uv')
    assert checks.follow_uv() == 'uv 0.12.5 at /u/uv did not follow to 0.13.7'
    monkeypatch.setattr(checks.shutil, 'which', lambda _name: None)
    assert checks.follow_uv() == '', 'PLANTED CONTROL: no uv yet is the installer step, not a follow'
    assert len(calls) == 1


def test_an_ops_upgrade_moves_the_hosts_uv_to_the_new_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pin is the NEWLY installed dev-lab's, read in a fresh ``[ops] python``; a refused probe follows nothing."""
    calls, follow = _recorder('')
    monkeypatch.setattr(upgrade, 'follow_pin', follow)
    config = SimpleNamespace(python='/py', upgrade=SimpleNamespace(uv='/opt/uv'))
    assert upgrade.follow_uv(config, lambda _argv: (0, '0.13.7\n')) == ''
    assert calls == [('/opt/uv', '0.13.7')]
    assert upgrade.follow_uv(config, lambda _argv: (1, '')) == 'the new pin is unreadable; uv left as it is'
    assert len(calls) == 1, 'PLANTED CONTROL'


def test_the_pin_lagging_the_newest_release_is_named() -> None:
    assert uvfollow.lag('0.12.5', '0.13.7') == 'the uv pin 0.12.5 lags the newest release 0.13.7'
    assert uvfollow.lag('0.13.7', '0.13.7') == ''


def test_family_check_names_the_kits_pin_lagging_the_newest_release() -> None:
    """PLANTED CONTROLS: a pin at the newest says nothing; an unreadable release list is named, never silent."""

    def offline() -> str:
        msg = 'offline'
        raise OSError(msg)

    assert [f.what for f in watch.uv_pin('0.12.5', lambda: '0.13.7')] == [
        'uv pin: the uv pin 0.12.5 lags the newest release 0.13.7 -- the serve relock raises it; run it'
    ]
    assert watch.uv_pin('0.13.7', lambda: '0.13.7') == []
    assert watch.uv_pin('0.13.7', offline)[0].what.startswith('unread:')
