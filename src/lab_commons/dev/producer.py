"""THE PRODUCER EXIT CONTRACT -- what a part producer's exit code MEANS to ``forge serve``. One source.

A producer is the argv ``forge tick`` hands out for a claimed LOCAL part (a local runner, ``verify``); a
cluster part is no process but a resumable run (:mod:`lab_commons.dev.forgerun`). Serve cannot read a
producer's mind, only its exit code, so every code means ONE thing:

* ``0`` PASS -- the part was judged PASS (and posted when the tree allowed it).
* ``1`` FAIL -- the part was judged FAIL and the failures are named (posted likewise). A red part.
* ``2`` USAGE -- the producer REFUSED ITS ARGV. argparse's own code, kept so a renamed flag needs no
  extra code to be caught: serve calls it a broken contract and fails loudly.
* ``3`` INCONCLUSIVE -- it ran and cannot say (over the wall, truncated log, box held). No part; the
  claim is released naming it, and the commit is NOT re-claimed by itself -- a human decides.
* ``4`` UNREACHABLE -- infrastructure it needs did not answer (no login host, no forge). It says
  nothing about the code: the claim is released as retryable and the next tick claims it again.

Any other code is a CRASH. Live finding 2026-10-11: a consumer runner returned ``2`` for INCONCLUSIVE
and serve reported "the producer refused its argv" -- two meanings sharing one code is the bug.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final

__all__ = ['RETRYABLE', 'ProducerExit', 'release_reason']


class ProducerExit(IntEnum):
    """The five codes a producer may exit with; anything else is a crash."""

    PASS = 0
    FAIL = 1
    USAGE = 2
    INCONCLUSIVE = 3
    UNREACHABLE = 4


#: The description prefix of a released claim the next tick may claim again (:func:`release_reason`).
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
