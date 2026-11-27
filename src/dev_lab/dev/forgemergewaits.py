"""What a PR head's posted statuses lack before the forge merges it: read off the statuses, nothing written.

Split out of :mod:`dev_lab.dev.forgemerge` (the merge DECISION), which asks :func:`status_waits` once per head.
A repo declaring ``[tool.dev_lab.integrator] merge_checks`` waits on those checks (:func:`checks_wait`);
a repo whose ``tests`` are bound to ``ci`` (:mod:`dev_lab.dev.roles`) only on the parts Actions post
(:func:`actions_wait`);
otherwise on the serve-posted ones -- ``tests/security``, the head gates, and every GATING test part standing
PASS (:func:`parts_wait`): ``base``, and the parts of each OS the repo's ``[tool.dev_lab.integrator]
merge_systems`` names (:func:`gates`; the family default is Windows, user ruling 2026-11-27), ``cargo``, and each
part a pull request's own hosted job produces. Any other part is a hand part (:func:`hand_parts`, user ruling
2026-11-10), named, never waited on;
nor is a part released under a class that is not the code's (:func:`requeued_parts`, W5 dev-lab#644): no part
posted, no grant had room, a QOS refusal is the environment's or the schedule's, requeued
(:mod:`dev_lab.dev.requeue`), never the author's wait.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Final

from lab_commons.hpc.needsets import BASE
from lab_commons.outcomes import Conclusion

from dev_lab.dev import cargostep
from dev_lab.dev.forgeheadgate import gates_wait
from dev_lab.dev.forgesecurity import security_wait
from dev_lab.dev.partrows import row_part, row_system
from dev_lab.dev.platformparts import derived, part_context, parts_of, standing
from dev_lab.dev.producer import Owner, owner_of
from dev_lab.dev.roles import CI

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.lanepolicy import Policy

__all__ = [
    'RECORD_LINE',
    'RED',
    'actions_wait',
    'checks_wait',
    'gates',
    'green_waits',
    'hand_note',
    'hand_parts',
    'off_record',
    'parts_wait',
    'recorded_as_ran',
    'red_checks',
    'requeued_parts',
    'status_waits',
]

#: The terminal red states of a status, on both forges: the check FAILED, it is not waiting.
RED: Final = frozenset({'failure', 'error'})
#: RED-INTEGRATION-MERGES: the PR line that puts one red part ON RECORD, its residual named after ``--``.
RECORD_LINE: Final = 'Red-On-Record: <part> -- <residual>'
_RECORD: Final = re.compile(r'^Red-On-Record:\s*(?P<part>\S+)\s+--\s*(?P<residual>\S.*)$', re.MULTILINE)
_PART_PREFIX: Final = 'tests/'


def gates(name: str, *, systems: Collection[str], hosted: Collection[str]) -> bool:
    """Whether part (or row) *name* is a merge condition under the repo's merge *systems* and *hosted* parts.

    ``base`` always; a row of it (``base@windows``) and an OS part (``windows``) when its OS is one of *systems*
    (user ruling 2026-11-27, dev-lab #1045: Windows gates as base does, macOS is tested later); ``cargo``, which a
    hosted runner produces (dev-lab#1033: fmt and clippy drift landed on integration unchecked while it was a hand
    part); and each part in *hosted*, which a pull request's own hosted job produces
    (:func:`dev_lab.dev.hostedparts.pull_request_parts`): being in another part's ``hands=`` makes none of those a
    hand part (dev-lab#1024). Every other part -- a resource's (``gpu``, ``femm+windows``) or an OS's outside
    *systems* -- is a hand part (:func:`hand_parts`).
    """
    part, system = row_part(name), row_system(name)
    if part == BASE:
        return not system or system in systems
    return part == cargostep.PART or name in hosted or (not system and part in systems)


def _ran_red(
    statuses: Sequence[CommitStatus], *, systems: Collection[str], hosted: Collection[str]
) -> dict[str, CommitStatus]:
    """The gating parts that RAN and failed: a judged FAIL, or an error its own code caused (``class=code``).

    Hand and requeued parts never hold a merge (:func:`red_checks` drops them), nor does ``tests/review``; every
    gating part is put on record the same way.
    """
    latest = {status.context: status for status in statuses}
    return {
        c: latest[c]
        for c in red_checks(statuses, systems=systems, hosted=hosted)
        if c.startswith(_PART_PREFIX)
        and gates(c.removeprefix(_PART_PREFIX), systems=systems, hosted=hosted)
        and (latest[c].state == 'failure' or 'class=code' in latest[c].description)
    }


def _recorded(record: str) -> frozenset[str]:
    return frozenset(found.group('part') for found in _RECORD.finditer(record))


def off_record(
    statuses: Sequence[CommitStatus], record: str, *, systems: Collection[str], hosted: Collection[str]
) -> list[str]:
    """The wait for the test parts standing red in *statuses* that *record* (the PR body) does not put on record."""
    if off := sorted(set(_ran_red(statuses, systems=systems, hosted=hosted)) - _recorded(record)):
        return [f'its red parts on record: add `{RECORD_LINE}` to the PR for {", ".join(off)}']
    return []


def recorded_as_ran(
    statuses: Sequence[CommitStatus], record: str, *, systems: Collection[str], hosted: Collection[str]
) -> tuple[CommitStatus, ...]:
    """*statuses* with every red test part ON RECORD in *record* read as ran (``success``) -- integration only.

    User ruling RED-INTEGRATION-MERGES: integration MAY be red, so a part that RAN and failed is no wait once its
    residual is named. A pending or absent part is untouched and still waits; promote to the trunk never reads this.
    """
    on = _ran_red(statuses, systems=systems, hosted=hosted).keys() & _recorded(record)
    return tuple(dataclasses.replace(s, state='success') if s.context in on and s.state in RED else s for s in statuses)


def hand_parts(
    statuses: Sequence[CommitStatus], *, systems: Collection[str], hosted: Collection[str]
) -> frozenset[str]:
    """The parts *statuses* derive that no merge waits on: every part :func:`gates` refuses.

    USER RULING 2026-11-10: such a part (``gpu``, ``vendor``...) is tested LATER, when a hand host has room, and is
    never a merge condition. USER RULING 2026-11-27: the OS parts of the repo's merge systems are not among them.
    """
    parts, _ = parts_of(statuses)
    return frozenset(name for name in {*derived(statuses), *parts} if not gates(name, systems=systems, hosted=hosted))


def requeued_parts(statuses: Sequence[CommitStatus]) -> frozenset[str]:
    """The parts whose latest ``tests/<part>`` stands ``error`` under an owner class other than :attr:`Owner.CODE`."""
    latest = {status.context: status for status in statuses}
    return frozenset(
        context.removeprefix(part_context(''))
        for context, status in latest.items()
        if context.startswith(part_context('')) and owner_of(status.state, status.description) not in {None, Owner.CODE}
    )


def hand_note(statuses: Sequence[CommitStatus], *, systems: Collection[str], hosted: Collection[str]) -> str | None:
    """How *statuses*' hand parts stand, each by name (``tests/windows FAIL``), or ``None`` when there is none.

    It is said, never waited on: absent, unposted or red, a hand part is a later finding (:func:`hand_parts`).
    """
    hands = hand_parts(statuses, systems=systems, hosted=hosted)
    if not hands:
        return None
    parts, _ = parts_of(statuses)
    latest = {status.context: status for status in statuses}

    def said(name: str) -> str:
        context = part_context(name)
        if name in parts:
            return f'{context} {parts[name].result.name}'
        status = latest.get(context)
        return f'{context} not posted' if status is None else f'{context} {status.state} ({status.description})'

    return 'hand parts, tested later, never a merge condition: ' + ', '.join(said(name) for name in sorted(hands))


def parts_wait(
    head: str, statuses: Sequence[CommitStatus], *, systems: Collection[str], hosted: Collection[str]
) -> str | None:
    """Why *head*'s hosted test parts do not all stand PASS, or ``None``: the one :func:`standing` reading.

    Every hand part (:func:`hand_parts`) is waived -- an unproduced one and a secrets-hosted one (produced only on a
    full run, never for a pull request) among them; a part in *hosted* a pull request's own job produces never is.
    """
    parts = standing(
        statuses, head=head, waived=hand_parts(statuses, systems=systems, hosted=hosted) | requeued_parts(statuses)
    )
    if parts.result is Conclusion.PASS:
        return None
    return '; '.join([f'they stand {parts.reading}', *parts.problems])


def checks_wait(checks: Sequence[str], statuses: Sequence[CommitStatus]) -> str | None:
    """Why the declared *checks* do not all stand ``success`` in *statuses*, or ``None``: each one named.

    A check not yet posted, or posted ``pending``, waits (``is pending``); ``failure`` or ``error`` FAILED and says
    so -- a job that ended without a record is never read as one still running. Nothing else stands in.
    """
    latest = {status.context: status for status in statuses}
    said = []
    for context in checks:
        held = latest.get(context)
        if held is None:
            said.append(f'{context} is not yet posted')
        elif held.state in RED:
            said.append(f'{context} FAILED ({held.state}): {held.description}')
        elif held.state != 'success':
            said.append(f'{context} is {held.state}: {held.description}')
    return '; '.join(said) or None


def actions_wait(
    head: str, statuses: Sequence[CommitStatus], *, systems: Collection[str], hosted: Collection[str]
) -> str | None:
    """Why the parts forge Actions post for *head* -- the base rows -- do not all stand PASS, or ``None``.

    A repo whose ``tests`` are bound to ``ci`` (:mod:`dev_lab.dev.roles`) has no serve host, so nothing here is
    UNCLAIMED or waits on a host: a base part not yet posted is Actions' run still to come.
    """
    if not any(status.context.startswith(part_context(BASE)) for status in statuses):
        return (
            f'forge Actions has not yet posted {part_context(BASE)} for {head[:12]}: its ci.yml run is still to come '
            '(a parts job that derives no matrix posts it red, naming why)'
        )
    return parts_wait(head, statuses, systems=systems, hosted=hosted)


def green_waits(
    head: str, statuses: Sequence[CommitStatus], *, tests: str, systems: Collection[str], hosted: Collection[str]
) -> list[str]:
    """Why *head* is not green as *tests* (its ``tests`` kind) posts it; break-glass reads green through this alone.

    :func:`actions_wait` for ``ci``, else the security check and the test parts a serve host posts.
    """
    if tests == CI:
        waits = [actions_wait(head, statuses, systems=systems, hosted=hosted)]
    else:
        waits = [security_wait(statuses), parts_wait(head, statuses, systems=systems, hosted=hosted)]
    return [wait for wait in waits if wait is not None]


def status_waits(
    policy: Policy, head: str, statuses: Sequence[CommitStatus], *, tests: str, hosted: Collection[str]
) -> list[str]:
    """What *head*'s posted statuses lack: the repo's declared merge checks, else what its *tests* executor posts.

    User ruling 2026-11-12: a repo declaring ``merge_checks`` waits on them IN PLACE of the test parts,
    ``tests/security`` and the head gates, which only a serve host posts. User ruling 2026-11-16: a repo with
    ``tests`` bound to ``ci`` waits only on the parts forge Actions post (:func:`actions_wait`), never on a
    serve-posted status.
    """
    if policy.merge_checks:
        checked = checks_wait(policy.merge_checks, statuses)
        return [] if checked is None else [f'its merge checks: {checked}']
    if tests == CI:
        waited = actions_wait(head, statuses, systems=policy.merge_systems, hosted=hosted)
        return [] if waited is None else [f'its test parts: {waited}']
    said = [
        ('its security check', security_wait(statuses)),
        ('its head gates', gates_wait(statuses)),
        ('its test parts', parts_wait(head, statuses, systems=policy.merge_systems, hosted=hosted)),
    ]
    return [f'{what}: {why}' for what, why in said if why is not None]


def red_checks(
    statuses: Sequence[CommitStatus], *, systems: Collection[str], hosted: Collection[str]
) -> tuple[str, ...]:
    """The contexts in *statuses* standing terminal red (``failure``/``error``), hand and requeued parts excluded."""
    hands = {
        part_context(name) for name in hand_parts(statuses, systems=systems, hosted=hosted) | requeued_parts(statuses)
    }
    latest = {status.context: status for status in statuses}
    return tuple(c for c, s in latest.items() if s.state in RED and c not in hands)
