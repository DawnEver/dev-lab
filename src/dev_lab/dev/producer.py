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

EVERY NON-PASS NAMES ITS OWNER (:class:`Owner`, architecture contract 6). A forge has four states, so the
owner is not a state: it is the ``class=<owner>`` field of an ``error`` description (:func:`owned`), read
back by :func:`owner_of`. A ``failure`` is a judged FAIL and always :attr:`Owner.CODE`; an ``error`` is
the author's red only when it says ``class=code``. Every other class is not the author's: it still blocks
promoting ``main`` and is never a PASS. A producer DECLARES an outage it did not cause -- infrastructure
that did not answer (:func:`unreachable`) or a vendor licence it could not check out (:func:`licence_outage`)
-- and either is released RETRYABLE under its class.
"""

from __future__ import annotations

import os
import re
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.box import ProcessEnd, Refused

from dev_lab.dev.forgestatus import DESCRIPTION_LIMIT

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    'AUTHORS_RED',
    'CLASS_FIELD',
    'OUTCOME_VAR',
    'PRODUCING_VAR',
    'RETRYABLE',
    'Owner',
    'ProducerExit',
    'box_release_reason',
    'declared_outage',
    'full_suite_refusal',
    'licence_outage',
    'outage_env',
    'owned',
    'owner_of',
    'producing',
    'release_reason',
    'unreachable',
    'whose',
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


class Owner(StrEnum):
    """Who owns a non-PASS -- THE ONE LIST (architecture contract 6); only :attr:`CODE` is the author's red."""

    CODE = 'code'  # the commit under test: a judged FAIL, or a defect of the commit itself
    ENVIRONMENT = 'environment'  # the producer, its tree or its interpreter broke: a crash, no record, no tree
    SCHEDULING = 'scheduling'  # the box refused or killed it, a lease lapsed, a newer tip superseded it
    VENDOR_LICENCE = 'vendor-licence'  # a vendor tool's licence could not be checked out
    NETWORK = 'network'  # infrastructure it needs did not answer: a login host, the forge
    STATUS_PUBLISHING = 'status-publishing'  # the verdict exists but its status could not be posted (the outbox)


#: The description field naming a non-PASS's owner: ``class=<owner>``.
CLASS_FIELD: Final = 'class='
_CLASS: Final = re.compile(r'(?:^|\s)class=(?P<owner>[a-z-]+)\b')


def owned(owner: Owner, description: str) -> str:
    """*description* naming *owner* in its :data:`CLASS_FIELD`: appended, so every prefix a reader matches stays put.

    The description is cut to fit a status first, so the field is never the part a forge cuts off.
    """
    field = f' {CLASS_FIELD}{owner}'
    return description[: DESCRIPTION_LIMIT - len(field)] + field


def owner_of(state: str, description: str) -> Owner | None:
    """The owner a status names: a ``failure`` is :attr:`Owner.CODE`; an ``error`` its ``class=``; else ``None``.

    Read tolerantly: the field may sit anywhere among other ``key=value`` fields. An ``error`` naming no class,
    or one not in :class:`Owner`, is ``None`` -- unowned, so never the author's red and never a PASS.
    """
    if state == 'failure':
        return Owner.CODE
    found = _CLASS.search(description) if state == 'error' else None
    try:
        return Owner(found['owner']) if found else None
    except ValueError:
        return None


#: How :func:`whose` names a red its author owns; a reading's problem ending so is the commit's FAIL.
AUTHORS_RED: Final = "the author's red (class=code)"


def whose(state: str, description: str) -> str:
    """The owner an unsettled *state* names, said for a reader: ``''`` for a claim, else whose red it is.

    Architecture contract 6: an ``error`` of any class but ``code`` is NOT the author's -- it still leaves the
    commit unsettled (never a PASS, so it blocks promoting ``main``), but it is the producer's, the box's,
    the network's, a vendor licence's or the forge's to clear, and the reading says so.
    """
    if state != 'error':
        return ''
    owner = owner_of(state, description)
    if owner is Owner.CODE:
        return f'; {AUTHORS_RED}'
    return f"; not the author's (class={owner or 'unnamed'})"


#: The description prefix of a released claim the next tick may claim again (:func:`release_reason`): OPEN, not settled.
RETRYABLE: Final = 'released: unreachable'


#: The path ``forge serve`` hands its producer: a producer whose infrastructure did not answer WRITES its outage there.
OUTCOME_VAR: Final = 'DEV_LAB_PRODUCER_OUTCOME'

