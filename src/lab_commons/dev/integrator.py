"""The integrator's merge queue, DERIVED from origin refs and commit statuses (docs-src/dev/integrator.md).

ONE PREDICATE, TWO MODES. The integrator is either WOKEN (the observer saw a lane's ``lab/gate`` go
green and pinged its session) or SELF-POLLING (a scheduled loop). Neither mode carries readiness: a
wake is "re-derive now", and both modes call :func:`ready_lanes` over the same inputs. So the queue
is never STORED -- it is recomputed from what origin holds, which makes it idempotent by
construction: a duplicate wake, a lost wake or a wake racing a poll all print the same queue.

THE RULE. A lane is an origin branch under a DECLARED prefix, not yet absorbed by the integration
branch (``git cherry``: no ``+`` line). It is READY when the LATEST gate status on its EXACT tip is
``success``; BLOCKED on ``failure``; WAITING otherwise. A status is keyed on a sha, so a moved or
force-pushed lane loses its green by construction -- there is no staleness to detect. The
integration tip, when not on ``main``, is PROMOTE on a heavy ``success``, BLOCKED on ``failure``,
HEAVY_NEEDED otherwise. Ready lanes merge oldest tip commit first, ties by branch name.

FETCH-FREE, the caller's half, exactly as in ``forgeissue``: run the fetch through the retry wrapper
first. The tips printed make a stale answer visible.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.forgestatus import GATE_CONTEXT, HEAVY_CONTEXT, Status, status_list
from lab_commons.dev.forgework import client_for
from lab_commons.log import emit

__all__ = [
    'BLOCKED',
    'HEAVY_NEEDED',
    'MERGE',
    'PROMOTE',
    'WAITING',
    'LaneRef',
    'Policy',
    'Queue',
    'Queued',
    'gate_ready',
    'load_policy',
    'main',
    'read_refs',
    'ready_lanes',
]

MERGE: Final = 'merge'
BLOCKED: Final = 'blocked'
WAITING: Final = 'waiting'
PROMOTE: Final = 'promote'
HEAVY_NEEDED: Final = 'heavy-needed'

_SUCCESS: Final = 'success'
_FAILURE: Final = 'failure'
_TRACKING: Final = 'refs/remotes/origin/'
_TABLE: Final = 'integrator'


@dataclass(frozen=True)
class Policy:
    """What a consumer declares in ``[tool.lab_commons.integrator]``: names only, never a rule."""

    lane_prefixes: tuple[str, ...] = ('feat/', 'fix/')
    integration: str = 'integrate/main'
    main: str = 'main'
    gate_context: str = GATE_CONTEXT
    heavy_context: str = HEAVY_CONTEXT
    #: The test trees :mod:`lab_commons.dev.mergeaudit` reads; every merge a push publishes is audited over them.
    test_roots: tuple[str, ...] = ('tests',)


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


def gate_ready(state: str) -> bool:
    """THE ready predicate on a gate state -- ``forgeissue`` derives ``ready`` from this same call."""
    return state == _SUCCESS


def _lane_state(state: str) -> str:
    if gate_ready(state):
        return MERGE
    return BLOCKED if state == _FAILURE else WAITING


def _heavy_state(state: str) -> str:
    if state == _SUCCESS:
        return PROMOTE
    return BLOCKED if state == _FAILURE else HEAVY_NEEDED


def ready_lanes(refs: Sequence[LaneRef], statuses: Mapping[str, Mapping[str, str]], policy: Policy) -> Queue:
    """The queue, as a pure function of the refs and the latest state per context per tip sha."""

    def state(ref: LaneRef, context: str) -> str:
        return statuses.get(ref.tip, {}).get(context, '')

    lanes = sorted(
        (ref for ref in refs if ref.branch.startswith(policy.lane_prefixes) and not ref.absorbed),
        key=lambda ref: (ref.committed_at, ref.branch),
    )
    rows = [Queued(ref.branch, ref.tip, _lane_state(state(ref, policy.gate_context))) for ref in lanes]
    integration = next((ref for ref in refs if ref.branch == policy.integration and not ref.absorbed), None)
    promotion = (
        None
        if integration is None
        else Queued(integration.branch, integration.tip, _heavy_state(state(integration, policy.heavy_context)))
    )
    return Queue(
        tuple(row for row in rows if row.state == MERGE),
        tuple(row for row in rows if row.state != MERGE),
        promotion,
    )


def load_policy(root: Path) -> Policy:
    """*root*'s ``[tool.lab_commons.integrator]``, defaults for what it omits; an unknown key is refused."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return Policy()
    with manifest.open('rb') as handle:
        declared = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get(_TABLE, {})
    known = {field.name for field in dataclasses.fields(Policy)}
    unknown = sorted(set(declared) - known)
    if unknown:
        msg = f'[tool.lab_commons.{_TABLE}] in {manifest} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    declared = declared | {key: tuple(declared[key]) for key in ('lane_prefixes', 'test_roots') if key in declared}
    return Policy(**declared)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
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


def read_refs(root: Path, policy: Policy) -> tuple[LaneRef, ...]:
    """Declared lanes and the integration branch from *root*'s remote-tracking refs. Fetches nothing."""
    listed = _git(root, 'for-each-ref', '--format=%(refname) %(objectname) %(committerdate:unix)', _TRACKING)
    found = []
    for line in listed.splitlines():
        ref, tip, at = line.split(' ')
        branch = ref.removeprefix(_TRACKING)
        if branch == policy.integration:
            target = policy.main
        elif branch.startswith(policy.lane_prefixes):
            target = policy.integration
        else:
            continue
        found.append(LaneRef(branch, tip, int(at), absorbed=_absorbed(root, target, tip)))
    return tuple(found)


def _latest(found: Sequence[Status]) -> dict[str, str]:
    return {status.context: status.state for status in found}


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

    refs = read_refs(root, policy)
    queue = ready_lanes(refs, {ref.tip: _latest(statuses(ref.tip)) for ref in refs if not ref.absorbed}, policy)
    emit(json.dumps(dataclasses.asdict(queue), indent=2) if args.json else _render(queue))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
