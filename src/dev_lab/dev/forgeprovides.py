"""WHAT A HOST PROVIDES -- the resources beyond its OS, declared once per machine and read onto its card.

A part is ``tests/<part>``, its need-set (:mod:`lab_commons.hpc.needsets`), and every resource is equal: an
OS, a tool, a host fact. Which OS a host runs is measured, and so is every tool with a probe: it is present
exactly where the probe finds it, declared or not (:func:`lab_commons.compute.probe.tools`). THIS MACHINE's
file (:mod:`lab_commons.config`) declares only what no probe can read -- a tool's seat count, and a resource
without a probe::

    [capabilities.jmag]
    seats = 4          # how many solver jobs this box runs at once -- the one number no probe can read

    [capabilities.workstation]

Whether THIS host may claim a part is the admission's (:func:`lab_commons.compute.admission.admit`: the
part's needs present, its demand within the supply). What the queue says about EVERY live host is
:func:`unserved`: a part whose needs no live host has is BLOCKED naming the resource, never red, never
skipped.

A STALE CARD SUPPLIES NOTHING (:func:`supplied`, user ruling 2026-10-28): a host that stopped ticking cannot
claim, so what its card last declared -- ``jmag = 1`` on two workstations stale for days -- is never counted
as supply by the queue, the fleet alarm or any other reader. Its forge claims are not released by anyone: each
lapses with its lease (:data:`dev_lab.dev.forgeclaim.DEFAULT_LEASE`), which only its owner renews, and is then
retaken by any host serving that part.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Final

from dev_lab.dev.forgeschedule import NO_HOST

if TYPE_CHECKING:
    from dev_lab.dev.forgehosts import HostCard

__all__ = ['NO_PROVIDER', 'present', 'supplied', 'unserved']

#: How a part no host may claim is labelled: ``no host provides <resource>``.
NO_PROVIDER: Final = f'{NO_HOST} provides'


def present(platform: str, provides: Collection[str]) -> frozenset[str]:
    """The resources a host card says it has: its OS and every machine-file resource."""
    return frozenset({platform, *provides})


def supplied(card: HostCard, now: datetime) -> frozenset[str]:
    """The resources *card*'s host supplies as of *now*: its OS and every tool its probe found; NOTHING when stale."""
    return frozenset() if card.stale(now) else present(card.platform, card.tools_present())


def unserved(needs: Collection[str], hosts: Sequence[frozenset[str]]) -> str:
    """Why no host of *hosts* (each its present resources) has every one of *needs*; ``''`` when one has.

    Names the first need no host has at all, else the need-set no single host has together.
    """
    wanted = frozenset(needs)
    if any(have and wanted <= have for have in hosts):  # an empty set is a stale card: it serves not even base
        return ''
    if not wanted:
        return f'{NO_HOST} serves it'
    missing = sorted(name for name in wanted if not any(name in have for have in hosts))
    return f'{NO_PROVIDER} {missing[0] if missing else "+".join(sorted(wanted))}'
