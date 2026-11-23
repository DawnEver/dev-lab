"""A QUOTA WARNS BEFORE IT FILLS -- the one judgment of an account's usage against its two declared lines.

User ruling 2026-11-22: two accounts sat at 101% of their FILE quota and nobody had been told; the first sign was
``git clone`` and ``uv`` failing "Disk quota exceeded" in the middle of a deploy. The reading existed
(:func:`dev_lab.dev.diskusage.read_usage`) and so did an alarm, but only behind the steps a full quota breaks:
the tick's alarm is raised by the serve, and a tick whose refresh cannot write never reaches its serve; a
research account never ticks at all; a deploy read no quota.

THE TWO LINES ARE DECLARED ONCE, in ``[retention]`` (:class:`dev_lab.dev.retentionplan.Policy`), as the box
free-space floor is declared once in ``[storage]``:

* ``pressure`` (default 0.85) -- the WARNING line, :data:`NEAR`. It is the line retention already gets harder
  at, so "warned" and "retention is trying harder" are one fact, never two thresholds that can disagree.
* ``refuse`` (default 0.95) -- the REFUSE-NEW-WORK line, :data:`FULL`: a deploy builds nothing, a tick refreshes
  nothing and a serve claims nothing until retention has brought usage back under it.

Both are fractions of the SOFT quota of whichever of files and bytes is nearer its ceiling (a cluster home's
binding one is files), and every line says which. Every verb that reads an account's quota states it through
:func:`lines`: files AND bytes, each with its headroom, then the named warning with its door.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final, Protocol

from lab_commons.config import section

from dev_lab.dev.diskusage import Usage, storage_text
from dev_lab.dev.retentionplan import Policy, load_policy

__all__ = [
    'DOOR', 'FULL', 'NEAR', 'UNREAD', 'Lines', 'Watch', 'admitted_files', 'card', 'declared_lines', 'freed', 'judge',
    'lines', 'usage_line',
]  # fmt: skip

#: The warning: usage is at the ``[retention] pressure`` line.
NEAR: Final = 'QUOTA-NEAR'
#: The refusal of new work: usage is at the ``[retention] refuse`` line.
FULL: Final = 'QUOTA-FULL'
#: The door of both: the verb that frees an account's files, run from the workstation.
DOOR: Final = 'python -m dev_lab.dev.hpcaccount retention --account <user> --apply (--census names what holds files)'
#: What is said when no quota tool answered: a watch that cannot read cannot warn, and says so.
UNREAD: Final = 'usage unread (no mmlsquota or quota answered): no quota warning can be raised here'

_GB: Final = 1024**3


class Lines(Protocol):
    """The two declared lines, as :class:`dev_lab.dev.retentionplan.Policy` holds them."""

    @property
    def pressure(self) -> float:
        """The warning line, a fraction of the soft quota."""

    @property
    def refuse(self) -> float:
        """The refuse-new-work line, a fraction of the soft quota."""


@dataclass(frozen=True)
class Watch:
    """One judgment: its *name* (``''``, :data:`NEAR` or :data:`FULL`), which ceiling binds, and how near it is."""

    name: str
    binding: str
    fraction: float
    text: str = ''

    @property
    def near(self) -> bool:
        """At the warning line or past it."""
        return bool(self.name)

    @property
    def full(self) -> bool:
        """At the refuse-new-work line or past it."""
        return self.name == FULL


def usage_line(usage: Usage) -> str:
    """``usage files <used>/<quota> (<p>%), headroom <n> files; bytes ... GB (<p>%), headroom ... GB``."""
    left = max(0, usage.limit - usage.used)
    share = f' ({usage.used / usage.limit:.1%})' if usage.limit else ''
    size = f'bytes {usage.used / _GB:.1f}/{usage.limit / _GB:.1f} GB{share}, headroom {left / _GB:.1f} GB'
    if usage.files is None or not usage.files_limit:
        return f'usage files unread (no file quota is read); {size}'
    files, cap = usage.files, usage.files_limit
    return f'usage files {files}/{cap} ({files / cap:.1%}), headroom {max(0, cap - files)} files; {size}'


def judge(usage: Usage | None, policy: Lines) -> Watch:
    """*usage* against *policy*'s two lines; unreadable is no warning (its line is :data:`UNREAD`)."""
    if usage is None:
        return Watch('', '', 0.0)
    fraction, binding = usage.fraction(), usage.binding()
    name = FULL if fraction >= policy.refuse else NEAR if fraction >= policy.pressure else ''
    if not name:
        return Watch('', binding, fraction)
    line = (policy.refuse, 'refuse', 'new work is refused') if name == FULL else (
        policy.pressure, 'pressure', f'new work is refused at {policy.refuse:.0%}'
    )  # fmt: skip
    text = (
        f'{name}: {binding} at {fraction:.1%} of the quota, at or past the {line[0]:.0%} line '
        f'([retention] {line[1]}); {line[2]} -- {DOOR}'
    )
    return Watch(name, binding, fraction, text)


def lines(usage: Usage | None, policy: Lines, *, who: str = '') -> list[str]:
    """What a verb says of *who*'s quota: :func:`usage_line`, then the named warning when a line is reached."""
    head = f'{who}: ' if who else ''
    if usage is None:
        return [f'{head}{UNREAD}']
    watch = judge(usage, policy)
    return [f'{head}{usage_line(usage)}', *([f'{head}{watch.text}'] if watch.near else [])]


def admitted_files(usage: Usage | None, policy: Lines) -> float | None:
    """Files a claim may still write: none at :data:`FULL` (a claim's tree is new files); ``None`` unread."""
    return 0.0 if judge(usage, policy).full else usage.files_left if usage is not None else None


def card(usage: Usage | None, policy: Lines) -> str:
    """The host card's storage text, the named warning after it once a line is reached."""
    watch = judge(usage, policy)
    return storage_text(usage) + (f' -- {watch.text}' if watch.near else '')


def declared_lines(table: Mapping[str, Any] | None = None) -> Policy:
    """The declared lines: the ``[retention]`` *table* (default: this machine's) over the kit defaults."""
    return load_policy(section('retention') if table is None else table)


def freed(usage: Usage | None, freed_bytes: int, freed_files: int) -> Usage | None:
    """*usage* once *freed_bytes* and *freed_files* went: what a pass that deleted leaves to be judged."""
    if usage is None:
        return None
    files = None if usage.files is None else usage.files - freed_files
    return replace(usage, used=usage.used - freed_bytes, files=files)
