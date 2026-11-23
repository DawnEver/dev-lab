"""A cron tick is BOUNDED: its own lock, a holder record naming its phase, and a wall it ends itself at.

Measured 2026-11-23: one tick in a gather's tenth retry round held the lock for hours and silenced the host.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dev_lab.dev import hpcaccount, tickholder
from dev_lab.dev.hpcaccount import spec as deploy_spec
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


#: A tick of another process holding the lock, in a named phase, until killed.
_HOLDER = (
    'import sys, time\n'
    'from pathlib import Path\n'
    'from dev_lab.dev.hpcaccount.tickwall import locked\n'
    'def body(wall):\n'
    "    wall.phase('advancing the cluster run of abc123 (submitted)')\n"
    "    print('held', flush=True)\n"
    '    time.sleep(60)\n'
    "locked(Path(sys.argv[1]), 'alpha', 2400.0, body)\n"
)


def test_a_held_lock_names_its_holder_pid_age_and_phase(tmp_path: Path) -> None:
    lock = tmp_path / 'alpha.lock'
    first = subprocess.Popen([sys.executable, '-c', _HOLDER, str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == 'held'
        lines: list[str] = []
        seen: list[tickholder.Holder] = []
        assert tickwall.locked(lock, 'alpha', 60.0, lambda _w: 0, say=lines.append, on_held=seen.append) == (
            tickwall.HELD
        )
    finally:
        first.kill()
        first.wait(timeout=30)
    [line] = lines
    found = re.search(r'held by tick pid (\d+) since ', line)  # the venv launcher's child on Windows, not first.pid
    assert found, line
    assert line.endswith('in advancing the cluster run of abc123 (submitted) -- this tick does nothing (exit 75)')
    assert [holder.pid for holder in seen] == [int(found[1])], 'the live holder is handed on for the host card'


def test_planted_control_a_holder_that_wrote_no_record_is_said_so_and_never_published(tmp_path: Path) -> None:
    lock = tmp_path / 'alpha.lock'
    hold = 'import sys, time\nfrom pathlib import Path\nfrom dev_lab.dev.servelock import held\n'
    hold += "with held(Path(sys.argv[1])):\n    print('held', flush=True)\n    time.sleep(60)\n"
    first = subprocess.Popen([sys.executable, '-c', hold, str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == 'held'
        lines: list[str] = []
        seen: list[tickholder.Holder] = []
        assert tickwall.locked(lock, 'alpha', 60.0, lambda _w: 0, say=lines.append, on_held=seen.append) == (
            tickwall.HELD
        )
    finally:
        first.kill()
        first.wait(timeout=30)
    assert 'held by a process that wrote no holder record' in lines[0]
    assert seen == []


def test_a_dead_holders_lock_is_taken_over_by_name(tmp_path: Path) -> None:
    lock = tmp_path / 'alpha.lock'
    dead = tickholder.Holder(999_999, 1, '2026-11-23T09:57:00+00:00', 2400.0, 'alpha', 'serving alpha')
    tickholder.write(tickholder.record_of(lock), dead)
    lines: list[str] = []
    assert tickwall.locked(lock, 'alpha', 60.0, lambda _w: 0, say=lines.append) == 0
    assert lines == [
        '[tick] alpha: took over the lock of dead tick pid 999999 (since 2026-11-23T09:57:00+00:00, in serving alpha)'
    ]


def test_describe_reads_the_holders_age() -> None:
    holder = tickholder.Holder(42, None, '2026-11-23T09:57:00+00:00', 2400.0, 'alpha', 'serving alpha')
    now = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)
    assert tickholder.describe(holder, now) == (
        'held by tick pid 42 since 2026-11-23T09:57:00+00:00 (1 h 03 min) in serving alpha'
    )


def test_a_held_tick_marks_its_repos_host_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = deploy_spec.Repo(deploy_spec.KIT, 'https://f/o/dev-lab.git', 'trunk')
    alpha = deploy_spec.Repo('alpha', 'https://f/o/alpha.git', 'trunk')
    spec = deploy_spec.Deployment('h', str(tmp_path), '3.13', (lab, alpha))
    monkeypatch.setattr(tick, '_declared', lambda name, _path: (spec, alpha) if name == 'alpha' else f'{name}?')
    marked: list[tuple[Path, dict[str, object]]] = []
    holder = tickholder.Holder(42, None, '2026-11-23T09:57:00+00:00', 2400.0, 'alpha', 'serving alpha')
    line = tick.announce_held(
        'alpha', holder, config=tmp_path, mark=lambda c, _h, held: marked.append((c, held)) or 'updated'
    )
    assert line == '[tick] alpha: host card marked held (updated)'
    assert marked == [
        (deploy_spec.checkout_of(spec, alpha), {'pid': 42, 'since': holder.since, 'phase': 'serving alpha'})
    ]

    def refused(*_a: object) -> str:
        refusal = 'the forge refused the credential'
        raise OSError(refusal)

    assert 'not published: the forge refused' in tick.announce_held('alpha', holder, config=tmp_path, mark=refused)
