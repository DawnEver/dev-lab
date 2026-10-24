"""AUTO-SYNC: the forge merges integration INTO a behind ``pr/*`` head, so no PR waits for a hand ``forge sync``.

User ruling 2026-10-21: integration is an automatic mechanism; a steward cannot hand-merge every PR whose base
moved. Declared per repo (``[tool.lab_commons.integrator] auto_sync = true``; undeclared, nothing is synced),
the integration step of ``forge serve`` (:func:`dev_lab.dev.forgeintegration.tick`, given its host) asks
:func:`plan` of each open PR into integration that the forge did not merge this tick, and :func:`sync` carries
out a ``sync`` plan:

* a head that does not contain ``origin/<integration>`` is merged with it in a worktree under the repository's git
  directory -- a MERGE COMMIT on the head (first parent the head, ``Merged-Branch: <integration>``), never a
  rebase or a force -- and pushed under the head's own name, so origin's compare-and-swap refuses it if the author
  pushed meanwhile. The new head gets its parts by the normal path;
* its lock is relocked when the merge leaves it stale or conflicted, through the dependency door
  (:func:`dev_lab.dev.relock.door_upgrade`, the one writer of a lock) and the same staleness reading as
  the relock (:func:`dev_lab.dev.lockcheck.stale`) -- inside the merge commit, so no hand relock follows;
* the merge passes the merge audit (:func:`dev_lab.dev.mergeaudit.judge`) before it is committed, and the
  commit runs the repository's hooks (``MERGE-DEVIATIONS-NAMED``).

It REFUSES, naming why once in the head's :data:`CONTEXT` status and the PR's integration comment
(each sentence below is a module constant, said nowhere else):

* :data:`CONFLICTED` -- a textual conflict outside the lock is never resolved by the machine;
* :data:`STACKED` -- the head holds another open PR's unmerged head: it waits behind that PR, and is synced
  once that one merges (its commits then are integration's);
* :data:`QUIET` -- a head committed inside the declared ``auto_sync_quiet`` (default ``"10 min"``): a live
  author is not raced;
* :data:`NOT_EPHEMERAL` -- a head outside ``[tool.lab_commons.branchset] ephemeral`` is the author's branch;
* :data:`AUDIT`, :data:`RELOCK`, :data:`LOCAL_BRANCH`, :data:`PUSH` -- the merge, relock or push could not finish.

ONCE PER INTEGRATION TIP. Every outcome is a status on the head naming the tip it was judged against, and a head
carrying one for the current tip is left alone (:func:`attempted`); a claim (``pending``) keeps N serving hosts
to one, and a claim older than :data:`CLAIM_STALE` is presumed dead. A new tip earns one new attempt.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgenotice import duration
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.labsession import machine_env
from dev_lab.dev.lockcheck import LOCK, mount_submodules, stale
from dev_lab.dev.mergeaudit import MergeAuditError, judge
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.relock import door_upgrade
from dev_lab.dev.sessionbranch import MERGED_BRANCH
from dev_lab.dev.trialmerge import contains, shares_unmerged, trial

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.lanepolicy import Policy
    from dev_lab.dev.netverb import Report

__all__ = [
    'AUDIT', 'CLAIM_STALE', 'CONFLICTED', 'CONTEXT', 'LOCAL_BRANCH', 'NOT_EPHEMERAL', 'PUSH', 'QUIET', 'RELOCK',
    'STACKED', 'Open', 'Plan', 'SyncRefused', 'attempted', 'claim', 'merge_message', 'outcome', 'plan', 'quiet_after',
    'step', 'sync',
]  # fmt: skip

#: The commit-status context an auto-sync outcome (or claim) is posted in, on the head it judged.
CONTEXT: Final = 'integration/sync'

#: The refusals, each said once, here.
CONFLICTED: Final = 'conflicts with {integration} in {paths}: the machine resolves no conflict -- merge it by hand'
STACKED: Final = 'waits behind #{number} ({branch}), whose commits it holds: synced once that one merges'
QUIET: Final = 'its head was committed inside auto_sync_quiet {quiet}: a live author is not raced'
NOT_EPHEMERAL: Final = '{branch} is not an ephemeral head ([tool.lab_commons.branchset] ephemeral): never synced'
AUDIT: Final = 'the merge audit refuses the machine merge: {problems}'
RELOCK: Final = 'the lock could not be relocked: {why}'
LOCAL_BRANCH: Final = 'a local branch {branch} exists on this host: its owner pushes it'
PUSH: Final = 'the push of {branch} failed: {why}'

#: How old a claim grows before another host may take the head over: above the door's own resolution time.
CLAIM_STALE: Final = timedelta(hours=1)
#: The default ``auto_sync_quiet``.
DEFAULT_QUIET: Final = '10 min'

_CLAIMED: Final = 'claimed by'
_CLAIM: Final = re.compile(rf'^{_CLAIMED} \S+ at (?P<at>\S+) for (?P<tip>[0-9a-f]+)')
_TIP: Final = re.compile(r'\bat ([0-9a-f]{12})\b')
_SHORT: Final = 12


class SyncRefused(OSError):
    """A sync that could not be carried; its message is one of the module's refusals."""


