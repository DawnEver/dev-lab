"""HOST PRESSURE -- disk, memory and CPU pressure measured ONE way, for supervision and the forge tick (D54).

User ruling D54 (2026-11-01): a pressed host must tell the agent on it that can clean up, and the humans. The
incident that set the bar: the Gitea runner's cgroup hit ``memory.high`` 151,572 times at load 5.5 while HOST
RAM read ~80% -- so a host-level percentage is not the measurement. What is:

* DISK -- per declared path: percent used, free bytes against a floor, and DAYS TO FULL from a short history
  of readings (a slope, so a disk filling fast alarms before it is nearly full);
* LINUX MEMORY/CPU -- PSI (``/proc/pressure/memory`` ``some``/``full avg60``, ``/proc/pressure/cpu`` ``some
  avg60``): the share of time work STALLED, which is what the runner felt; and per declared systemd service its
  cgroup ``memory.events`` DELTAS (``high``/``max``/``oom_kill``) between two readings -- a counter that moved
  is a throttle that happened, whatever the host percentage says;
* A WORKSTATION (Windows, macOS) -- psutil AVERAGED over a window: a 50 ms ``cpu_percent`` sample on two cores
  is noise, which is why CPU was off. Where PSI is absent the PSI reading is UNMEASURABLE (``None``), never 0.

Every threshold is a named constant, overridable by the same name in the machine file's ``[pressure]`` table
(:func:`thresholds`). This module MEASURES AND REPORTS; it never deletes (:mod:`dev_lab.supervise.components.
resources` rules that) -- the remedy it carries is the biggest consumers and the family's cleanup doors.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final

__all__ = [
    'CGROUP_ROOT',
    'DOORS',
    'OWNED',
    'RAM_CRITICAL',
    'THRESHOLDS',
    'WALK_BUDGET',
    'Consumer',
    'Declared',
    'Finding',
    'Measured',
    'consumers',
    'measure',
    'parse_events',
    'parse_psi',
    'thresholds',
    'tree_bytes',
]

#: Where the box's RAM counts as full -- supervision's ``ProcessMonitor`` ceiling and a workstation's, one source.
RAM_CRITICAL: Final = 95

#: The defaults, each overridable by its own name in ``[pressure]``. Percent values are PSI ``avg60`` (the
#: share of the last minute some/all tasks stalled) or psutil's percent; bytes are GB for a human to set.
THRESHOLDS: Final[Mapping[str, float]] = {
    'disk_free_floor_gb': 10.0,  # below this many free GB on a declared path: critical
    'disk_percent_ceiling': 90.0,  # past this percent used: warning
    'days_to_full_floor': 3.0,  # filling so fast it is full within this many days: warning
    'psi_memory_some_avg60': 10.0,  # some task stalled on memory this share of the last minute
    'psi_memory_full_avg60': 5.0,  # EVERY task stalled on memory: critical
    'psi_cpu_some_avg60': 50.0,  # runnable work waited for a CPU half the last minute
    'cpu_percent_ceiling': 90.0,  # a workstation's CPU, averaged over the window
    'memory_percent_ceiling': float(RAM_CRITICAL),  # a workstation's RAM: supervision's own ceiling, one source
    'psutil_window_s': 5.0,  # the averaging window on a workstation; never a 50 ms sample
    # THE CADENCE AND THE SLOPE, ONE SOURCE: a writer reads every `interval_s` (a writer passes its own: the
    # forge tick's `[schedule] tick_minutes`, supervision's `cycle.interval`); a days-to-full slope is believed
    # only over at least `slope_span_s`, and the disk history is kept BY AGE -- `slope_span_s + interval_s` --
    # so at any cadence the window holds a reading old enough to meet the floor.
    'interval_s': 300.0,
    'slope_span_s': 3600.0,
}

#: The cgroup counters a declared service's ``memory.events`` is read for, and the severity a rise carries.
EVENTS: Final[Mapping[str, str]] = {'high': 'warning', 'max': 'critical', 'oom_kill': 'critical'}

#: Where systemd's services' cgroups live (cgroup v2).
CGROUP_ROOT: Final = Path('/sys/fs/cgroup/system.slice')

#: The PSI files, by resource.
PSI: Final[Mapping[str, Path]] = {'memory': Path('/proc/pressure/memory'), 'cpu': Path('/proc/pressure/cpu')}

#: A slope needs two readings.
_SLOPE_POINTS: Final = 2

#: How many directory entries one reading's consumer walk may visit: a pressed disk is not walked whole.
WALK_BUDGET: Final = 200_000

#: How many consumers a disk alarm names.
TOP_CONSUMERS: Final = 5

#: The trees the forge and the agents make and may clean, as globs under a declared path (``*/`` one checkout
#: deeper too) -- a consumer matching one is marked ``owned``; any other is named and never touched.
OWNED: Final = (
    '.claude/worktrees/*',
    'output/logs/*',
    '.cache/act/*',
    '.cache/actcache/*',
    '_work/_temp/*',
    'ci/*',
)

#: The family's cleanup doors, in the order an agent should try them. None is run by this module.
DOORS: Final = (
    'python -m dev_lab.dev.branchset --apply  (landed branches and their worktrees)',
    'python -m dev_lab.dev.retention --apply  (the forge runs this host left behind)',
    "the repo's clean runner (output/logs retention)",
)


def thresholds(table: Mapping[str, Any]) -> dict[str, float]:
    """:data:`THRESHOLDS`, each overridden by the same key in *table* (the machine file's ``[pressure]``)."""
    return {name: float(table.get(name, default)) for name, default in THRESHOLDS.items()}


@dataclass(frozen=True)
class Declared:
    """What one host watches: *paths* (disk), *services* (systemd units with a cgroup), and *limits*."""

    paths: tuple[Path, ...] = ()
    services: tuple[str, ...] = ()
    limits: Mapping[str, float] = field(default_factory=lambda: dict(THRESHOLDS))

    @classmethod
    def of(cls, table: Mapping[str, Any]) -> Declared:
        """From ``[pressure]``: ``paths``, ``services`` and any threshold by name."""
        paths = tuple(Path(str(p)) for p in table.get('paths', ()))
        return cls(paths, tuple(str(s) for s in table.get('services', ())), thresholds(table))


@dataclass(frozen=True)
class Consumer:
    """One directory holding a pressed disk: its path AS READ FROM DISK (untrusted text), bytes, and ownership."""

    path: str
    bytes: int
    owned: bool


@dataclass(frozen=True)
class Finding:
    """One alarm: which pressure, how severe, what was read, and who holds the resource.

    *kind* names WHICH pressure (``disk:/``, ``cgroup:gitea-runner.service:high``); *consumers* are the biggest
    owners of the resource.
    """

    kind: str
    severity: str
    measurement: str
    consumers: tuple[Consumer, ...] = ()


@dataclass
class Measured:
    """The findings, every reading (``None`` = unmeasurable here), and the memo the next reading compares to."""

    findings: list[Finding] = field(default_factory=list)
    readings: dict[str, float | None] = field(default_factory=dict)
    memo: dict[str, Any] = field(default_factory=dict)
    interval_s: float = THRESHOLDS['interval_s']


def parse_psi(text: str) -> dict[str, float]:
    """``{'some_avg60': x, 'full_avg60': y}`` from a PSI file's lines (``full`` absent for cpu on old kernels)."""
    found: dict[str, float] = {}
    for line in text.splitlines():
        head, *pairs = line.split()
        for pair in pairs:
            key, _, value = pair.partition('=')
            if key == 'avg60':
                found[f'{head}_avg60'] = float(value)
    return found


def parse_events(text: str) -> dict[str, int]:
    """A cgroup ``memory.events`` file as ``{counter: count}``."""
    return {k: int(v) for k, v in (line.split() for line in text.splitlines() if line.strip())}


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
    oldest = now - limits['slope_span_s'] - limits['interval_s']
    kept = [one for one in history if one[0] >= oldest] + [[now, float(disk.used)]]
    days = _days_to_full(kept, disk.free, limits['slope_span_s'])
    readings = {f'disk:{name}:percent': round(percent, 1), f'disk:{name}:free_gb': round(free_gb, 2),
                f'disk:{name}:days_to_full': None if days is None else round(days, 1)}  # fmt: skip
    said = f'{name} {percent:.1f}% used, {free_gb:.1f} GB free' + (f', full in {days:.1f} days' if days else '')
    if free_gb < limits['disk_free_floor_gb']:
        return (
            [Finding(f'disk:{name}', 'critical', f'{said} (floor {limits["disk_free_floor_gb"]} GB)')],
            readings,
            kept,
        )
    if percent > limits['disk_percent_ceiling'] or (days is not None and days < limits['days_to_full_floor']):
        return [Finding(f'disk:{name}', 'warning', said)], readings, kept
    return [], readings, kept


def _days_to_full(history: Sequence[Sequence[float]], free: int, span: float) -> float | None:
    """Days until *free* bytes are gone at the first-to-last slope; ``None`` when not filling or under *span*."""
    if len(history) < _SLOPE_POINTS:
        return None
    (t0, used0), (t1, used1) = history[0], history[-1]
    if t1 - t0 < span:  # a burst seconds apart is not a trend
        return None
    rate = (used1 - used0) / (t1 - t0)  # bytes per second
    return free / rate / 86400 if rate > 0 else None


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
            findings.append(Finding(f'psi:{resource}:{scope}', severity, text))
    return findings, readings


def _cgroups(
    services: Sequence[str], previous: Mapping[str, Mapping[str, int]], read: Callable[[Path], str | None]
) -> tuple[list[Finding], dict[str, float | None], dict[str, dict[str, int]]]:
    findings: list[Finding] = []
    readings: dict[str, float | None] = {}
    counts: dict[str, dict[str, int]] = {}
    for service in services:
        text = read(CGROUP_ROOT / service / 'memory.events')
        if text is None:
            readings[f'cgroup:{service}'] = None
            continue
        now = counts[service] = parse_events(text)
        before = previous.get(service)
        for counter, severity in EVENTS.items():
            rise = now.get(counter, 0) - before.get(counter, 0) if before is not None else None
            readings[f'cgroup:{service}:{counter}_delta'] = rise  # the first reading has no delta yet
            if rise is not None and rise > 0:
                said = f'{service} cgroup memory.events {counter} rose by {rise} (now {now.get(counter, 0)})'
                findings.append(Finding(f'cgroup:{service}:{counter}', severity, said))
    return findings, readings, counts


def _windowed(psutil: ModuleType | None, limits: Mapping[str, float]) -> tuple[list[Finding], dict[str, float | None]]:
    if psutil is None:
        return [], {'cpu:percent': None, 'memory:percent': None}
    cpu = float(psutil.cpu_percent(interval=limits['psutil_window_s']))  # averaged over the window
    memory = float(psutil.virtual_memory().percent)
    findings = [
        Finding(f'{name}:percent', 'warning', f'{name} {value:.0f}% averaged over {limits["psutil_window_s"]:.0f}s')
        for name, value in (('cpu', cpu), ('memory', memory))
        if value > limits[f'{name}_percent_ceiling']
    ]
    return findings, {'cpu:percent': round(cpu, 1), 'memory:percent': round(memory, 1)}


def tree_bytes(path: Path, budget: list[int], device: int) -> int:
    """The bytes under *path* on the DECLARED ROOT'S filesystem *device*, symlinks not followed, within *budget*.

    Bounded twice, because it runs when a disk is ALREADY pressed and on every tick while it stays so: it never
    descends into another mount (``/proc``, ``/sys``, another disk are not this disk), and it stops when the
    shared *budget* (:data:`WALK_BUDGET` entries per reading) is spent -- the sizes then read as lower bounds. An
    entry that cannot be read is skipped, never raised.
    """
    total, stack = 0, [path]
    while stack and budget[0] > 0:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            total += info.st_size
            if entry.is_dir(follow_symlinks=False) and info.st_dev == device:
                stack.append(Path(entry.path))
    return total


def _device(path: Path) -> int | None:
    try:
        return path.lstat().st_dev
    except OSError:
        return None


def consumers(
    roots: Sequence[Path], *, top: int = TOP_CONSUMERS, device: Callable[[Path], int | None] = _device
) -> tuple[Consumer, ...]:
    """The *top* directories under *roots* by bytes, each marked owned (an :data:`OWNED` glob) or not.

    An owned tree is named per child (one worktree, one log day), any other directory as one entry holding
    what is NOT owned under it -- so no byte is counted twice, and the agent sees what it may clean. A root
    that cannot be listed names nothing: the alarm stands without its consumers, never vanishes. A directory on
    ANOTHER device than its declared root (``/proc``, ``/sys``, ``/dev``, ``/run`` under ``/``) is not a consumer
    of this disk and is never walked.
    """
    seen: dict[Path, bool] = {}
    devices: dict[Path, int] = {}
    for root in roots:
        home = device(root)
        if home is None:
            continue
        try:
            for pattern in OWNED:
                for hit in (*root.glob(pattern), *root.glob(f'*/{pattern}')):
                    if hit.is_dir() and not hit.is_symlink() and device(hit) == home:
                        seen[hit], devices[hit] = True, home
            for child in sorted(root.iterdir()) if root.is_dir() else ():
                if child.is_dir() and not child.is_symlink() and device(child) == home and child not in seen:
                    seen[child], devices[child] = False, home
        except OSError:
            continue
    budget = [WALK_BUDGET]
    sizes = {p: tree_bytes(p, budget, devices[p]) for p in seen}
    rest = {p: n - sum(sizes[o] for o, mine in seen.items() if mine and p in o.parents) for p, n in sizes.items()}
    ranked = sorted(seen, key=lambda p: -rest[p])[:top]
    return tuple(Consumer(p.as_posix(), max(rest[p], 0), seen[p]) for p in ranked)


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
) -> Measured:
    """One reading of everything *declared*, judged against its limits and the *previous* memo.

    Each seam is a fixture's way in: *read* a file's text, *usage* a disk, *psutil* the module's loader (a
    real reading passes :func:`~dev_lab.supervise.components.resources.psutil_module`; ``None`` is absent),
    *linux* whether PSI and cgroups are asked, *sizes* the consumers of a disk alarm.
    """
    done = Measured(interval_s=declared.limits['interval_s'])
    histories = previous.get('disk', {})
    for path in declared.paths:
        found, readings, kept = _disk(path, declared.limits, histories.get(path.as_posix(), []), now, usage)
        done.memo.setdefault('disk', {})[path.as_posix()] = kept
        done.readings.update(readings)
        try:
            named = sizes([path]) if found else ()
        except OSError:
            named = ()  # the alarm stands without its consumers
        done.findings += [Finding(f.kind, f.severity, f.measurement, named) for f in found]
    if linux:
        found, readings = _psi(declared.limits, read)
        done.findings += found
        done.readings.update(readings)
        found, readings, counts = _cgroups(declared.services, previous.get('cgroup', {}), read)
        done.findings += found
        done.readings.update(readings)
        done.memo['cgroup'] = counts
    else:
        done.readings.update({f'psi:{r}': None for r in ('memory:some_avg60', 'memory:full_avg60', 'cpu:some_avg60')})
        found, readings = _windowed(psutil(), declared.limits)
        done.findings += found
        done.readings.update(readings)
    return done
