"""HOST PRESSURE IS MEASURED ONE WAY (D54): each reading alarms over its line and stays silent under it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

from dev_lab.supervise.pressure import (
    CGROUP_ROOT,
    PSI,
    THRESHOLDS,
    Declared,
    Measured,
    consumers,
    measure,
    parse_psi,
    tree_bytes,
)

GB = 1024**3


class Disk(NamedTuple):
    total: int
    used: int
    free: int


EVENTS = 'low 0\nhigh {high}\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n'
PSI_TEXT = (
    'some avg10=1.00 avg60={some:.2f} avg300=1.00 total=1\nfull avg10=0.00 avg60={full:.2f} avg300=0.00 total=1\n'
)


def _files(table: dict[Path, str]) -> Callable[[Path], str | None]:
    return table.get


def _linux(files: dict[Path, str], declared: Declared, previous: dict | None = None) -> Measured:
    return measure(declared, previous or {}, now=1000.0, read=_files(files), linux=True)


def test_a_cgroup_whose_high_counter_jumps_alarms_and_a_flat_one_does_not() -> None:
    """The 2026-11-01 incident: memory.high hit 151,572 times while host RAM read ~80%. PLANTED CONTROL: flat."""
    service = 'gitea-runner.service'
    events = CGROUP_ROOT / service / 'memory.events'
    declared = Declared(services=(service,))
    first = _linux({events: EVENTS.format(high=100)}, declared)
    assert first.findings == []  # a first reading is a baseline, never a delta
    jumped = _linux({events: EVENTS.format(high=151_672)}, declared, first.memo)
    assert [(f.kind, f.severity) for f in jumped.findings] == [(f'cgroup:{service}:high', 'warning')]
    assert '151572' in jumped.findings[0].measurement
    flat = _linux({events: EVENTS.format(high=151_672)}, declared, jumped.memo)
    assert flat.findings == []
    assert flat.readings[f'cgroup:{service}:high_delta'] == 0


def test_psi_over_its_line_alarms_under_it_does_not_and_absent_is_unmeasurable_not_zero() -> None:
    """PLANTED CONTROL: the same files under the line; and a host with no PSI reads None, never 0."""
    over = {PSI['memory']: PSI_TEXT.format(some=42, full=7), PSI['cpu']: PSI_TEXT.format(some=80, full=0)}
    kinds = {f.kind: f.severity for f in _linux(over, Declared()).findings}
    assert kinds == {'psi:memory:some': 'warning', 'psi:memory:full': 'critical', 'psi:cpu:some': 'warning'}
    under = {PSI['memory']: PSI_TEXT.format(some=1, full=0), PSI['cpu']: PSI_TEXT.format(some=3, full=0)}
    assert _linux(under, Declared()).findings == []
    absent = _linux({}, Declared())
    assert absent.findings == []
    assert absent.readings['psi:memory:some_avg60'] is None


def test_parse_psi_reads_avg60_per_line() -> None:
    assert parse_psi(PSI_TEXT.format(some=12.5, full=2)) == {'some_avg60': 12.5, 'full_avg60': 2.0}


def _tree(root: Path) -> None:
    big = root / '.claude' / 'worktrees' / 'stale-lane'
    big.mkdir(parents=True)
    (big / 'blob').write_bytes(b'x' * 50_000)
    (root / 'notes').mkdir()
    (root / 'notes' / 'a').write_bytes(b'x' * 10)


def test_a_disk_under_its_free_floor_alarms_naming_the_biggest_consumer_and_above_it_none(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same tree with free space above the floor raises nothing and names nobody."""
    _tree(tmp_path)
    declared = Declared(paths=(tmp_path,))
    low = measure(declared, {}, now=0.0, usage=lambda _p: Disk(100 * GB, 98 * GB, 2 * GB), linux=False,
                  psutil=lambda: None)  # fmt: skip
    (alarm,) = low.findings
    assert (alarm.kind, alarm.severity) == (f'disk:{tmp_path.as_posix()}', 'critical')
    assert (alarm.consumers[0].path, alarm.consumers[0].owned) == (
        (tmp_path / '.claude/worktrees/stale-lane').as_posix(),
        True,
    )
    assert any(c.path.endswith('notes') and not c.owned for c in alarm.consumers)
    roomy = measure(declared, {}, now=0.0, usage=lambda _p: Disk(100 * GB, 50 * GB, 50 * GB), linux=False,
                    psutil=lambda: None)  # fmt: skip
    assert roomy.findings == []


def test_a_disk_filling_fast_alarms_on_days_to_full_before_it_is_nearly_full(tmp_path: Path) -> None:
    """20 GB free, 10 GB written per day: full in two days, under the three-day floor. Control: a flat disk."""
    declared = Declared(paths=(tmp_path,))
    day = 86400.0
    past = {'disk': {tmp_path.as_posix(): [[day - 3600.0, 80.0 * GB - 10.0 * GB / 24]]}}
    filling = measure(declared, past, now=day, usage=lambda _p: Disk(100 * GB, 80 * GB, 20 * GB), linux=False,
                      psutil=lambda: None, sizes=lambda _r: ())  # fmt: skip
    assert [f.severity for f in filling.findings] == ['warning']
    assert filling.readings[f'disk:{tmp_path.as_posix()}:days_to_full'] == 2.0
    flat = {'disk': {tmp_path.as_posix(): [[day - 3600.0, 80.0 * GB]]}}
    still = measure(declared, flat, now=day, usage=lambda _p: Disk(100 * GB, 80 * GB, 20 * GB), linux=False,
                    psutil=lambda: None)  # fmt: skip
    assert still.findings == []