@dataclass(frozen=True)
class Open:
    """Another open PR into integration: its number, head branch and head commit."""

    number: int
    branch: str
    head: str


@dataclass(frozen=True)
class Plan:
    """What auto-sync does with one head: ``skip`` (nothing to do or already tried), ``sync``, or ``refuse``."""

    action: str
    reason: str = ''


def quiet_after(policy: Policy) -> timedelta:
    """*policy*'s ``auto_sync_quiet`` as a :class:`timedelta`; a bare number or a non-duration is refused naming it."""
    return duration('auto_sync_quiet', policy.auto_sync_quiet)


def merge_message(policy: Policy, branch: str, tip: str) -> str:
    """The machine merge's message: a conventional subject, then ``Merged-Branch: <integration>``."""
    return (
        f'chore(merge): {policy.integration} at {tip[:_SHORT]} into {branch}\n\n'
        f'Synced by the forge (dev_lab.dev.forgeautosync).\n\n{MERGED_BRANCH}: {policy.integration}\n'
    )


def outcome(state: str, tip: str, text: str) -> tuple[str, str]:
    """The ``(state, description)`` an outcome is posted as: it names the tip it was judged against."""
    return state, f'at {tip[:_SHORT]}: {text}'


def attempted(status: CommitStatus | None, tip: str, now: datetime) -> bool:
    """Whether the head carrying *status* was already synced, refused or claimed for integration tip *tip*."""
    if status is None:
        return False
    if (claim := _CLAIM.match(status.description)) is not None:
        try:
            fresh = now - datetime.fromisoformat(claim['at']) < CLAIM_STALE
        except ValueError:
            fresh = False  # an unreadable claim cannot hold a head forever
        return fresh and tip.startswith(claim['tip'])
    found = _TIP.match(status.description)
    return found is not None and tip.startswith(found.group(1))


def claim(host: str, tip: str, now: datetime) -> str:
    """The ``pending`` description a host posts before it syncs: every other host skips the head."""
    return f'{_CLAIMED} {host} at {now.isoformat(timespec="seconds")} for {tip[:_SHORT]}, syncing'


