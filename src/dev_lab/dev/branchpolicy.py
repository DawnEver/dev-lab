"""BRANCH-POLICY-OBSERVED: an unlanded origin branch too far behind integration, or idle too long, is an issue.

User ruling D46 (integrator, 2026-11-19): the branch policy is a per-repo DECLARATION in
``[tool.dev_lab.branchset]`` (:mod:`dev_lab.dev.branchset`) and an OBSERVER derives what breaks it:

* :data:`OVER_AHEAD` -- integration holds more than ``max_ahead`` commits the branch lacks (unjudged when the key
  is absent). Its doors: SYNC it (merge integration into it through a sync PR), or RETIRE it.
* :data:`STALE` -- its tip has sat idle for ``max_idle_hours`` (the same bound the prune deletes a merged branch
  by). Its doors: LAND it through a PR, or RETIRE it.

RETIRING is the user's call, never the observer's: LAND the branch with a declared ``git merge -s ours`` PR into a
``pr/`` head, then ``branchprune delete`` it (LOSSLESS-DELETE). A branch merged into integration or the trunk is
never a row: the prune owns it (:mod:`dev_lab.dev.branchprune`).

ONE ISSUE PER ROW, KEYED STABLY. A row's title is ``integration: branch policy <kind> <branch>`` -- no sha, so a
branch that moves keeps its issue -- and :func:`observe` reconciles the open issues under that prefix
(:func:`dev_lab.dev.forgeroute.reconcile`): a new row opens one, a changed body updates it, re-observing writes
nothing, and a row that cleared CLOSES its issue. Read from the local refs: the caller fetches first.

WHO RUNS IT is the ``prune`` role's executor (:mod:`dev_lab.dev.roles`) -- :func:`prune_duty`, the one pass every
executor kind calls, so a policy is observed and a merged head deleted in exactly one place per repo.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.branchdelete import DOOR, serve_sweep
from dev_lab.dev.branchprune import serve_prune
from dev_lab.dev.branchset import BranchSet, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.deletejudge import ORIGIN
from dev_lab.dev.forge import Forge, fetch_origin, forge_from_remote
from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete
from dev_lab.dev.forgerecords import serve_prune as serve_records_prune
from dev_lab.dev.forgeroute import Routed, reconcile
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.prlanded import serve_close_landed
from dev_lab.dev.roles import PRUNE, Roles, Unbound, performs, roles_at

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['OVER_AHEAD', 'PREFIX', 'STALE', 'PolicyRow', 'derive', 'observe', 'prune_duty', 'run_here', 'wanted']

OVER_AHEAD: Final = 'over-ahead'
STALE: Final = 'stale'
#: Every policy issue's title starts so; :func:`observe` owns exactly the open issues under it.
PREFIX: Final = 'integration: branch policy '
_HOUR_S: Final = 3600.0


@dataclass(frozen=True)
class PolicyRow:
    """One unlanded origin branch breaking one bound: its tip, where it stands against integration, its idle age."""

    kind: str
    branch: str
    tip: str
    ahead: int
    behind: int
    idle_h: float

    @property
    def title(self) -> str:
        """The stable key: kind and branch, never the tip."""
        return f'{PREFIX}{self.kind} {self.branch}'

    def body(self, integration: str, bound: str) -> str:
        """The row, the bound it breaks, and its doors."""
        first = 'sync it: merge {i} into it through a sync PR' if self.kind == OVER_AHEAD else 'land it: open its PR'
        return (
            f'{self.branch} at {self.tip[:12]}: {self.ahead} ahead, {self.behind} behind {integration}, '
            f'idle {self.idle_h:.0f} h -- {bound}\n'
            f'- {first.format(i=integration)}: python -m dev_lab.dev.forge pr create --head <pr/ head> '
            f'--base {integration if self.kind == STALE else self.branch}\n'
            f'- retire it (the user decides; its {self.ahead} commit(s) exist nowhere else): LAND it with a declared '
            f'`git merge -s ours` PR into a pr/ head, then {DOOR} {self.branch}\n'
        )


def _holders(root: Path, policy: Policy) -> tuple[str, ...]:
    refs = (f'{ORIGIN}{policy.integration}', f'{ORIGIN}{policy.trunk}')
    return tuple(ref for ref in refs if git_out(root, 'rev-parse', '--verify', '--quiet', ref))


def derive(root: Path, branchset: BranchSet, policy: Policy, *, now: datetime) -> tuple[PolicyRow, ...]:
    """Every row of *root*'s origin branches breaking *branchset*'s bounds, sorted; from local refs.

    Raises:
        OSError: git could not list origin's refs -- an unread origin is not a clean one.

    """
    listed = git_out(root, 'for-each-ref', '--format=%(refname)%09%(objectname)%09%(committerdate:unix)', ORIGIN)
    if listed is None:
        msg = f'git could not list the origin refs of {root}; no branch policy was judged'
        raise OSError(msg)
    keep = branchset.declared | {policy.integration, policy.trunk, 'HEAD'}
    holders = _holders(root, policy)
    rows: list[PolicyRow] = []
    for line in listed.splitlines():
        ref, sha, stamp = line.split('\t')
        name = ref.removeprefix(ORIGIN)
        if name in keep or any(git_out(root, 'merge-base', '--is-ancestor', sha, h) is not None for h in holders):
            continue
        counted = git_out(root, 'rev-list', '--left-right', '--count', f'{sha}...{ORIGIN}{policy.integration}')
        ahead, behind = (int(n) for n in counted.split()) if counted else (0, 0)
        idle_h = (now - datetime.fromtimestamp(int(stamp), tz=UTC)).total_seconds() / _HOUR_S
        if branchset.max_ahead is not None and behind > branchset.max_ahead:
            rows.append(PolicyRow(OVER_AHEAD, name, sha, ahead, behind, idle_h))
        if idle_h >= branchset.max_idle_hours:
            rows.append(PolicyRow(STALE, name, sha, ahead, behind, idle_h))
    return tuple(sorted(rows, key=lambda row: (row.branch, row.kind)))


def wanted(rows: tuple[PolicyRow, ...], branchset: BranchSet, integration: str) -> dict[str, str]:
    """Title -> body of the one issue each row keeps open."""
    bounds = {
        OVER_AHEAD: f'max_ahead = {branchset.max_ahead}',
        STALE: f'max_idle_hours = {branchset.max_idle_hours:g}',
    }
    return {row.title: row.body(integration, bounds[row.kind]) for row in rows}


def observe(root: Path, client: Client, *, now: datetime) -> tuple[Routed, ...]:
    """Derive *root*'s rows and reconcile their issues: open new, update changed, close cleared."""
    branchset, policy = declared_branchset(root), load_policy(root)
    rows = derive(root, branchset, policy, now=now)
    return reconcile(client, PREFIX, wanted(rows, branchset, policy.integration))


