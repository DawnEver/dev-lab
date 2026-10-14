"""WHAT A HOST PROVIDES -- the resources beyond its OS, declared once per machine and read onto its card.

A part is ``tests/<part>``, its need-set (:mod:`lab_commons.hpc.needsets`), and every resource is equal: an
OS, a tool, a host fact. Which OS a host runs is measured; what else it has is declared in THIS MACHINE's
file (:mod:`lab_commons.config`), one table per resource, and a tool with a probe is present only where the
probe also finds it (:func:`lab_commons.compute.probe.tools`)::

    [capabilities.jmag]
    seats = 4          # how many solver jobs this box runs at once -- the one number no probe can read

    [capabilities.dev_checkout]

Whether THIS host may claim a part is the admission's (:func:`lab_commons.compute.admission.admit`: the
part's needs present, its demand within the supply). What the queue says about EVERY live host is
:func:`unserved`: a part whose needs no live host has is BLOCKED naming the resource, never red, never
skipped.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Final

from lab_commons.dev.forgeschedule import NO_HOST

__all__ = ['NO_PROVIDER', 'present', 'unserved']

#: How a part no host may claim is labelled: ``no host provides <resource>``.
NO_PROVIDER: Final = f'{NO_HOST} provides'


def present(platform: str, provides: Collection[str]) -> frozenset[str]:
    """The resources a host card says it has: its OS and every machine-file resource."""
    return frozenset({platform, *provides})


def unserved(needs: Collection[str], hosts: Sequence[frozenset[str]]) -> str:
    """Why no host of *hosts* (each its present resources) has every one of *needs*; ``''`` when one has.

    Names the first need no host has at all, else the need-set no single host has together.
    """
    wanted = frozenset(needs)
    if any(wanted <= have for have in hosts):
        return ''
    if not wanted:
        return f'{NO_HOST} serves it'
    missing = sorted(name for name in wanted if not any(name in have for have in hosts))
    return f'{NO_PROVIDER} {missing[0] if missing else "+".join(sorted(wanted))}'
