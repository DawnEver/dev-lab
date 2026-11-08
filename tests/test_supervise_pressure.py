"""HOST PRESSURE IS MEASURED ONE WAY (D54): each reading alarms over its line and stays silent under it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

from dev_lab.supervise.cgroup import CGROUP_MOUNT
from dev_lab.supervise.consumers import consumers, tree_bytes
from dev_lab.supervise.pressure import (
    PSI,
    THRESHOLDS,
    Declared,
    Measured,
    measure,
)
from dev_lab.supervise.reading import parse_psi

GB = 1024**3


class Disk(NamedTuple):
    total: int
    used: int
    free: int


EVENTS = 'low 0\nhigh {high}\nmax 0\noom 0\noom_kill {oom_kill}\noom_group_kill 0\n'
STAT = 'anon 35000000\nfile 105000000\nworkingset_refault_anon {anon}\nworkingset_refault_file 900\n'
PSI_TEXT = (
    'some avg10=1.00 avg60={some:.2f} avg300=1.00 total=1\nfull avg10=0.00 avg60={full:.2f} avg300=0.00 total=1\n'
)
GROUP_PSI = (
    'some avg10={some:.2f} avg60=0.00 avg300=0.00 total=1\nfull avg10={full:.2f} avg60=0.00 avg300=0.00 total=1\n'
)


def _events(high: int = 0, oom_kill: int = 0) -> str:
    return EVENTS.format(high=high, oom_kill=oom_kill)


def _files(table: dict[Path, str]) -> Callable[[Path], str | None]:
    return table.get


RUNNERS = '/ci.slice/ci-runners.slice'


def _systemd(units: dict[str, str]) -> Callable[[str], str]:
    """A fake ``systemctl show <unit> -p ControlGroup --value``: a known unit's group, else the refusal."""

    def locate(unit: str) -> str:
        if unit not in units:
            msg = f'systemctl knows no ControlGroup for {unit}'
            raise LookupError(msg)
        return units[unit]

    return locate


def _linux(
    files: dict[Path, str], declared: Declared, previous: dict | None = None, units: dict[str, str] | None = None
) -> Measured:
    located = units if units is not None else {s: f'{RUNNERS}/{s}' for s in declared.services}
    return measure(declared, previous or {}, now=1000.0, read=_files(files), linux=True, locate=_systemd(located))


def _group(service: str, high: int = 0, oom_kill: int = 0, anon: int = 0, psi: tuple[float, float] = (0, 0)) -> dict:
    """The three files of *service*'s cgroup under the runners slice."""
    root = CGROUP_MOUNT / RUNNERS.lstrip('/') / service
    return {
        root / 'memory.events': _events(high, oom_kill),
        root / 'memory.stat': STAT.format(anon=anon),
        root / 'memory.pressure': GROUP_PSI.format(some=psi[0], full=psi[1]),
    }


SERVICE = 'forge-runner-light.service'


def test_a_high_rise_alone_is_routine_reclaim_and_never_alarms() -> None:
    """2026-11-06 forge-a1: memory.high +252 at 139 MB of 1 GB, oom_kill 0, refault_anon 0 -- cache reclaim."""
    declared = Declared(services=(SERVICE,))
    first = _linux(_group(SERVICE, high=100), declared)
    assert first.findings == []  # a first reading is a baseline, never a delta
    routine = _linux(_group(SERVICE, high=352), declared, first.memo)
    assert routine.findings == []
    assert routine.readings[f'cgroup:{SERVICE}:high_delta'] == 252


def test_the_high_line_is_an_opt_in_that_alarms_past_its_rise() -> None:
    """PLANTED CONTROL for the default: the same +252 alarms once a host declares ``cgroup_high_rise``."""
    declared = Declared.of({'services': [SERVICE], 'cgroup_high_rise': 100})
    first = _linux(_group(SERVICE, high=100), declared)
    risen = _linux(_group(SERVICE, high=352), declared, first.memo)
    assert [(f.kind, f.severity, f.value) for f in risen.findings] == [(f'cgroup:{SERVICE}:high', 'warning', '+252')]


def test_an_oom_kill_rise_alarms_critical_and_names_its_signal() -> None:
    declared = Declared(services=(SERVICE,))
    first = _linux(_group(SERVICE, high=100), declared)
    killed = _linux(_group(SERVICE, high=352, oom_kill=1), declared, first.memo)
    assert [(f.kind, f.severity) for f in killed.findings] == [(f'cgroup:{SERVICE}:oom_kill', 'critical')]
    assert 'oom_kill rose by 1' in killed.findings[0].measurement


def test_an_anon_refault_rise_alarms_and_a_flat_one_does_not() -> None:
    """The 2026-09-14 throttle signature: anon pages thrashed back in. PLANTED CONTROL: flat refaults."""
    declared = Declared(services=(SERVICE,))
    first = _linux(_group(SERVICE, anon=10), declared)
    thrashed = _linux(_group(SERVICE, high=5000, anon=4010), declared, first.memo)
    kinds = [(f.kind, f.severity) for f in thrashed.findings]
    assert kinds == [(f'cgroup:{SERVICE}:workingset_refault_anon', 'warning')]
    assert 'workingset_refault_anon rose by 4000' in thrashed.findings[0].measurement
    assert _linux(_group(SERVICE, high=9000, anon=4010), declared, thrashed.memo).findings == []