def prune_duty(
    root: Path,
    client: Client,
    *,
    now: datetime,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> None:
    """THE ``prune`` role's pass, whoever executes it: close landed PRs, sweep, prune, prune records, observe.

    The refs must be fetched already. Each step only alarms on failure; the policy observation last, so it reads
    what the prune left.
    """
    serve_close_landed(root, client, say=say, alarm=alarm)
    serve_sweep(root, client, say=say, alarm=alarm)
    serve_prune(root, client, now=now, say=say, alarm=alarm)
    serve_records_prune(root, client, now=now, say=say, alarm=alarm)
    try:
        for routed in observe(root, client, now=now):
            if routed.action != 'unchanged':
                say(f'[branch policy] {routed.action} #{routed.number}: {routed.area}')
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        alarm(Alarm(INTEGRATION, client.forge.repo, 'the branch policy was not observed', str(failed)))


def run_here(
    checkouts: Iterable[Path],
    *,
    clients: Callable[[Forge], Client],
    machine: str,
    now: datetime,
    say: Callable[[str], None],
    fetch: Callable[[Path], None] = fetch_origin,
    roles: Callable[[Path], Roles] = roles_at,
) -> tuple[str, ...]:
    """The prune duty for every checkout whose family binds ``prune`` to *machine* (a ``{ host }`` executor).

    A checkout bound elsewhere (``ci``, ``hpc``, another host) is skipped -- one executor per repo, so two machines
    never delete or reconcile the same branch. Each is fetched first; a failure is said, never raised. Returns the
    repos the duty ran for.
    """
    done = []
    for root in checkouts:
        try:
            if not performs(roles(root), PRUNE, machine):
                continue
            forge = forge_from_remote(root)
            fetch(root)
        except (Unbound, OSError, ValueError, subprocess.CalledProcessError) as why:
            say(f'[prune duty] {root}: not run: {why}')
            continue
        prune_duty(
            root, clients(forge), now=now, say=say, alarm=lambda one: say(f'[prune duty] {one.subject}: {one.body}')
        )
        done.append(forge.identity)
    return tuple(done)
