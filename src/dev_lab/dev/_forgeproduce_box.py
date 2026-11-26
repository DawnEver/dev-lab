"""THE PRODUCER'S BOX: the demand a claimed item runs at, the argv that holds it, and what a run teaches the box.

The box is :mod:`lab_commons.box`; the run it holds is :mod:`dev_lab.dev.forgeproduce`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from lab_commons.box import GB, Capacity, command
from lab_commons.compute.learned import Run, box_demand, record_run
from lab_commons.compute.model import Demand
from lab_commons.proc import process_tree, working_set_bytes

from dev_lab.dev.forgeclaim import Work
from dev_lab.dev.forgewait import claim_vector
from dev_lab.dev.partrows import needs_of_row
from dev_lab.dev.platformparts import origin_url

#: How long a producer waits for its box claim, in seconds: the tick admitted it against the box ledger, so
#: only a run admitted in between can be in its way -- then the claim is released and retried next tick.
BOX_QUEUE_S: Final = 60.0


#: Bytes in one gibibyte.
_GB: Final = 1024.0**3


def tree_gb(pid: int) -> float | None:
    """Resident GB of *pid*'s whole process tree now, or ``None`` when nothing of it could be read."""
    readings = [working_set_bytes(one) for one in process_tree(pid)]
    known = [r for r in readings if r is not None]
    return sum(known) / _GB if known else None


def learn_box_run(root: Path, item: Work, run: Run, *, ended: str) -> None:
    """Record one box run of *root*'s repository under ``(its producer, its need-set)``, by how it *ended*.

    *ended* is :attr:`~lab_commons.box.ProcessEnd.reason`'s vocabulary; ``record_run`` prices only an exit
    and a memory kill, so a run the wall or a signal cut mid-climb teaches nothing.

    A part's producer is ``local``; a request's is its declared NAME, so it never shares a test part's record.
    """
    record_run(origin_url(root), item.producer, needs_of_row(item.platform), run, ended=ended)


def _origin(root: Path | None) -> str:
    """*root*'s origin URL, ``''`` (nothing learned) for none or an unreadable one."""
    try:
        return '' if root is None else origin_url(root)
    except OSError:
        return ''


def boxed(item: Work, argv: Sequence[str], capacity: Capacity, outcome: Path, *, root: Path | None = None) -> list[str]:
    """*argv* run through the box at the demand the tick admitted *item* at, recording how it ended at *outcome*.

    An item claimed with no demand is priced as the tick prices a box part (:func:`~lab_commons.compute.learned.
    box_demand` of *root*'s origin). The child holds against *capacity*, the one reading the demand was sized by.
    """
    what = f'{item.context}@{item.sha[:12]}'
    return command(
        argv,
        box_claim(item, capacity, root=root),
        item.wall_s,
        BOX_QUEUE_S,
        key=item.context,
        what=what,
        outcome=outcome,
        fingerprint=item.sha,
        capacity=capacity,
        claim=item.box,
    )


def box_claim(item: Work, capacity: Capacity, *, root: Path | None = None) -> Demand:
    """The :class:`Demand` *item* runs in the box at: the tick's admitted demand, else priced as a box part."""
    needs = needs_of_row(item.platform)
    asked = item.demand or box_demand(_origin(root), needs, cpu=capacity.cpu, mem_gb=capacity.mem_bytes / GB)
    return claim_vector(asked, capacity, needs)
