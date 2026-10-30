"""THE PRODUCER EXIT CONTRACT -- what a part producer's exit code MEANS to ``forge serve``. One source.

A producer is the argv ``forge tick`` hands out for a claimed LOCAL part (a local runner, ``verify``); a
cluster part is no process but a resumable run (:mod:`dev_lab.dev.forgerun`). Serve cannot read a
producer's mind, only its exit code, so every code means ONE thing:

* ``0`` PASS -- the part was judged PASS (and posted when the tree allowed it).
* ``1`` FAIL -- the part was judged FAIL and the failures are named (posted likewise). A red part.
* ``2`` USAGE -- the producer REFUSED ITS ARGV. argparse's own code, kept so a renamed flag needs no
  extra code to be caught: serve calls it a broken contract and fails loudly.
* ``3`` INCONCLUSIVE -- it ran and cannot say (over the wall, truncated log). No part; the
  claim is released naming it, and the commit is NOT re-claimed by itself -- a human decides.
* ``4`` UNREACHABLE -- infrastructure it needs did not answer (no login host, no forge), or the box had
  no room for it (capacity, never a verdict). It says nothing about the code: the claim is released as
  retryable and the next tick claims it again.

Any other code is a CRASH. Live finding 2026-10-11: a consumer runner returned ``2`` for INCONCLUSIVE
and serve reported "the producer refused its argv" -- two meanings sharing one code is the bug.

THE BOX'S DECISION IS NOT A CODE (:func:`box_release_reason`). A producer runs in the box, whose CLI exits
with the producer's own code and writes how the box ended it to a record (``--outcome``). Reading a box
refusal or kill off a sentinel exit code misread a producer that chose that number itself (sharp review
SR-20261015-002: one exiting sysexits' unavailable code was re-claimed every tick forever), so the record
decides first and the code is judged only when the producer ended on its own.

THE DOOR TO A FULL SUITE IS ``forge serve`` (``VERDICTS-FROM-THE-FORGE``, user report 2026-10-11:
agents on other workstations ran full suites locally and blocked development for hours). A verdict is
a fact about a sha, produced ONCE, after the push, by the host that claimed the part -- so a full tier
runs only in a process serve spawned for a claim, which carries :data:`PRODUCING_VAR` naming the part
(:func:`producing`). Everywhere else :func:`full_suite_refusal` refuses it with the remedy; there is no
flag, because a flag is a second door a developer can walk through by habit.
"""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, Final

from lab_commons.box import ProcessEnd, Refused

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    'PRODUCING_VAR',
    'RETRYABLE',
    'ProducerExit',
    'box_release_reason',
    'full_suite_refusal',
    'producing',
    'release_reason',
]

#: Set by ``forge serve`` on the producer it spawns: the claimed part, ``tests/<part>@<sha>``.
PRODUCING_VAR: Final = 'LAB_COMMONS_PRODUCING'


def producing(context: str, sha: str) -> dict[str, str]:
    """The environment ``forge serve`` adds to the producer of part *context* at *sha*.

    The sha is the text after the LAST ``@``: a row's context carries one itself (``tests/base@windows``), a sha never.
    """
    return {PRODUCING_VAR: f'{context}@{sha}'}


def full_suite_refusal(what: str, env: Mapping[str, str], context: str) -> str | None:
    """``None`` inside a producer serve spawned for *context* (this box's part), else the refusal naming the remedy."""
    if env.get(PRODUCING_VAR, '').rpartition('@')[0] == context:
        return None
    return (
        f'{what}: refused -- a full suite is a verdict, and a verdict is produced once per sha, after the push, '
        f'by the forge serve host that claims {context}; never by a developer or an agent. '
        f'Remedy: push; the forge produces the part; read it with '
        f'`python -m dev_lab.dev.forge status list <sha>` (pending parts: `forge tick --dry-run`). '
        f'To check a change now, run a targeted selection: `python -m dev_lab.dev.verify -- <paths>`.'
    )


class ProducerExit(IntEnum):
    """The five codes a producer may exit with; anything else is a crash."""

    PASS = 0
    FAIL = 1
    USAGE = 2
    INCONCLUSIVE = 3
    UNREACHABLE = 4


#: The description prefix of a released claim the next tick may claim again (:func:`release_reason`): OPEN, not settled.
RETRYABLE: Final = 'released: unreachable'


def release_reason(code: int) -> str:
    """The ``error`` description releasing a claim its producer left pending after exiting *code*."""
    reasons: dict[int, str] = {
        ProducerExit.PASS: 'released: producer exited 0 (PASS) but posted no part',
        ProducerExit.FAIL: 'released: producer exited 1 (FAIL) but posted no part',
        ProducerExit.USAGE: 'released: producer refused its argv (exit 2)',
        ProducerExit.INCONCLUSIVE: 'released: inconclusive (exit 3) -- no part',
        ProducerExit.UNREACHABLE: f'{RETRYABLE} (exit 4) -- infrastructure did not answer; retried next tick',
    }
    return reasons.get(code, f'released: producer crashed (exit {code})')


def box_release_reason(ended: ProcessEnd | Refused | None) -> str | None:
    """The release a box record forces (refused, killed, or none: crashed); ``None`` when the producer ended itself.

    A refusal is RETRYABLE (nothing ran: the box had no room in time, or no enforcer); a kill and a crash
    are released naming what happened, never red.
    """
    if isinstance(ended, Refused):
        return f'{RETRYABLE} -- the box refused it ({ended}); retried next tick'
    if ended is None:
        return 'released: the box crashed -- it left no record of how the producer ended'
    if ended.killed:
        return f'released: the box killed it past its declared {ended.reason} (exit {ended.returncode})'
    return None
