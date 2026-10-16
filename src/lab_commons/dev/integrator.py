"""The integrator's merge queue, DERIVED from origin refs and commit statuses (docs-src/dev/integrator.md).

ONE PREDICATE, TWO MODES. The integrator is either WOKEN (the observer saw a lane's parts go green
and pinged its session) or SELF-POLLING (a scheduled loop). Neither mode carries readiness: a
wake is "re-derive now", and both modes call :func:`ready_lanes` over the same inputs. So the queue
is never STORED -- it is recomputed from what origin holds, which makes it idempotent by
construction: a duplicate wake, a lost wake or a wake racing a poll all print the same queue.

THE RULE. A lane is an origin branch the schedule's ONE RULE classes (``[tool.lab_commons.schedule]
classes_by_ref``, :meth:`lab_commons.compute.model.Schedule.class_of`), not yet absorbed by the integration
branch (``git cherry``: no ``+`` line). ONE NAME FOR A PLATFORM RESULT: the ``tests/<part>``
parts on a tip (:func:`lab_commons.dev.platformparts.standing`), the same reading push admission
makes. A lane is READY when its EXACT tip's parts stand PASS (any scope); BLOCKED on a FAIL part;
WAITING otherwise. A status is keyed on a sha, so a moved or force-pushed lane loses its green by
construction. The integration tip, when not on ``main``, is PROMOTE when its parts stand PASS at
scope ``full`` (what the trunk admits), BLOCKED on a FAIL part, PARTS_NEEDED otherwise. Ready lanes
merge oldest tip commit first, ties by branch name.

THE FORGE PROMPTS THE INTEGRATOR. A wake is the observer's half, and the observer is ``forge serve``: EVERY
serving host derives this same queue (:func:`observe`) on each tick -- no host owns integration -- and the
rows that ask the integrator to act (:func:`prompts`: a READY lane, a PROMOTE-able tip, a BLOCKED red to
route) are kept as ONE forge issue per row (:func:`lab_commons.dev.forgeroute.reconcile`, titled
``integration: <subject>``), so N hosts write one issue and only the host that creates or changes it pages.
Nothing else is stored.

FETCH-FREE, the caller's half, exactly as in ``forgeissue``: run the fetch through the retry wrapper
first. The tips printed make a stale answer visible.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.compute.model import Schedule
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.forgealarm import INTEGRATION, Alarm
from lab_commons.dev.forgeschedule import load_schedule
from lab_commons.dev.forgestatus import Status, status_list
from lab_commons.dev.forgework import client_for
from lab_commons.dev.lanepolicy import Policy, load_policy
from lab_commons.dev.platformparts import standing
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit

__all__ = [
    'BLOCKED',
    'MERGE',
    'PARTS_NEEDED',
    'PROMOTE',
    'WAITING',
    'LaneRef',
    'Queue',
    'Queued',
    'derive',
    'lane_ready',
    'main',
    'observe',
    'prompts',
    'read_refs',
    'ready_lanes',
]

MERGE: Final = 'merge'
BLOCKED: Final = 'blocked'
WAITING: Final = 'waiting'
PROMOTE: Final = 'promote'
PARTS_NEEDED: Final = 'parts-needed'

_TRACKING: Final = 'refs/remotes/origin/'


@dataclass(frozen=True)
class LaneRef:
    """One origin branch: its tip, the tip's commit time, and whether its target already holds it.

    For a lane the target is the integration branch; for the integration branch it is ``main``.
    """

    branch: str
    tip: str
    committed_at: int
    absorbed: bool = False


@dataclass(frozen=True)
class Queued:
    """One queue row: a branch at a tip, and what the integrator should do with it."""

    branch: str
    tip: str
    state: str


@dataclass(frozen=True)
class Queue:
    """``merge`` in order; ``held`` lanes not ready; ``promotion`` the integration tip not on main."""

    merge: tuple[Queued, ...]
    held: tuple[Queued, ...]
    promotion: Queued | None


def lane_ready(statuses: Sequence[Status], *, head: str) -> bool:
    """THE ready predicate on a lane tip -- ``forgeissue`` derives ``ready`` from this same call."""
    return standing(statuses, head=head).result == 'PASS'


def _lane_state(statuses: Sequence[Status], head: str) -> str:
    result = standing(statuses, head=head).result
    if result == 'PASS':
        return MERGE
    return BLOCKED if result == 'FAIL' else WAITING


def _promotion_state(statuses: Sequence[Status], head: str) -> str:
    result = standing(statuses, head=head, scope=FULL).result
    if result == 'PASS':
        return PROMOTE
    return BLOCKED if result == 'FAIL' else PARTS_NEEDED


def ready_lanes(refs: Sequence[LaneRef], statuses: Mapping[str, Sequence[Status]], policy: Policy) -> Queue:
    """The queue, as a pure function of the refs and the latest statuses per tip sha."""
    lanes = sorted(
        (ref for ref in refs if ref.branch not in {policy.integration, policy.trunk} and not ref.absorbed),
        key=lambda ref: (ref.committed_at, ref.branch),
    )
    rows = [Queued(ref.branch, ref.tip, _lane_state(statuses.get(ref.tip, ()), ref.tip)) for ref in lanes]
    integration = next((ref for ref in refs if ref.branch == policy.integration and not ref.absorbed), None)
    promotion = (
        None
        if integration is None
        else Queued(
            integration.branch, integration.tip, _promotion_state(statuses.get(integration.tip, ()), integration.tip)
        )
    )
    return Queue(
        tuple(row for row in rows if row.state == MERGE),
        tuple(row for row in rows if row.state != MERGE),
        promotion,
    )


def _git(root: Path, *args: str) -> str:
    done = _door.run(
        [_GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    return done.stdout if done.returncode == 0 else ''


def _absorbed(root: Path, target: str, tip: str) -> bool:
    # ``git cherry``: a ``+`` line is a commit whose change the target does not hold. Ancestry alone
    # would answer NO for a cherry-picked or rebased lane whose content IS present.
    return not any(line.startswith('+') for line in _git(root, 'cherry', f'{_TRACKING}{target}', tip).splitlines())


def read_refs(root: Path, policy: Policy, schedule: Schedule) -> tuple[LaneRef, ...]:
    """The lanes *schedule* classes and the integration branch, from *root*'s remote-tracking refs. Fetches nothing."""
    listed = _git(root, 'for-each-ref', '--format=%(refname) %(objectname) %(committerdate:unix)', _TRACKING)
    found = []
    for line in listed.splitlines():
        ref, tip, at = line.split(' ')
        branch = ref.removeprefix(_TRACKING)
        if branch == policy.integration:
            target = policy.trunk
        elif branch != policy.trunk and schedule.class_of(branch) is not None:
            target = policy.integration
        else:
            continue
        found.append(LaneRef(branch, tip, int(at), absorbed=_absorbed(root, target, tip)))
    return tuple(found)