#: What a producer may declare (:func:`declared_outage`): an outage it did not cause, never the code's.
_OUTAGE: Final = {
    Owner.ENVIRONMENT: 'a tool it needs could not run here',
    Owner.NETWORK: 'infrastructure did not answer',
    Owner.SCHEDULING: 'the box had no room for it',
    Owner.VENDOR_LICENCE: 'a vendor licence could not be checked out',
    Owner.STATUS_PUBLISHING: 'its verdict could not be posted',
}


def unreachable(why: str, owner: Owner = Owner.NETWORK) -> int:
    """Declare an outage of *owner* in the record ``forge serve`` named (:data:`OUTCOME_VAR`); the code to exit with.

    The exit code alone is not the evidence: a command a repo declares may exit 4 itself, and read as an outage it
    would be released RETRYABLE and re-claimed every tick (sharp-review 2026-10-15). Outside serve nothing is written.
    """
    if owner not in _OUTAGE:
        msg = f'a producer declares an outage of {sorted(_OUTAGE)}, never {owner}'
        raise ValueError(msg)
    if target := os.environ.get(OUTCOME_VAR):
        Path(target).write_text(f'unreachable: {CLASS_FIELD}{owner} {why}\n', encoding='utf-8')
    return ProducerExit.UNREACHABLE


def licence_outage(why: str) -> int:
    """Declare that a vendor licence could not be checked out: released RETRYABLE as ``class=vendor-licence``."""
    return unreachable(why, Owner.VENDOR_LICENCE)


def outage_env(record: Path) -> dict[str, str]:
    """The env naming where the producer of the run boxed at *record* declares an outage (:func:`unreachable`)."""
    return {OUTCOME_VAR: str(record.with_name(f'{record.name}.producer'))}


def declared_outage(record: Path) -> Owner | None:
    """The outage the producer of the run boxed at *record* declared, ``None`` if none; the declaration is consumed.

    A declaration naming no class it may declare is :attr:`Owner.NETWORK`: infrastructure that did not answer.
    """
    said = Path(outage_env(record)[OUTCOME_VAR])
    try:
        text = said.read_text(encoding='utf-8')
    except OSError:
        return None
    finally:
        said.unlink(missing_ok=True)
    if not text.startswith('unreachable:'):
        return None
    owner = owner_of('error', text)
    return owner if owner in _OUTAGE else Owner.NETWORK


def release_reason(code: int, *, outage: Owner | None, detail: str = '') -> str:
    """The ``error`` description releasing a claim its producer left pending after exiting *code*, naming its owner.

    Exit 4 is RETRYABLE only when the producer declared the *outage* in its record; undeclared it is a crash's code.
    A producer that ends without a part never names the code's fault: every other release is the environment's.
    *detail* follows the reason, before the class.
    """
    if code == ProducerExit.UNREACHABLE and outage is not None:
        return owned(outage, f'{RETRYABLE} (exit 4) -- {_OUTAGE[outage]}; retried next tick{detail}')
    if code == ProducerExit.UNREACHABLE:
        return owned(
            Owner.ENVIRONMENT, f'released: producer exited {code} without declaring an outage -- not retried{detail}'
        )
    reasons: dict[int, str] = {
        ProducerExit.PASS: 'released: producer exited 0 (PASS) but posted no part',
        ProducerExit.FAIL: 'released: producer exited 1 (FAIL) but posted no part',
        ProducerExit.USAGE: 'released: producer refused its argv (exit 2)',
        ProducerExit.INCONCLUSIVE: 'released: inconclusive (exit 3) -- no part',
    }
    return owned(Owner.ENVIRONMENT, reasons.get(code, f'released: producer crashed (exit {code})') + detail)


def box_release_reason(ended: ProcessEnd | Refused | None) -> str | None:
    """The release a box record forces (refused, killed, or none: crashed); ``None`` when the producer ended itself.

    A refusal is RETRYABLE (nothing ran: the box had no room in time, or no enforcer); a kill and a crash
    are released naming what happened, never red.
    """
    if isinstance(ended, Refused):
        return owned(Owner.SCHEDULING, f'{RETRYABLE} -- the box refused it ({ended}); retried next tick')
    if ended is None:
        return owned(Owner.ENVIRONMENT, 'released: the box crashed -- it left no record of how the producer ended')
    if ended.killed:
        why = f'released: the box killed it past its declared {ended.reason} (exit {ended.returncode})'
        return owned(Owner.SCHEDULING, why)
    return None
