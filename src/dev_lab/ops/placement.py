"""Where a host role's systemd service sits: the keys every service-rendering role of :mod:`dev_lab.ops.config` has."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ['Placement']


@dataclass(frozen=True, kw_only=True)
class Placement:
    """Where a role's systemd service sits: its ``Slice=``, and the units it is ordered ``After=`` and ``Wants=``.

    Every role that renders a service carries these keys; each defaults to none, which leaves systemd's own default.
    """

    slice: str = ''
    after: tuple[str, ...] = field(default=())
    wants: tuple[str, ...] = field(default=())
