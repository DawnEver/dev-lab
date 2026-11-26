"""HOST PRESSURE -- disk, memory and CPU pressure measured ONE way, for supervision and the forge tick (D54).

User ruling D54 (2026-11-01): a pressed host must tell the agent on it that can clean up, and the humans. The
incident that set the bar: the Gitea runner's cgroup hit ``memory.high`` 151,572 times at load 5.5 while HOST
RAM read ~80% -- so a host-level percentage is not the measurement. What is:

* DISK -- per declared path: percent used, free bytes against a floor, and DAYS TO FULL from a short history
  of readings (a slope, so a disk filling fast alarms before it is nearly full);
* LINUX MEMORY/CPU -- PSI (``/proc/pressure/memory`` ``some``/``full avg60``, ``/proc/pressure/cpu`` ``some
  avg60``): the share of time work STALLED, which is what the runner felt; and per declared systemd service its
  cgroup's REAL pressure: a rise of ``memory.events`` ``oom_kill``/``oom``/``max``, a rise of ``memory.stat``
  ``workingset_refault_anon`` (anonymous pages thrashed back in), or its ``memory.pressure`` avg10 over a line.
  The ``high`` counter ALONE is never pressure (2026-11-06, forge-a1: +252 at 139 MB of a 1 GB memory.high, 105
  MB of it file cache, oom_kill 0, refault_anon 0 -- the kernel reclaiming git-mirror cache at the line, routine).
  The throttle signature is high large WITH anon refaults (2026-09-14); ``cgroup_high_rise`` is an opt-in line;
* A WORKSTATION (Windows, macOS) -- psutil AVERAGED over a window: a 50 ms ``cpu_percent`` sample on two cores
  is noise, which is why CPU was off. Where PSI is absent the PSI reading is UNMEASURABLE (``None``), never 0.

Every threshold is a named constant, overridable by the same name in the machine file's ``[pressure]`` table
(:func:`thresholds`). A size, a duration or a percentage is declared WITH its unit (``disk_free_floor =
"10 GiB"``, ``psutil_window = "5 s"``, ``disk_ceiling = "90 %"``) and read once by
:func:`lab_commons.quantity.parse`; a key that spells its unit (``disk_free_floor_gb``, ``disk_percent_ceiling``) is
refused with the line that replaces it (user ruling 2026-11-25). PSI lines (``psi_*_avg60``) stay plain percent
numbers: ``avg60`` is the kernel's field name, not a unit.
This module MEASURES AND REPORTS; it never deletes (:mod:`dev_lab.supervise.components.
resources` rules that) -- the remedy it carries is the biggest consumers (:mod:`dev_lab.supervise.consumers`)
and the family's cleanup doors.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from lab_commons.quantity import Renamed, parse, refuse_renamed

from dev_lab.supervise.cgroup import cgroups, control_group
from dev_lab.supervise.consumers import Consumer, consumers
from dev_lab.supervise.reading import Finding, parse_psi

__all__ = [
    'DOORS',
    'RAM_CRITICAL',
    'SERVER_DOORS',
    'THRESHOLDS',
    'Declared',
    'Measured',
    'measure',
    'thresholds',
]

#: Where the box's RAM counts as full -- supervision's ``ProcessMonitor`` ceiling and a workstation's, one source.
RAM_CRITICAL: Final = 95

_GIB: Final = 1024**3
_DAY: Final = 86400.0

#: The defaults, each overridable by its own name in ``[pressure]``. Percent values are PSI ``avg60`` (the
#: share of the last minute some/all tasks stalled) or psutil's percent; a size is held in bytes and a duration in
#: seconds (:data:`QUANTITIES` names which), each declared with its unit.
THRESHOLDS: Final[Mapping[str, float]] = {
    'disk_free_floor': 10.0 * _GIB,  # below this much free on a declared path: critical
    'disk_ceiling': 0.90,  # past this fraction used: warning
    'full_horizon': 3 * _DAY,  # filling so fast it is full within this long: warning
    'psi_memory_some_avg60': 10.0,  # some task stalled on memory this share of the last minute
    'psi_memory_full_avg60': 5.0,  # EVERY task stalled on memory: critical
    'psi_cpu_some_avg60': 50.0,  # runnable work waited for a CPU half the last minute
    'cpu_ceiling': 0.90,  # a workstation's CPU, averaged over the window
    'memory_ceiling': RAM_CRITICAL / 100,  # a workstation's RAM: supervision's own ceiling, one source
    'psutil_window': 5.0,  # the averaging window on a workstation; never a 50 ms sample
    # THE CADENCE AND THE SLOPE, ONE SOURCE: a writer reads every `interval` (a writer passes its own: the
    # forge tick's `[schedule]` tick, supervision's `cycle.interval`); a days-to-full slope is believed
    # only over at least `slope_span`, and the disk history is kept BY AGE -- `slope_span + interval` --
    # so at any cadence the window holds a reading old enough to meet the floor.
    'interval': 300.0,
    'slope_span': 3600.0,
    # A SLOPE PROJECTS AT MOST THIS MANY TIMES THE SPAN IT WAS MEASURED OVER: one hour of a 1.4 GB export read
    # 'full in 2.5 days' on forge-a1 (2026-11-08). History is kept long enough to meet `full_horizon`.
    'slope_extrapolation_max': 24.0,
    # A CGROUP'S REAL PRESSURE. `high` alone is routine cache reclaim at memory.high: it alarms only past an
    # opt-in rise (default never); anon refaults and the cgroup's own memory PSI (avg10) are the throttle.
    'cgroup_high_rise': float('inf'),  # warning when memory.events `high` rose by MORE than this between readings
    'cgroup_refault_anon_rise': 0.0,  # warning when memory.stat workingset_refault_anon rose by more than this
    'cgroup_psi_memory_some_avg10': 10.0,  # the cgroup's memory.pressure `some avg10`: warning
    'cgroup_psi_memory_full_avg10': 5.0,  # the cgroup's memory.pressure `full avg10`: critical
}

#: The thresholds declared WITH a unit, and their dimension (:mod:`lab_commons.quantity`); every other is a number.
QUANTITIES: Final[Mapping[str, str]] = {
    'disk_free_floor': 'size',
    'full_horizon': 'duration',
    'disk_ceiling': 'fraction',
    'cpu_ceiling': 'fraction',
    'memory_ceiling': 'fraction',
    'psutil_window': 'duration',
    'interval': 'duration',
    'slope_span': 'duration',
}
#: Unit-suffixed keys retired by the 2026-11-25 ruling, refused with the line that replaces them; never read.
RENAMED: Final[Mapping[str, Renamed]] = {
    'disk_free_floor_gb': Renamed('disk_free_floor', 'GiB'),
    'days_to_full_floor': Renamed('full_horizon', 'd'),
    'disk_percent_ceiling': Renamed('disk_ceiling', '%'),
    'cpu_percent_ceiling': Renamed('cpu_ceiling', '%'),
    'memory_percent_ceiling': Renamed('memory_ceiling', '%'),
    'psutil_window_s': Renamed('psutil_window', 's'),
    'interval_s': Renamed('interval', 's'),
    'slope_span_s': Renamed('slope_span', 's'),
}

#: The PSI files, by resource.
PSI: Final[Mapping[str, Path]] = {'memory': Path('/proc/pressure/memory'), 'cpu': Path('/proc/pressure/cpu')}

#: A slope needs two readings.
_SLOPE_POINTS: Final = 2

#: The family's cleanup doors, in the order an agent should try them. None is run by this module.
DOORS: Final = (
    'python -m dev_lab.dev.branchset --apply  (landed branches and their worktrees)',
    'python -m dev_lab.dev.retention --apply  (the forge runs this host left behind)',
    "the repo's clean runner (output/logs retention)",
)
#: A server the integrator owns (``[pressure] owner = "integrator"``) is cleaned from outside, through the ops door.
SERVER_DOORS: Final = (
    'python -m dev_lab.dev.opsserver <server> disk  (read-only: df, the largest directories, journal, docker)',
    'python -m dev_lab.dev.opsserver <server> clean  (journal to its retention, apt, gitea caches, docker prune)',
)


def thresholds(table: Mapping[str, Any]) -> dict[str, float]:
    """:data:`THRESHOLDS`, each overridden by the same key in *table* (the machine file's ``[pressure]``).

    Raises:
        lab_commons.quantity.QuantityRefused: a retired unit-suffixed key, or a size/duration without its unit.

    """
    refuse_renamed('[pressure]', table, RENAMED)
    found = {}
    for name, default in THRESHOLDS.items():
        if name not in table:
            found[name] = default
        elif name in QUANTITIES:
            found[name] = parse(f'[pressure] {name}', table[name], QUANTITIES[name], positive=True)
        else:
            found[name] = float(table[name])
    return found


@dataclass(frozen=True)
class Declared:
    """What one host watches: *paths* (disk), *services* (systemd units with a cgroup), and *limits*."""

    paths: tuple[Path, ...] = ()
    services: tuple[str, ...] = ()
    limits: Mapping[str, float] = field(default_factory=lambda: dict(THRESHOLDS))

    @classmethod
    def of(cls, table: Mapping[str, Any], *, interval: float | None = None) -> Declared:
        """From ``[pressure]``: ``paths``, ``services`` and any threshold by name.

        *interval* is the writer's own cadence in seconds, the default a declared ``interval`` overrides.
        """
        paths = tuple(Path(str(p)) for p in table.get('paths', ()))
        limits = thresholds(table)
        if interval is not None and 'interval' not in table:
            limits['interval'] = float(interval)
        return cls(paths, tuple(str(s) for s in table.get('services', ())), limits)


@dataclass
class Measured:
    """The findings, every reading (``None`` = unmeasurable here), and the memo the next reading compares to."""

    findings: list[Finding] = field(default_factory=list)
    readings: dict[str, float | None] = field(default_factory=dict)
    memo: dict[str, Any] = field(default_factory=dict)
    interval_s: float = THRESHOLDS['interval']


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return None


def _disk(
    path: Path, limits: Mapping[str, float], history: list[list[float]], now: float, usage: Callable[..., Any]
) -> tuple[list[Finding], dict[str, float | None], list[list[float]]]:
    name = path.as_posix()
    try:
        disk = usage(str(path))
    except OSError:
        return [], {f'disk:{name}:percent': None}, history
    if not disk.total:  # no size is unanswerable, never 0% full
        return [], {f'disk:{name}:percent': None}, history
    percent, free_gb = disk.used / disk.total * 100, disk.free / 1024**3
    horizon = limits['full_horizon'] / limits['slope_extrapolation_max']
    oldest = now - max(limits['slope_span'], horizon) - limits['interval']
    kept = [one for one in history if one[0] >= oldest] + [[now, float(disk.used)]]
    days = _days_to_full(kept, disk.free, limits['slope_span'], limits['slope_extrapolation_max'])
    readings = {f'disk:{name}:percent': round(percent, 1), f'disk:{name}:free_gb': round(free_gb, 2),
                f'disk:{name}:days_to_full': None if days is None else round(days, 1)}  # fmt: skip
    said = f'{name} {percent:.1f}% used, {free_gb:.1f} GB free' + (f', full in {days:.1f} days' if days else '')
    floor_gib, full_days = limits['disk_free_floor'] / _GIB, limits['full_horizon'] / _DAY
    ceiling = 100 * limits['disk_ceiling']
    if disk.free < limits['disk_free_floor']:
        return (
            [
                Finding(
                    f'disk:{name}',
                    'critical',
                    f'{said} (floor {floor_gib:g} GiB)',
                    metric=f'disk {name}',
                    value=f'{free_gb:.1f} GB free',
                    threshold=f'{floor_gib:g} GiB',
                )
            ],
            readings,
            kept,
        )
    if percent > ceiling or (days is not None and days < full_days):
        if percent > ceiling:
            value, bar = f'{percent:.0f}%', f'{ceiling:g}%'
        else:
            value, bar = f'full in {days:.1f} days', f'{full_days:g} days'
        found = Finding(f'disk:{name}', 'warning', said, metric=f'disk {name}', value=value, threshold=bar)
        return [found], readings, kept
    return [], readings, kept


def _days_to_full(history: Sequence[Sequence[float]], free: int, span: float, reach: float) -> float | None:
    """Days until *free* bytes are gone at the first-to-last slope.

    ``None`` when not filling, under *span*, or when the projection reaches past *reach* times the measured span.
    """
    if len(history) < _SLOPE_POINTS:
        return None
    (t0, used0), (t1, used1) = history[0], history[-1]
    if t1 - t0 < span:  # a burst seconds apart is not a trend
        return None
    rate = (used1 - used0) / (t1 - t0)  # bytes per second
    if rate <= 0 or free / rate > reach * (t1 - t0):  # an hour of writes is no evidence about next week
        return None
    return free / rate / 86400


def _psi(
    limits: Mapping[str, float], read: Callable[[Path], str | None]
) -> tuple[list[Finding], dict[str, float | None]]:
    checks = (('memory', 'some', 'warning'), ('memory', 'full', 'critical'), ('cpu', 'some', 'warning'))
    findings: list[Finding] = []
    readings: dict[str, float | None] = {}
    for resource, scope, severity in checks:
        text = read(PSI[resource])
        value = None if text is None else parse_psi(text).get(f'{scope}_avg60')
        readings[f'psi:{resource}:{scope}_avg60'] = value  # absent PSI is unmeasurable, never 0
        limit = limits[f'psi_{resource}_{scope}_avg60']
        if value is not None and value > limit:
            text = f'{resource} pressure {scope} avg60 {value:.1f}% > {limit:.1f}%'
            reading = {
                'metric': f'{resource} pressure {scope}',
                'value': f'{value:.1f}%',
                'threshold': f'{limit:.1f}%',
            }
            findings.append(Finding(f'psi:{resource}:{scope}', severity, text, **reading))
    return findings, readings


def _windowed(psutil: ModuleType | None, limits: Mapping[str, float]) -> tuple[list[Finding], dict[str, float | None]]:
    if psutil is None:
        return [], {'cpu:percent': None, 'memory:percent': None}
    cpu = float(psutil.cpu_percent(interval=limits['psutil_window']))  # averaged over the window
    memory = float(psutil.virtual_memory().percent)
    findings = [
        Finding(
            f'{name}:percent',
            'warning',
            f'{name} {value:.0f}% averaged over {limits["psutil_window"]:.0f}s',
            metric=name,
            value=f'{value:.0f}%',
            threshold=f'{100 * limits[f"{name}_ceiling"]:g}%',
        )
        for name, value in (('cpu', cpu), ('memory', memory))
        if value > 100 * limits[f'{name}_ceiling']
    ]
    return findings, {'cpu:percent': round(cpu, 1), 'memory:percent': round(memory, 1)}


def measure(
    declared: Declared,
    previous: Mapping[str, Any],
    *,
    now: float,
    read: Callable[[Path], str | None] = _read,
    usage: Callable[..., Any] = shutil.disk_usage,
    psutil: Callable[[], ModuleType | None] = lambda: None,
    linux: bool = sys.platform.startswith('linux'),
    sizes: Callable[[Sequence[Path]], tuple[Consumer, ...]] = consumers,
    locate: Callable[[str], str] = control_group,
) -> Measured:
    """One reading of everything *declared*, judged against its limits and the *previous* memo.

    Each seam is a fixture's way in: *read* a file's text, *usage* a disk, *psutil* the module's loader (a
    real reading passes :func:`~dev_lab.supervise.reading.psutil_module`; ``None`` is absent),
    *linux* whether PSI and cgroups are asked, *sizes* the consumers of a disk alarm, *locate* a
    declared unit's cgroup (systemd's ``ControlGroup``).
    """
    done = Measured(interval_s=declared.limits['interval'])
    histories = previous.get('disk', {})
    for path in declared.paths:
        found, readings, kept = _disk(path, declared.limits, histories.get(path.as_posix(), []), now, usage)
        done.memo.setdefault('disk', {})[path.as_posix()] = kept
        done.readings.update(readings)
        try:
            named = sizes([path]) if found else ()
        except OSError:
            named = ()  # the alarm stands without its consumers
        done.findings += [replace(f, consumers=named) for f in found]
    if linux:
        found, readings = _psi(declared.limits, read)
        done.findings += found
        done.readings.update(readings)
        found, readings, counts = cgroups(declared.services, previous.get('cgroup', {}), declared.limits, read, locate)
        done.findings += found
        done.readings.update(readings)
        done.memo['cgroup'] = counts
    else:
        done.readings.update({f'psi:{r}': None for r in ('memory:some_avg60', 'memory:full_avg60', 'cpu:some_avg60')})
        found, readings = _windowed(psutil(), declared.limits)
        done.findings += found
        done.readings.update(readings)
    return done
