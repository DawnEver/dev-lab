"""BRANCH-POLICY-OBSERVED: an unlanded origin branch holding too much unlanded work, or idle too long, is an alarm.

User ruling D46 (integrator, 2026-11-19): the branch policy is a per-repo DECLARATION in
``[tool.dev_lab.branchset]`` (:mod:`dev_lab.dev.branchset`) and an OBSERVER derives what breaks it:

* :data:`OVER_AHEAD` -- the branch holds more than ``max_ahead`` commits integration lacks (unjudged when the key
  is absent). Its doors (user correction 2026-11-19): LAND IT NOW, and RECORD WHY it ran past the limit -- no test
  producer, nobody integrating, or the lane withheld finished work. Never "split it": the work is done, and the
  cause of the backlog is what is recorded.
* :data:`STALE` -- its tip has sat idle for ``max_idle_hours`` (the same bound the prune deletes a merged branch
  by). Its doors: LAND it through a PR, or RETIRE it.

RETIRING is the user's call, never the observer's: LAND the branch with a declared ``git merge -s ours`` PR into a
``pr/`` head, then ``branchprune delete`` it (LOSSLESS-DELETE). A branch merged into integration or the trunk is
never a row: the prune owns it (:mod:`dev_lab.dev.branchprune`).

ONE ALARM PER ROW, NEVER AN ISSUE (user ruling 2026-11-19: issues do not record events nor fan out). A row
is an ``integration`` alarm on the host card and the session feed, keyed by ``about = <kind> <branch>`` -- no
sha, so a branch that moves repeats as the same alarm -- and a row that cleared simply stops being raised: the
state is derived each pass, never stored. Read from the local refs: the caller fetches first.

WHO RUNS IT is the ``prune`` role's executor (:mod:`dev_lab.dev.roles`) -- :func:`prune_duty`, the one pass every
executor kind calls, so a policy is observed and a merged head deleted in exactly one place per repo.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.branchdelete import DOOR, serve_sweep
from dev_lab.dev.branchprune import serve_prune
from dev_lab.dev.branchset import BranchSet, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.deletejudge import ORIGIN
from dev_lab.dev.forge import Forge, fetch_origin, forge_from_remote
from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgeclaim import this_machine
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete
from dev_lab.dev.forgerecords import serve_prune as serve_records_prune
from dev_lab.dev.forgethreads import feed_dir, read_json, seconds
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.prlanded import serve_close_landed
from dev_lab.dev.roles import PRUNE, Roles, Unbound, performs, roles_at

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DEFAULT_PRUNE_DUTY_S',
    'OVER_AHEAD',
    'PREFIX',
    'STALE',
    'PolicyRow',
    'derive',
    'duty_once',
    'observe',
    'prune_duty',
    'prune_duty_s',
    'run_here',
    'wanted',
]

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
        head = (
            f'{self.branch} at {self.tip[:12]}: {self.ahead} ahead, {self.behind} behind {integration}, '
            f'idle {self.idle_h:.0f} h -- {bound}\n'
            f'- land it now: python -m dev_lab.dev.forge pr create --head {self.branch} --base {integration}\n'
        )
        if self.kind == OVER_AHEAD:
            return head + (
                f'- record why it ran past {bound}: no test producer, nobody integrating, or the lane withheld '
                'finished work -- a comment on this issue\n'
            )
        return head + (
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
        if branchset.max_ahead is not None and ahead > branchset.max_ahead:
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


def observe(root: Path, repo: str, *, now: datetime) -> tuple[Alarm, ...]:
    """Derive *root*'s rows as alarms: one per row, keyed by kind and branch, nothing stored."""
    branchset, policy = declared_branchset(root), load_policy(root)
    rows = derive(root, branchset, policy, now=now)
    bodies = wanted(rows, branchset, policy.integration)
    return tuple(
        Alarm(INTEGRATION, repo, row.title, bodies[row.title], about=f'{row.kind} {row.branch}') for row in rows
    )


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
        for raised in observe(root, client.forge.repo, now=now):
            alarm(raised)
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


#: The prune duty's interval when the machine file declares none (D46, 2026-11-19: branches change slowly).
DEFAULT_PRUNE_DUTY_S: Final = 1800


def prune_duty_s(table: object = None) -> int:
    """The forge feed's prune-duty interval: ``[forgefeed] prune_duty_s``, else :data:`DEFAULT_PRUNE_DUTY_S`.

    Raises:
        ValueError: the declared value is not a positive integer (named, with its key).

    """
    return seconds('forgefeed', 'prune_duty_s', DEFAULT_PRUNE_DUTY_S, table)


def duty_once(
    *, clients: Callable[[Forge], Client], now: float, every_s: float, checkouts: Iterable[Path]
) -> tuple[str, ...] | None:
    """:func:`run_here` when *every_s* has passed since its last run on this machine; ``None`` when not yet due."""
    stamp = feed_dir() / 'prune-duty.json'
    last = read_json(stamp).get('at')
    if isinstance(last, int | float) and now - last < every_s:
        return None
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({'at': now}), encoding='utf-8')
    return run_here(
        checkouts, clients=clients, machine=this_machine(), now=datetime.fromtimestamp(now, tz=UTC), say=emit
    )
