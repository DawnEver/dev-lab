"""The shapes a pressure reading is made of: one :class:`Finding`, and the kernel files' text parsed.

Shared by :mod:`dev_lab.supervise.pressure` (host disk, PSI, psutil) and :mod:`dev_lab.supervise.cgroup` (a
declared unit's cgroup), so neither imports the other's internals.
"""

from __future__ import annotations

from dataclasses import dataclass

from dev_lab.supervise.consumers import Consumer

__all__ = ['Finding', 'parse_events', 'parse_psi']


@dataclass(frozen=True)
class Finding:
    """One alarm: which pressure, how severe, what was read, and who holds the resource.

    *kind* names WHICH pressure (``disk:/``, ``cgroup:gitea-runner.service:high``); *consumers* are the biggest
    owners of the resource. *metric*, *value* and *threshold* are the glanceable reading an alert's first line
    shows (``disk /``, ``91%``, ``> 90%``); *measurement* is the full sentence.
    """

    kind: str
    severity: str
    measurement: str
    consumers: tuple[Consumer, ...] = ()
    metric: str = ''
    value: str = ''
    threshold: str = ''


def parse_psi(text: str) -> dict[str, float]:
    """``{'some_avg10': x, 'some_avg60': y, ...}`` from a PSI file's lines (``full`` absent for cpu on old kernels)."""
    found: dict[str, float] = {}
    for line in text.splitlines():
        head, *pairs = line.split()
        for pair in pairs:
            key, _, value = pair.partition('=')
            if key.startswith('avg'):
                found[f'{head}_{key}'] = float(value)
    return found


def parse_events(text: str) -> dict[str, int]:
    """A cgroup ``memory.events`` or ``memory.stat`` file as ``{counter: count}``."""
    return {k: int(v) for k, v in (line.split() for line in text.splitlines() if line.strip())}
