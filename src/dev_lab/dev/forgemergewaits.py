"""What a PR head's posted statuses lack before the forge merges it: read off the statuses, nothing written.

Split out of :mod:`dev_lab.dev.forgemerge` (the merge DECISION), which asks :func:`status_waits` once per head.
A repo declaring ``[tool.dev_lab.integrator] merge_checks`` waits on those checks (:func:`checks_wait`);
a repo whose ``tests`` are bound to ``ci`` (:mod:`dev_lab.dev.roles`) only on the parts Actions post
(:func:`actions_wait`);
otherwise on the serve-posted ones -- ``tests/security``, the head gates, and every HOSTED test part standing
PASS (:func:`parts_wait`). A hand part (:func:`hand_parts`, user ruling 2026-11-10) is named, never waited on;
nor is a part released under a class that is not the code's (:func:`requeued_parts`, W5 dev-lab#644): no part
posted, no grant had room, a QOS refusal is the environment's or the schedule's, requeued
(:mod:`dev_lab.dev.requeue`), never the author's wait.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from lab_commons.hpc.needsets import BASE
from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgeheadgate import gates_wait
from dev_lab.dev.forgesecurity import security_wait
from dev_lab.dev.partrows import row_part
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


def _ran_red(statuses: Sequence[CommitStatus]) -> dict[str, CommitStatus]:
    """The hosted base parts that RAN and failed: a judged FAIL, or an error its own code caused (``class=code``).

    Hand and requeued parts never hold a merge (:func:`red_checks` drops them), nor does ``tests/review``.
    """
    latest = {status.context: status for status in statuses}
    return {
        c: latest[c]
        for c in red_checks(statuses)
        if c.startswith(_PART_PREFIX)
        and row_part(c.removeprefix(_PART_PREFIX)) == BASE
        and (latest[c].state == 'failure' or 'class=code' in latest[c].description)
    }


def _recorded(record: str) -> frozenset[str]:
    return frozenset(found.group('part') for found in _RECORD.finditer(record))


def off_record(statuses: Sequence[CommitStatus], record: str) -> list[str]:
    """The wait for the test parts standing red in *statuses* that *record* (the PR body) does not put on record."""
    if off := sorted(set(_ran_red(statuses)) - _recorded(record)):
        return [f'its red parts on record: add `{RECORD_LINE}` to the PR for {", ".join(off)}']
    return []


def recorded_as_ran(statuses: Sequence[CommitStatus], record: str) -> tuple[CommitStatus, ...]:
    """*statuses* with every red test part ON RECORD in *record* read as ran (``success``) -- integration only.

    User ruling RED-INTEGRATION-MERGES: integration MAY be red, so a part that RAN and failed is no wait once its
    residual is named. A pending or absent part is untouched and still waits; promote to the trunk never reads this.
    """
    on = _ran_red(statuses).keys() & _recorded(record)
    return tuple(dataclasses.replace(s, state='success') if s.context in on and s.state in RED else s for s in statuses)


def hand_parts(statuses: Sequence[CommitStatus]) -> frozenset[str]:
    """The parts *statuses* derive that only a hand host produces: every part but :data:`BASE` and its OS rows.

    USER RULING 2026-11-10: such a part (``windows``, ``gpu``, ``vendor``...) is tested LATER, when a hand host has
    room, and is never a merge condition; a hosted runner produces ``tests/base`` and each ``tests/base@<os>``.
    """
    parts, _ = parts_of(statuses)
    return frozenset(name for name in {*derived(statuses), *parts} if row_part(name) != BASE)


def requeued_parts(statuses: Sequence[CommitStatus]) -> frozenset[str]:
    """The parts whose latest ``tests/<part>`` stands ``error`` under an owner class other than :attr:`Owner.CODE`."""
    latest = {status.context: status for status in statuses}
    return frozenset(
        context.removeprefix(part_context(''))
        for context, status in latest.items()
        if context.startswith(part_context('')) and owner_of(status.state, status.description) not in {None, Owner.CODE}
    )


def hand_note(statuses: Sequence[CommitStatus]) -> str | None:
    """How *statuses*' hand parts stand, each by name (``tests/windows FAIL``), or ``None`` when there is none.

    It is said, never waited on: absent, unposted or red, a hand part is a later finding (:func:`hand_parts`).
    """
    hands = hand_parts(statuses)
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


def parts_wait(head: str, statuses: Sequence[CommitStatus]) -> str | None:
    """Why *head*'s hosted test parts do not all stand PASS, or ``None``: the one :func:`standing` reading.

    Every hand part (:func:`hand_parts`) is waived -- an unproduced one and a secrets-hosted one (produced only on a
    full run, never for a pull request) among them.
    """
    parts = standing(statuses, head=head, waived=hand_parts(statuses) | requeued_parts(statuses))
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


def actions_wait(head: str, statuses: Sequence[CommitStatus]) -> str | None:
    """Why the parts forge Actions post for *head* -- the base rows -- do not all stand PASS, or ``None``.

    A repo whose ``tests`` are bound to ``ci`` (:mod:`dev_lab.dev.roles`) has no serve host, so nothing here is
    UNCLAIMED or waits on a host: a base part not yet posted is Actions' run still to come.
    """
    if not any(status.context.startswith(part_context(BASE)) for status in statuses):
        return (
            f'forge Actions has not yet posted {part_context(BASE)} for {head[:12]}: its ci.yml run is still to come '
            '(a parts job that derives no matrix posts it red, naming why)'
        )
    return parts_wait(head, statuses)


def green_waits(head: str, statuses: Sequence[CommitStatus], *, tests: str) -> list[str]:
    """Why *head* is not green as *tests* (its ``tests`` kind) posts it; break-glass reads green through this alone.

    :func:`actions_wait` for ``ci``, else the security check and the test parts a serve host posts.
    """
    waits = [actions_wait(head, statuses)] if tests == CI else [security_wait(statuses), parts_wait(head, statuses)]
    return [wait for wait in waits if wait is not None]


def status_waits(policy: Policy, head: str, statuses: Sequence[CommitStatus], *, tests: str) -> list[str]:
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
        waited = actions_wait(head, statuses)
        return [] if waited is None else [f'its test parts: {waited}']
    said = [
        ('its security check', security_wait(statuses)),
        ('its head gates', gates_wait(statuses)),
        ('its test parts', parts_wait(head, statuses)),
    ]
    return [f'{what}: {why}' for what, why in said if why is not None]


def red_checks(statuses: Sequence[CommitStatus]) -> tuple[str, ...]:
    """The contexts in *statuses* standing terminal red (``failure``/``error``), hand and requeued parts excluded."""
    hands = {part_context(name) for name in hand_parts(statuses) | requeued_parts(statuses)}
    latest = {status.context: status for status in statuses}
    return tuple(c for c, s in latest.items() if s.state in RED and c not in hands)
