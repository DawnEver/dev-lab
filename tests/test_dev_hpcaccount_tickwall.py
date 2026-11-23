"""A cron tick is BOUNDED: its own lock, a holder record naming its phase, and a wall it ends itself at.

Measured 2026-11-23: one tick in a gather's tenth retry round held the lock for hours and silenced the host.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dev_lab.dev import hpcaccount, tickholder
from dev_lab.dev.hpcaccount import tick, tickwall

#: A serve that names its own phase in the record its tick handed it, then outlives any wall a test sets.
_SLOW = (
    'import time\n'
    'from dev_lab.dev.tickholder import phase\n'
    "phase('advancing the cluster run of abc123 (submitted)')\n"
    'time.sleep(60)\n'
)


def _wall(tmp_path: Path, wall_s: float) -> tickwall.Wall:
    record = tmp_path / 'alpha.lock.holder'
    tickholder.write(record, tickholder.Holder(1, None, '2026-11-23T09:57:00+00:00', wall_s, 'alpha'))
    return tickwall.Wall(record, wall_s)


def test_a_serve_past_the_wall_is_ended_and_the_line_names_the_phase_it_was_in(tmp_path: Path) -> None:
    lines: list[str] = []
    ran = tickwall.within([sys.executable, '-c', _SLOW], cwd=tmp_path, wall=_wall(tmp_path, 3.0), say=lines.append,
                          grace_s=5.0)  # fmt: skip
    assert ran.returncode == tickwall.WALL
    [line] = lines
    assert line.startswith('tick: ended at its wall after ')
    assert line.endswith(' s doing advancing the cluster run of abc123 (submitted)'), line


def test_planted_control_a_serve_inside_its_wall_keeps_its_own_exit_and_prints_nothing(tmp_path: Path) -> None:
    lines: list[str] = []
    ran = tickwall.within([sys.executable, '-c', 'raise SystemExit(3)'], cwd=tmp_path, wall=_wall(tmp_path, 120.0),
                          say=lines.append)  # fmt: skip
    assert ran.returncode == 3
    assert lines == []


def test_the_holder_record_lives_exactly_while_the_lock_is_held(tmp_path: Path) -> None:
    lock = tmp_path / 'serve' / 'alpha.lock'
    seen: list[tickholder.Holder | None] = []

    def body(wall: tickwall.Wall) -> int:
        wall.phase('refreshing alpha')
        seen.append(tickholder.read(tickholder.record_of(lock)))
        return 0

    assert tickwall.locked(lock, 'alpha', 2400.0, body) == 0
    [holder] = seen
    assert holder is not None
    assert (holder.repo, holder.wall_s, holder.phase) == ('alpha', 2400.0, 'refreshing alpha')
    assert not tickholder.record_of(lock).exists(), 'a released lock leaves no record behind'


def test_a_stopped_tick_ends_naming_its_phase_and_releases_the_lock(tmp_path: Path) -> None:
    lock = tmp_path / 'alpha.lock'
    lines: list[str] = []

    def body(wall: tickwall.Wall) -> int:
        wall.phase('serving alpha')
        raise tickwall.TickStopped

    assert tickwall.locked(lock, 'alpha', 60.0, body, say=lines.append) == tickwall.STOPPED
    assert lines[-1].startswith('tick: stopped after ')
    assert lines[-1].endswith('doing serving alpha')
    assert tickwall.locked(lock, 'alpha', 60.0, lambda _wall: 0) == 0, 'the lock was let go'


def test_the_cli_tick_runs_under_the_lock_and_wall_its_cron_line_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    walls: list[tickwall.Wall | None] = []
    monkeypatch.setattr(tick, 'tick', lambda _name, **kw: walls.append(kw['wall']) or 0)
    lock = tmp_path / 'alpha.lock'
    assert hpcaccount.main(['tick', 'alpha', '--lock', str(lock), '--wall-minutes', '7']) == 0
    [wall] = walls
    assert wall is not None
    assert wall.wall_s == 420.0
    assert wall.record == tickholder.record_of(lock)
    walls.clear()
    assert hpcaccount.main(['tick', 'alpha']) == 0
    assert walls == [None], 'PLANTED CONTROL: no --lock, no wall'
