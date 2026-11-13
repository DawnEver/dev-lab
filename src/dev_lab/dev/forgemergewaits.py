"""What a PR head's posted statuses lack before the forge merges it: read off the statuses, nothing written.

Split out of :mod:`dev_lab.dev.forgemerge` (the merge DECISION), which asks :func:`status_waits` once per head.
A repo declaring ``[tool.dev_lab.integrator] merge_checks`` waits on those checks (:func:`checks_wait`);
otherwise on the serve-posted ones -- ``tests/security``, the head gates, and every HOSTED test part standing
PASS (:func:`parts_wait`). A hand part (:func:`hand_parts`, user ruling 2026-11-10) is named, never waited on.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from lab_commons.hpc.needsets import BASE
from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgeheadgate import gates_wait
from dev_lab.dev.forgesecurity import security_wait
from dev_lab.dev.partrows import row_part
from dev_lab.dev.platformparts import derived, part_context, parts_of, standing

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.lanepolicy import Policy

__all__ = ['RED', 'checks_wait', 'hand_note', 'hand_parts', 'parts_wait', 'red_checks', 'status_waits']

#: The terminal red states of a status, on both forges: the check FAILED, it is not waiting.
RED: Final = frozenset({'failure', 'error'})


def hand_parts(statuses: Sequence[CommitStatus]) -> frozenset[str]:
    """The parts *statuses* derive that only a hand host produces: every part but :data:`BASE` and its OS rows.

    USER RULING 2026-11-10: such a part (``windows``, ``gpu``, ``vendor``...) is tested LATER, when a hand host has
    room, and is never a merge condition; a hosted runner produces ``tests/base`` and each ``tests/base@<os>``.
    """
    parts, _ = parts_of(statuses)
    return frozenset(name for name in {*derived(statuses), *parts} if row_part(name) != BASE)


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
    parts = standing(statuses, head=head, waived=hand_parts(statuses))
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


def status_waits(policy: Policy, head: str, statuses: Sequence[CommitStatus]) -> list[str]:
    """What *head*'s posted statuses lack: the repo's declared merge checks, else every serve-posted status.

    User ruling 2026-11-12: a repo declaring ``merge_checks`` waits on them IN PLACE of the test parts,
    ``tests/security`` and the head gates, which only a serve host posts.
    """
    if policy.merge_checks:
        checked = checks_wait(policy.merge_checks, statuses)
        return [] if checked is None else [f'its merge checks: {checked}']
    said = [
        ('its security check', security_wait(statuses)),
        ('its head gates', gates_wait(statuses)),
        ('its test parts', parts_wait(head, statuses)),
    ]
    return [f'{what}: {why}' for what, why in said if why is not None]


def red_checks(statuses: Sequence[CommitStatus]) -> tuple[str, ...]:
    """The contexts in *statuses* standing terminal red (``failure``/``error``), every hand part excluded."""
    hands = {part_context(name) for name in hand_parts(statuses)}
    latest = {status.context: status for status in statuses}
    return tuple(c for c, s in latest.items() if s.state in RED and c not in hands)