def test_cgroup_memory_psi_over_its_line_alarms_and_under_it_does_not() -> None:
    """PLANTED CONTROL: the same group at avg10 under both lines is silent."""
    declared = Declared(services=(SERVICE,))
    over = _linux(_group(SERVICE, psi=(25.0, 8.0)), declared)
    kinds = {f.kind: (f.severity, f.value) for f in over.findings}
    assert kinds == {
        f'cgroup:{SERVICE}:psi_some': ('warning', '25.0%'),
        f'cgroup:{SERVICE}:psi_full': ('critical', '8.0%'),
    }
    under = _linux(_group(SERVICE, psi=(9.0, 4.0)), declared)
    assert under.findings == []
    assert under.readings[f'cgroup:{SERVICE}:psi_memory_some_avg10'] == 9.0


def test_a_unit_in_a_nested_slice_is_read_where_systemd_says_it_lives() -> None:
    """2026-11-02: the runners moved to /ci.slice/ci-runners.slice; the alarm reads there, nowhere else."""
    service = 'gitea-runner.service'
    nested = CGROUP_MOUNT / 'ci.slice' / 'ci-runners.slice' / service / 'memory.events'
    old = Path('/sys/fs/cgroup/system.slice') / service / 'memory.events'
    declared = Declared(services=(service,))
    first = _linux({nested: _events(oom_kill=1), old: _events(oom_kill=1)}, declared)
    jumped = _linux({nested: _events(oom_kill=9), old: _events(oom_kill=1)}, declared, first.memo)
    assert [f.kind for f in jumped.findings] == [f'cgroup:{service}:oom_kill']


def test_the_old_system_slice_guess_is_never_consulted() -> None:
    """PLANTED CONTROL: a file only at the old hard-coded path, and systemd placing the unit elsewhere."""
    service = 'gitea-runner.service'
    old = Path('/sys/fs/cgroup/system.slice') / service / 'memory.events'
    done = _linux({old: _events(oom_kill=5)}, Declared(services=(service,)))
    assert done.memo['cgroup'] == {}
    assert [(f.kind, f.severity) for f in done.findings] == [(f'cgroup:{service}', 'warning')]


def test_a_slice_unit_is_read_at_its_own_group() -> None:
    slice_unit = 'ci-runners.slice'
    events = CGROUP_MOUNT / 'ci.slice' / slice_unit / 'memory.events'
    declared = Declared(services=(slice_unit,))
    units = {slice_unit: f'/ci.slice/{slice_unit}'}
    first = _linux({events: _events()}, declared, units=units)
    jumped = _linux({events: _events(oom_kill=3)}, declared, first.memo, units=units)
    assert [(f.kind, f.severity) for f in jumped.findings] == [(f'cgroup:{slice_unit}:oom_kill', 'critical')]


def test_an_unresolvable_or_unreadable_unit_is_a_warning_never_a_silent_none() -> None:
    gone, unread = 'gone.service', 'unread.service'
    done = _linux({}, Declared(services=(gone, unread)), units={unread: f'{RUNNERS}/{unread}'})
    by_kind = {f.kind: f for f in done.findings}
    assert {k: f.severity for k, f in by_kind.items()} == {f'cgroup:{gone}': 'warning', f'cgroup:{unread}': 'warning'}
    assert 'systemctl knows no ControlGroup' in by_kind[f'cgroup:{gone}'].measurement
    assert 'the alarm cannot see it' in by_kind[f'cgroup:{unread}'].measurement
    assert done.readings[f'cgroup:{gone}'] is None


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


def test_parse_psi_reads_every_window_per_line() -> None:
    parsed = parse_psi(PSI_TEXT.format(some=12.5, full=2))
    assert (parsed['some_avg60'], parsed['full_avg60'], parsed['some_avg10']) == (12.5, 2.0, 1.0)


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
    past = {'disk': {tmp_path.as_posix(): [[day - 10800.0, 80.0 * GB - 10.0 * GB / 8]]}}  # 3 h: past what 2 days needs
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


def test_an_hour_of_writes_never_projects_days_ahead(tmp_path: Path) -> None:
    """forge-a1 2026-11-08 03:30Z: ~1.4 GB written within one hour on 84.6 GB free read 'full in 2.5 days'.

    A slope is extrapolated at most `slope_extrapolation_max` times the span it was measured over.
    PLANTED CONTROL: the same rate held for the hours a 2.5-day projection needs does warn.
    """
    declared = Declared(paths=(tmp_path,))
    used, free = 12 * GB, int(84.6 * GB)
    rate = free / (2.5 * 86400)  # bytes per second that read 'full in 2.5 days'

    def at(span: float) -> Measured:
        past = {'disk': {tmp_path.as_posix(): [[0.0, used - rate * span]]}}
        return measure(declared, past, now=span, usage=lambda _p: Disk(96 * GB, used, free), linux=False,
                       psutil=lambda: None, sizes=lambda _r: ())  # fmt: skip

    hour = at(3600.0)
    assert hour.findings == []
    assert hour.readings[f'disk:{tmp_path.as_posix()}:days_to_full'] is None
    held = at(2.5 * 86400 / THRESHOLDS['slope_extrapolation_max'])
    assert [f.severity for f in held.findings] == ['warning']


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
