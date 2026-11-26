"""THE DECLARATION A SERVE READS, refused by name: this host's machine file tables, read in one place.

Measured 2026-11-22: ``forge serve`` read ``[schedule]``, ``[serve]``, ``[capabilities]``, the priority table, the
account's affinity (:func:`dev_lab.dev.forgeaffinity.declared`) and its ``[deploy]`` role uncaught, so a machine file
its layered reader refuses was a ValueError traceback out of every tick. :func:`declaration` reads them all and
turns a reader's refusal into :class:`DeclarationRefused` -- the release, the cause and, on a cluster account, the
door (the re-render) -- which ``serve``'s CLI prints as one line, exit 2: the guard the cron tick has for its own
reads (:mod:`dev_lab.dev.hpcaccount.tick`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lab_commons.box.machine import provided
from lab_commons.compute.priority import PRIORITY_TABLE, Priority
from lab_commons.compute.serves import SERVE_TABLE, Serves
from lab_commons.config import config_path, section
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.retired import refuse_retired_keys

from dev_lab.dev.forgeaffinity import declared
from dev_lab.dev.hpcaccount.grantslice import refused_with_door
from dev_lab.dev.hpcaccount.spec import load, schedule_tick

__all__ = ['DeclarationRefused', 'declaration']


class DeclarationRefused(ValueError):
    """The declaration of this host -- the machine file a serve reads its tables from -- was refused by its reader.

    A named release, never a traceback (the guard :mod:`dev_lab.dev.hpcaccount.tick` has for its own reads): the
    message is the release, the reader's cause and, on a cluster account, its door, the re-render.
    """


def declaration(
    repo: str, seat: ClusterAccount | None, table: Mapping[str, Any] | None
) -> tuple[Mapping[str, Any], Any, Priority, Serves, Sequence[str], str]:
    """Every read of this host's declaration: ``[schedule]``, the capabilities, priority, serves, affinity, role.

    Raises:
        DeclarationRefused: a reader refused the machine file (or the family file under it).

    """
    try:
        table = section('schedule') if table is None else table
        schedule_tick(table)  # its period, refused here by name rather than mid-tick
        refuse_retired_keys('serve', section('serve'))
        refuse_retired_keys('capabilities', section('capabilities'))
        capable = provided(section('capabilities'))
        priority = Priority.of(section(PRIORITY_TABLE))
        serves = Serves.of(section(SERVE_TABLE))
        verify = declared(config_path(), repo) if seat is not None else ()  # HPC account affinity
        role = deployed.role if seat is not None and (deployed := load(config_path())) else ''  # its card shows it
    except ValueError as unread:
        cause = refused_with_door(unread) if seat is not None else str(unread)
        msg = f'released, not served this tick: {cause}'
        raise DeclarationRefused(msg) from unread
    return table, capable, priority, serves, verify, role