def test_a_workstation_averages_psutil_over_a_window_and_never_reads_psi() -> None:
    """The 50 ms sample on two cores misfired; the reading is averaged over the named window. Control: idle."""
    asked: list[float] = []

    def fake(cpu: float, ram: float) -> Callable[[], Any]:
        def cpu_percent(interval: float) -> float:
            asked.append(interval)
            return cpu

        return lambda: SimpleNamespace(cpu_percent=cpu_percent, virtual_memory=lambda: SimpleNamespace(percent=ram))

    busy = measure(Declared(), {}, now=0.0, linux=False, psutil=fake(97.0, 50.0))
    assert [f.kind for f in busy.findings] == ['cpu:percent']
    assert asked == [THRESHOLDS['psutil_window_s']]
    assert busy.readings['psi:memory:some_avg60'] is None
    assert measure(Declared(), {}, now=0.0, linux=False, psutil=fake(20.0, 50.0)).findings == []
    assert measure(Declared(), {}, now=0.0, linux=False, psutil=lambda: None).readings['cpu:percent'] is None


def test_every_threshold_is_overridable_by_its_name_in_the_machine_file() -> None:
    declared = Declared.of({'paths': ['/'], 'services': ['x.service'], 'psi_cpu_some_avg60': 5})
    assert declared.limits['psi_cpu_some_avg60'] == 5.0
    assert declared.limits['disk_free_floor_gb'] == THRESHOLDS['disk_free_floor_gb']
    assert (declared.paths, declared.services) == ((Path('/'),), ('x.service',))


def test_consumers_name_an_owned_tree_per_child(tmp_path: Path) -> None:
    _tree(tmp_path)
    assert any(c.path.endswith('.claude/worktrees/stale-lane') and c.owned for c in consumers([tmp_path]))


def test_a_disk_alarm_stands_when_its_consumers_cannot_be_read(tmp_path: Path) -> None:
    """A pressed disk whose consumer walk fails keeps its alarm, with no consumers -- never a vanished alarm."""

    def unreadable(_roots: object) -> tuple:
        why = 'permission denied'
        raise OSError(why)

    low = measure(Declared(paths=(tmp_path,)), {}, now=0.0, usage=lambda _p: Disk(100 * GB, 98 * GB, 2 * GB),
                  linux=False, psutil=lambda: None, sizes=unreadable)  # fmt: skip
    assert [(f.severity, f.consumers) for f in low.findings] == [('critical', ())]


def test_the_consumer_walk_is_bounded_by_its_budget(tmp_path: Path) -> None:
    """Control: an unspent budget sizes the whole tree; a spent one stops and reads a lower bound."""
    for name in range(20):
        (tmp_path / f'f{name}').write_bytes(b'x' * 100)
    device = tmp_path.lstat().st_dev
    assert tree_bytes(tmp_path, [10_000], device) == 2000
    assert tree_bytes(tmp_path, [5], device) < 2000


def test_a_child_on_another_device_than_its_declared_root_is_never_a_consumer(tmp_path: Path) -> None:
    """F-45930ad71de2: /proc under / (kcore ~128 TiB) is not this disk. PLANTED CONTROL: the same child, same device."""
    _tree(tmp_path)
    proc = tmp_path / 'proc'
    proc.mkdir()
    (proc / 'kcore').write_bytes(b'x' * 1_000_000)
    home = tmp_path.lstat().st_dev
    elsewhere = consumers([tmp_path], device=lambda p: home + 1 if p == proc else home)
    assert all(not c.path.endswith('/proc') for c in elsewhere)
    assert consumers([tmp_path])[0].path.endswith('/proc')


def test_two_readings_seconds_apart_are_not_a_trend(tmp_path: Path) -> None:
    """F-3829b028dda5: 100 MB written in 5 s on a half-empty disk is a burst, not 'full in 0.0 days'."""
    burst = {'disk': {tmp_path.as_posix(): [[0.0, 100e9]]}}
    half = measure(Declared(paths=(tmp_path,)), burst, now=5.0, usage=lambda _p: Disk(200 * GB, int(100.1e9), 50 * GB),
                   linux=False, psutil=lambda: None)  # fmt: skip
    assert half.findings == []
    assert half.readings[f'disk:{tmp_path.as_posix()}:days_to_full'] is None


def test_days_to_full_warns_at_the_real_cadence(tmp_path: Path) -> None:
    """F-9152150e82b5 (HIGH): 300 s readings of a disk filling 50 GB/h with 100 GB free warn within the window.

    PLANTED CONTROL: the same cadence on a flat disk never warns.
    """
    declared = Declared(paths=(tmp_path,))

    def run(rate: float) -> list[str | None]:
        memo: dict = {}
        said: list[str | None] = []
        for tick in range(20):
            used = 300 * GB + int(rate * tick * 300)
            done = measure(declared, memo, now=tick * 300.0, usage=lambda _p, u=used: Disk(500 * GB, u, 500 * GB - u),
                           linux=False, psutil=lambda: None, sizes=lambda _r: ())  # fmt: skip
            memo = done.memo
            said.append(done.findings[0].severity if done.findings else None)
        return said

    filling = run(50 * GB / 3600)
    assert 'warning' in filling
    assert filling[: int(THRESHOLDS['slope_span_s'] // 300)] == [None] * int(THRESHOLDS['slope_span_s'] // 300)
    assert run(0.0) == [None] * 20
