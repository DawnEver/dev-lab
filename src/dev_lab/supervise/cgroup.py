"""A declared unit's cgroup memory: REAL pressure alarms, routine reclaim at ``memory.high`` never does.

Per unit, read where systemd says it lives (:func:`control_group`): ``memory.events`` (``oom_kill``/``oom``/
``max`` -- any rise is critical; ``high`` -- read, alarming only past the opt-in ``cgroup_high_rise``),
``memory.stat`` ``workingset_refault_anon`` (anonymous pages thrashed back in: the 2026-09-14 throttle
signature, high large WITH anon refaults), and the cgroup's own ``memory.pressure`` avg10. Measured 2026-11-06
on forge-a1: ``high`` +252 at 139 MB of a 1 GB memory.high, 105 MB of it file cache, oom_kill 0, refault_anon 0
-- each Merge tick reads an 80 MB git mirror and the kernel reclaims that cache at the line. Routine, not pressure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from dev_lab.supervise.process.systemd import subprocess_runner
from dev_lab.supervise.reading import Finding, parse_events, parse_psi

__all__ = ['CGROUP_MOUNT', 'CGROUP_PSI', 'EVENTS', 'cgroups', 'control_group']

#: The cgroup counters read per declared unit: ``{counter: (file, severity, limit key or None for any rise)}``.
#: ``high`` is read for its delta but alarms only past its opt-in line; ``oom``/``oom_kill``/``max`` on any rise.
EVENTS: Final[Mapping[str, tuple[str, str, str | None]]] = {
    'high': ('memory.events', 'warning', 'cgroup_high_rise'),
    'max': ('memory.events', 'critical', None),
    'oom': ('memory.events', 'critical', None),
    'oom_kill': ('memory.events', 'critical', None),
    'workingset_refault_anon': ('memory.stat', 'warning', 'cgroup_refault_anon_rise'),
}

#: The cgroup's own ``memory.pressure`` lines and the severity each carries over its ``cgroup_psi_*`` line.
CGROUP_PSI: Final[Mapping[str, str]] = {'some': 'warning', 'full': 'critical'}

#: The cgroup v2 mount. WHERE under it a unit lives is systemd's answer (:func:`control_group`), never a guess:
#: on 2026-11-02 the runners moved to ``/ci.slice/ci-runners.slice`` and a hard-coded ``system.slice`` went blind.
CGROUP_MOUNT: Final = Path('/sys/fs/cgroup')

#: How long ``systemctl show`` may take, in seconds.
_SYSTEMCTL_TIMEOUT_S: Final = 10


def control_group(unit: str) -> str:
    """*unit*'s cgroup path as systemd reports it (``/ci.slice/ci-runners.slice/x.service``); a service or a slice.

    Raises:
        LookupError: systemctl failed or reported no group -- the reason, for the finding.

    """
    ran = subprocess_runner(['systemctl', 'show', unit, '-p', 'ControlGroup', '--value'], _SYSTEMCTL_TIMEOUT_S, None)
    group = ran.out.strip()
    if ran.code != 0 or not group.startswith('/'):
        msg = f'systemctl show gave no ControlGroup (exit {ran.code}{": " + ran.err.strip() if ran.err else ""})'
        raise LookupError(msg)
    return group


def cgroups(
    services: Sequence[str],
    previous: Mapping[str, Mapping[str, int]],
    limits: Mapping[str, float],
    read: Callable[[Path], str | None],
    locate: Callable[[str], str],
) -> tuple[list[Finding], dict[str, float | None], dict[str, dict[str, int]]]:
    """Each of *services* judged against *previous* counts and *limits*: findings, readings, the next memo."""
    """Each of *services* judged against *previous* counts and *limits*: findings, readings, the next memo."""
    findings: list[Finding] = []
    readings: dict[str, float | None] = {}
    counts: dict[str, dict[str, int]] = {}
    for service in services:
        try:
            group = CGROUP_MOUNT / locate(service).lstrip('/')
            text = read(group / 'memory.events')
            reason = f'{(group / "memory.events").as_posix()} not readable'
        except LookupError as exc:
            text, reason = None, str(exc)
        if text is None:  # unmeasurable is a reading AND a finding: an alarm that cannot see must say so
            readings[f'cgroup:{service}'] = None
            said = f'{service}: memory.events unreadable ({reason}) -- the alarm cannot see it'
            findings.append(Finding(f'cgroup:{service}', 'warning', said))
            continue
        stat = read(group / 'memory.stat')
        files = {'memory.events': parse_events(text), 'memory.stat': None if stat is None else parse_events(stat)}
        now = counts[service] = {c: files[f][c] for c, (f, _, _) in EVENTS.items() if files[f] and c in files[f]}
        before = previous.get(service)
        for counter, (_, severity, key) in EVENTS.items():
            known = before is not None and counter in now and counter in before
            rise = now[counter] - before[counter] if known else None  # a first or missing reading has no delta
            readings[f'cgroup:{service}:{counter}_delta'] = rise
            line = limits[key] if key else 0.0
            if rise is not None and rise > line:
                said = f'{service} cgroup {counter} rose by {rise} (now {now[counter]}; line {line:g})'
                reading = {'metric': f'{service} {counter}', 'value': f'+{rise}', 'threshold': f'{line:g}'}
                findings.append(Finding(f'cgroup:{service}:{counter}', severity, said, **reading))
        found, psi = _cgroup_psi(service, read(group / 'memory.pressure'), limits)
        findings += found
        readings.update(psi)
    return findings, readings, counts


def _cgroup_psi(
    service: str, text: str | None, limits: Mapping[str, float]
) -> tuple[list[Finding], dict[str, float | None]]:
    """The cgroup's own ``memory.pressure`` avg10 against ``cgroup_psi_memory_<scope>_avg10``."""
    parsed = {} if text is None else parse_psi(text)
    findings: list[Finding] = []
    readings: dict[str, float | None] = {}
    for scope, severity in CGROUP_PSI.items():
        value = parsed.get(f'{scope}_avg10')
        readings[f'cgroup:{service}:psi_memory_{scope}_avg10'] = value  # absent is unmeasurable, never 0
        line = limits[f'cgroup_psi_memory_{scope}_avg10']
        if value is not None and value > line:
            said = f'{service} cgroup memory pressure {scope} avg10 {value:.1f}% > {line:.1f}%'
            reading = {
                'metric': f'{service} memory pressure {scope}',
                'value': f'{value:.1f}%',
                'threshold': f'{line:g}%',
            }
            findings.append(Finding(f'cgroup:{service}:psi_{scope}', severity, said, **reading))
    return findings, readings
