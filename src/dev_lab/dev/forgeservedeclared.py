"""THE DECLARATION A SERVE READS, refused by name: this host's machine file tables, read in one place.

Measured 2026-11-22: ``forge serve`` read ``[schedule]``, ``[serve]``, ``[capabilities]``, the priority table, the
account's affinity (:func:`dev_lab.dev.forgeaffinity.declared`) and its ``[deploy]`` role uncaught, so a machine file
its layered reader refuses was a ValueError traceback out of every tick. :func:`declaration` reads them all and
turns a reader's refusal into :class:`DeclarationRefused` -- the release, the cause and, on a cluster account, the
door (the re-render) -- which ``serve``'s CLI prints as one line, exit 2: the guard the cron tick has for its own
reads (:mod:`dev_lab.dev.hpcaccount.tick`).

Measured 2026-11-26: ONE ``[capabilities.<vendor>]`` row without ``seats`` raised lab-commons' ``UndeclaredSeat``
(a LookupError, so no release either) out of every tick, and one vendor's missing count stopped all serving.
:func:`supplied` WITHHOLDS that row from this host's supply and hands its cause and door to *withhold* (the tick's
``seat`` alarm); every other row still supplies. A malformed row is still a refused declaration. The cluster
standing's seat provider read ``[capabilities]`` itself (lab-commons' ``account_seats``) and raised the same;
:func:`account_tool_seats` withholds the row there too.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from lab_commons.box.demand import Capacity
from lab_commons.box.machine import UndeclaredSeat, provided
from lab_commons.box.providers import ToolSeats, account_seats
from lab_commons.box.supply import Reading
from lab_commons.compute.presence import Presence
from lab_commons.compute.priority import PRIORITY_TABLE, Priority
from lab_commons.compute.serves import SERVE_TABLE, Serves
from lab_commons.config import config_path, section
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.retired import refuse_retired_keys

from dev_lab.dev.forgeaffinity import declared
from dev_lab.dev.hpcaccount.grantslice import refused_with_door
from dev_lab.dev.hpcaccount.spec import load, schedule_tick

__all__ = ['DeclarationRefused', 'account_tool_seats', 'declaration', 'supplied']


class DeclarationRefused(ValueError):
    """The declaration of this host -- the machine file a serve reads its tables from -- was refused by its reader.

    A named release, never a traceback (the guard :mod:`dev_lab.dev.hpcaccount.tick` has for its own reads): the
    message is the release, the reader's cause and, on a cluster account, its door, the re-render.
    """


def supplied(table: Mapping[str, Any], withhold: Callable[[str], object]) -> dict[str, dict[str, Any]]:
    """:func:`provided` over *table*, each vendor row with no declared seat count withheld and named to *withhold*.

    Raises:
        ValueError: a malformed row (:func:`provided`'s refusal), never an undeclared seat.

    """
    rows = dict(table)
    while True:
        try:
            return provided(rows)
        except UndeclaredSeat as undeclared:
            withhold(str(undeclared))
            del rows[undeclared.tool]


def _nothing_observed(_pids: object) -> Reading:
    """No OS reading: an account's seats are not observed in a process table."""
    return Reading(cores=0.0, idle_cores=0.0, total_bytes=0, available_bytes=0)


def account_tool_seats(presence: Mapping[str, Presence] | None) -> ToolSeats:
    """A cluster account's seat provider (lab-commons' ``account_seats``), each undeclared vendor withheld.

    Every vendor declared: exactly ``account_seats``. One undeclared: the rest are sized by their declared seats, and a
    row with a ``supply`` probe is BLIND -- it lends none, since its probe is lab-commons' and not run here -- until
    the declaration is fixed; the tick's ``seat`` alarm (:func:`declaration`) names the file and the door.
    """
    try:
        return account_seats(presence)
    except UndeclaredSeat:
        rows = supplied(section('capabilities'), lambda _why: None)  # declaration() alarmed it this tick
    sizes = {name: int(facts.get('seats', 1)) for name, facts in rows.items()}
    blind = {
        name: f'its supply probe {facts["supply"][0]!r} is not run while a vendor seat count is undeclared'
        for name, facts in rows.items()
        if facts.get('supply')
    }
    return ToolSeats(Capacity(cpu=0.0, mem_bytes=0, seats=sizes, blind=blind), _nothing_observed, presence)


def declaration(
    repo: str,
    seat: ClusterAccount | None,
    table: Mapping[str, Any] | None,
    *,
    withhold: Callable[[str], object],
) -> tuple[Mapping[str, Any], Any, Priority, Serves, Sequence[str], str]:
    """Every read of this host's declaration: ``[schedule]``, the capabilities, priority, serves, affinity, role.

    A vendor capability with no declared seat count is withheld from the supply (:func:`supplied`), named to
    *withhold*; the rest is served.

    Raises:
        DeclarationRefused: a reader refused the machine file (or the family file under it).

    """
    try:
        table = section('schedule') if table is None else table
        schedule_tick(table)  # its period, refused here by name rather than mid-tick
        refuse_retired_keys('serve', section('serve'))
        refuse_retired_keys('capabilities', section('capabilities'))
        capable = supplied(section('capabilities'), withhold)
        priority = Priority.of(section(PRIORITY_TABLE))
        serves = Serves.of(section(SERVE_TABLE))
        verify = declared(config_path(), repo) if seat is not None else ()  # HPC account affinity
        role = deployed.role if seat is not None and (deployed := load(config_path())) else ''  # its card shows it
    except ValueError as unread:
        cause = refused_with_door(unread) if seat is not None else str(unread)
        msg = f'released, not served this tick: {cause}'
        raise DeclarationRefused(msg) from unread
    return table, capable, priority, serves, verify, role