def derive(root: Path, policy: Policy, schedule: Schedule, statuses: Callable[[str], Sequence[Status]]) -> Queue:
    """The queue of *root* as last fetched: :func:`read_refs`, each live tip's *statuses*, :func:`ready_lanes`."""
    refs = read_refs(root, policy, schedule)
    return ready_lanes(refs, {ref.tip: tuple(statuses(ref.tip)) for ref in refs if not ref.absorbed}, policy)


_ASKS: Final = {
    MERGE: 'is READY: merge it into integration',
    PROMOTE: 'is PROMOTE-able: python -m lab_commons.dev.integrate promote <sha>',
    BLOCKED: 'is BLOCKED on a red part: route it',
}


def prompts(queue: Queue, repo: str) -> list[Alarm]:
    """One ``integration`` alarm per row of *queue* that asks the integrator to act, keyed by state, branch, tip."""
    rows = [*queue.merge, *queue.held, *([queue.promotion] if queue.promotion else [])]
    return [
        Alarm(
            INTEGRATION,
            repo,
            f'{row.branch} {_ASKS[row.state]}',
            f'{row.branch} at {row.tip[:12]} {_ASKS[row.state]} (python -m lab_commons.dev.integrator queue)',
            about=f'{row.state} {row.branch}@{row.tip[:12]}',
        )
        for row in rows
        if row.state in _ASKS
    ]


def observe(root: Path, repo: str, *, statuses: Callable[[str], Sequence[Status]]) -> list[Alarm]:
    """The prompts for *root*'s queue, derived by any host; the forge keeps one issue per row."""
    return prompts(derive(root, load_policy(root), load_schedule(root), statuses), repo)


def _render(queue: Queue) -> str:
    rows = [*queue.merge, *queue.held, *([queue.promotion] if queue.promotion else [])]
    return '\n'.join(f'{row.state}  {row.branch}  {row.tip[:12]}' for row in rows) or 'queue: empty'


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    statuses: Callable[[str], Sequence[Status]] | None = None,
) -> int:
    """``python -m lab_commons.dev.integrator queue [--json]``: the ordered queue, after the caller's fetch."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.integrator', description='the derived merge queue')
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('queue').add_argument('--json', action='store_true', help='print the queue as JSON')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    policy = load_policy(root)
    if statuses is None:
        client = client_for(root)

        def statuses(sha: str) -> Sequence[Status]:
            return status_list(client, sha)

    queue = derive(root, policy, load_schedule(root), statuses)
    emit(json.dumps(dataclasses.asdict(queue), indent=2) if args.json else _render(queue))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