def _git(root: Path, *argv: str) -> tuple[int, str]:
    done = _door.run(
        [_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, timeout=_GIT_TIMEOUT_S, env=machine_env(),  # a machine merge is the forge's, no session's
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).strip()


def _must(root: Path, *argv: str) -> str:
    code, out = _git(root, *argv)
    if code != 0:
        msg = f'git {" ".join(argv[:2])} failed in {root}: {out}'
        raise SyncRefused(msg)
    return out


def plan(
    root: Path,
    policy: Policy,
    *,
    branch: str,
    head: str,
    ephemeral: bool,
    others: Sequence[Open],
    status: CommitStatus | None,
    now: datetime,
) -> Plan:
    """What auto-sync does with PR head *branch* at *head*, read from the object store alone; writes nothing."""
    base = f'refs/remotes/origin/{policy.integration}'
    tip = _must(root, 'rev-parse', '--verify', f'{base}^{{commit}}')
    if contains(root, head, tip):
        return Plan('skip')
    if attempted(status, tip, now):
        return Plan('skip', status.description if status is not None else '')
    age = now - datetime.fromtimestamp(int(_must(root, 'show', '-s', '--format=%ct', head)), UTC)
    if ephemeral and age < quiet_after(policy):
        return Plan('skip', QUIET.format(quiet=policy.auto_sync_quiet))
    refused = _refusal(root, policy, branch=branch, head=head, tip=tip, ephemeral=ephemeral, others=others)
    return Plan('sync') if refused is None else Plan('refuse', refused)


def _refusal(
    root: Path, policy: Policy, *, branch: str, head: str, tip: str, ephemeral: bool, others: Sequence[Open]
) -> str | None:
    """Why the head may not be synced for tip *tip* at all: not ephemeral, stacked, or conflicting."""
    if not ephemeral:
        return NOT_EPHEMERAL.format(branch=branch)
    for other in others:
        if other.head != head and shares_unmerged(root, head, other.head, tip):
            return STACKED.format(number=other.number, branch=other.branch)
    conflicts = [path for path in trial(root, tip, head).conflicts if path != LOCK]
    if conflicts:
        paths = ', '.join(f'`{path}`' for path in conflicts)
        return CONFLICTED.format(integration=policy.integration, paths=paths)
    return None


@contextlib.contextmanager
def _worktree(root: Path, branch: str, head: str) -> Iterator[Path]:
    """A worktree of *root* on a local branch *branch* at *head*, with its submodules; branch and tree removed after.

    A LOCAL branch, so the push publishes ``refs/heads/<branch>`` from ``refs/heads/<branch>``
    (PUBLISH-IS-THE-LOCAL-REF); one that already exists here is an author's, and is refused, never reset.
    """
    if _git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}')[0] == 0:
        raise SyncRefused(LOCAL_BRANCH.format(branch=branch))
    common = Path(_must(root, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    tree = common / 'autosync' / head[:_SHORT]
    _git(root, 'worktree', 'remove', '--force', str(tree))
    _must(root, 'worktree', 'add', '-q', '-b', branch, str(tree), head)
    try:
        mount_submodules(root, tree)
        yield tree
    finally:
        _git(root, 'worktree', 'remove', '--force', str(tree))
        _git(root, 'branch', '-D', branch)


def _push(tree: Path, branch: str) -> None:
    report = run_network_verb([_GIT, 'push', 'origin', f'refs/heads/{branch}'], cwd=tree, timeout=300)
    if not report.ok:
        raise SyncRefused(PUSH.format(branch=branch, why=report.remedy))


def _relock(
    tree: Path, *, conflicted: bool, resolve: Callable[[Path], Report] | None, upgrade: Callable[[Path], int]
) -> None:
    if conflicted:
        _must(tree, 'checkout', '--theirs', '--', LOCK)  # integration's lock, then the door resolves the merge
    found = stale(tree) if resolve is None else stale(tree, resolve=resolve)
    if not conflicted and not found:
        return
    if unrun := [line for line in found if not line.startswith(f'{LOCK} is not the newest resolution')]:
        raise SyncRefused(RELOCK.format(why='; '.join(unrun)))
    if (exited := upgrade(tree)) != 0:
        raise SyncRefused(RELOCK.format(why=f'the dependency door exited {exited}'))
    _must(tree, 'add', '--', LOCK)


def sync(
    root: Path,
    policy: Policy,
    *,
    branch: str,
    head: str,
    resolve: Callable[[Path], Report] | None = None,
    upgrade: Callable[[Path], int] = door_upgrade,
    push: Callable[[Path, str], None] = _push,
) -> str:
    """Merge ``origin/<integration>`` into *branch* at *head*, relock, audit, commit and push; the new head.

    *resolve*, *upgrade* and *push* are the staleness resolution, the door and the push -- each a seam a test plants.
    """
    base = f'refs/remotes/origin/{policy.integration}'
    tip = _must(root, 'rev-parse', '--verify', f'{base}^{{commit}}')
    message = merge_message(policy, branch, tip)
    with _worktree(root, branch, head) as tree:
        _git(tree, 'merge', '--no-ff', '--no-commit', tip)
        unmerged = _must(tree, 'diff', '--name-only', '--diff-filter=U').split()
        if [path for path in unmerged if path != LOCK]:
            _git(tree, 'merge', '--abort')
            paths = ', '.join(f'`{path}`' for path in unmerged)
            raise SyncRefused(CONFLICTED.format(integration=policy.integration, paths=paths))
        _relock(tree, conflicted=LOCK in unmerged, resolve=resolve, upgrade=upgrade)
        merged = _must(tree, 'write-tree')
        try:
            problems = judge(root, [head, tip], merged, message, roots=policy.test_roots, label=branch)
        except MergeAuditError as error:
            problems = (str(error),)
        if problems:
            _git(tree, 'merge', '--abort')
            raise SyncRefused(AUDIT.format(problems='; '.join(problems)))
        title, _, body = message.partition('\n\n')
        _must(tree, 'commit', '-q', '-m', title, '-m', body.strip())
        new = _must(tree, 'rev-parse', 'HEAD')
        push(tree, branch)
    return new


def _ephemeral(root: Path, branch: str) -> bool:
    try:
        return declared_branchset(root).is_ephemeral(branch)
    except BranchSetNotDeclared:
        return False


def step(
    root: Path,
    client: Client,
    policy: Policy,
    *,
    branch: str,
    number: int,
    head: str,
    others: Sequence[Open],
    host: str,
    now: datetime,
    run: Callable[..., str] = sync,
) -> str | None:
    """Auto-sync PR *number* (*branch* at *head*) once for the current integration tip; the line its comment says.

    ``None`` when there is nothing to say (the head already holds integration). Every outcome is posted on the
    head in :data:`CONTEXT`, naming the tip, so a second tick on the same tip runs nothing.
    """
    latest = next((one for one in status_list(client, head) if one.context == CONTEXT), None)
    found = plan(
        root, policy, branch=branch, head=head, ephemeral=_ephemeral(root, branch), others=others,
        status=latest, now=now,
    )  # fmt: skip
    if found.action == 'skip':
        return f'auto-sync: {found.reason}' if found.reason else None
    tip = _must(root, 'rev-parse', '--verify', f'refs/remotes/origin/{policy.integration}^{{commit}}')
    if found.action == 'refuse':
        state, description = outcome('failure', tip, found.reason)
        status_post(client, head, context=CONTEXT, state=state, description=description)
        return f'auto-sync: {description}'
    status_post(client, head, context=CONTEXT, state='pending', description=claim(host, tip, now))
    try:
        new = run(root, policy, branch=branch, head=head)
    except SyncRefused as refused:
        state, description = outcome('failure', tip, str(refused))
        status_post(client, head, context=CONTEXT, state=state, description=description)
        return f'auto-sync: {description}'
    state, description = outcome('success', tip, f'synced as {new[:_SHORT]}')
    status_post(client, head, context=CONTEXT, state=state, description=description)
    return (
        f'auto-sync: merged `{policy.integration}` at {tip[:_SHORT]} into #{number} as {new[:_SHORT]}; its parts follow'
    )
