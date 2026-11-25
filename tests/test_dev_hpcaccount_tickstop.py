"""``tick-stop``: a tick older than its wall is stopped, verified first; a younger one is refused by name.

Measured 2026-11-23: a hung tick held a verification account for hours with no door to see or stop it.
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import tickholder
from dev_lab.dev.hpcaccount import tickstop
from dev_lab.dev.hpcaccount.fleet import Target

NOW = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)
ME = 1000
TICK = '/r/repos/dev-lab/.venv/bin/python -m dev_lab.dev.hpcaccount tick alpha --lock /r/serve/alpha.lock'


def _held(root: Path, minutes: float, *, wall_min: float = 40.0) -> tickholder.Holder:
    since = (NOW - timedelta(minutes=minutes)).isoformat()
    holder = tickholder.Holder(4242, None, since, wall_min * 60, 'alpha', 'advancing the cluster run of abc123')
    tickholder.write(tickholder.record_of(root / 'serve' / 'alpha.lock'), holder)
    return holder


def _stop(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, command: str = TICK, owner: int = ME, alive: bool = True
) -> tuple[int, list[tuple[int, int]], list[str]]:
    monkeypatch.setattr(tickholder, 'alive', lambda _h: alive)
    killed: list[tuple[int, int]] = []
    said: list[str] = []
    code = tickstop.stop_here(
        root, 'alpha', now=lambda: NOW, read=lambda _pid: (command, owner), kill=lambda p, s: killed.append((p, s)),
        uid=ME, say=said.append,
    )  # fmt: skip
    return code, killed, said


def test_a_tick_past_its_wall_is_verified_then_sent_sigterm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _held(tmp_path, 63)
    code, killed, said = _stop(tmp_path, monkeypatch)
    assert code == 0
    assert killed == [(4242, signal.SIGTERM)]
    assert 'held by tick pid 4242' in said[0]
    assert 'stopped (SIGTERM)' in said[0]


def test_planted_control_a_tick_younger_than_its_wall_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _held(tmp_path, 10)
    code, killed, said = _stop(tmp_path, monkeypatch)
    assert (code, killed) == (2, [])
    assert 'refused -- younger than its wall (10 min of 40 min): it ends itself in 30 min' in said[0]


@pytest.mark.parametrize(('command', 'owner', 'why'), [
    ('/usr/bin/vim notes', ME, 'is not a tick of alpha'),
    (TICK.replace('tick alpha', 'tick beta'), ME, 'is not a tick of alpha'),
    (TICK, 0, "is not this user's process"),
])  # fmt: skip
def test_a_pid_that_is_not_this_users_tick_of_the_repo_is_never_signaled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, owner: int, why: str
) -> None:
    _held(tmp_path, 63)
    code, killed, said = _stop(tmp_path, monkeypatch, command=command, owner=owner)
    assert (code, killed) == (2, [])
    assert why in said[0]


def test_a_dead_holder_is_said_and_nothing_is_signaled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _held(tmp_path, 63)
    code, killed, said = _stop(tmp_path, monkeypatch, alive=False)
    assert (code, killed) == (0, [])
    assert 'its process is gone' in said[0]


def test_the_workstation_door_runs_the_accounts_own_kit_on_its_declared_host(monkeypatch: pytest.MonkeyPatch) -> None:
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(tickstop.look, 'reached_machine', lambda _u: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(tickstop, 'declared_target', lambda _g, _s: Target('login1', '/r'))
    ran: list[tuple[str, str]] = []

    def pin(_grant: object, host: str) -> Callable[[str, str | None], str]:
        return lambda command, _stdin: ran.append((host, command)) or 'tick-stop: alpha: ... stopped\nrc=0\n'

    said: list[str] = []
    assert tickstop.stop('u1', 'alpha', connect=lambda _g: None, pin=pin, say=said.append) == 0
    [(host, command)] = ran
    assert host == 'login1'
    assert 'dev_lab.dev.hpcaccount tick-stop-here --root /r --repo alpha' in command
    assert said == ['tick-stop: alpha: ... stopped']
    assert tickstop.stop('u1', 'a;rm -rf ~', connect=lambda _g: None, pin=pin, say=said.append) == 2, 'PLANTED'
    assert len(ran) == 1
