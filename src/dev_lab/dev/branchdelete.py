"""LOSSLESS-DELETE and LANDED-BRANCHES-SWEPT: a branch is deleted only when its content is held elsewhere.

The command line is :mod:`dev_lab.dev.branchprune` (``delete``, ``sweep``); the idle-age prune is there too.

AN AGENT'S DELETION IS LOSSLESS-DELETE (user ruling 2026-10-21): never a raw push (``PUSH-REMOTE-DELETE``), only
:data:`DOOR`, which after a fresh fetch deletes a branch only when every commit on it is on integration or on
another live origin branch or open PR head (:func:`dev_lab.dev.deletejudge.judge` names that container) or, by
CONTENT, when no file its own commits wrote differs on integration, generated files aside -- a branch of forge sync
merges holds no work -- and otherwise refuses naming the commits and the files carrying unlanded content. The SAME
judgment runs at pre-push on every delete a push carries, however it was spelled (:mod:`dev_lab.dev.pushdelete`),
and this door's own push passes it there. A refused branch is told the two doors MERGE-OR-DELETE leaves (user
ruling D22, 2026-11-17: "no tags -- either merge or delete"): MERGE what is still wanted, or LAND the branch with a
declared content-neutral merge (``git merge -s ours``) and re-run the delete, now lossless. No tag holds a branch.
The delete is a lease on the judged sha through the network door, recorded as one
:data:`DELETED_EVENT` line and a ``pruned`` alarm naming the ``Lab-Session`` and the container.

LANDED-BRANCHES-SWEPT (user ruling 2026-10-29: "after a merge, clean up every branch it now includes -- as a
mechanism, in every repo"): :func:`sweep` judges EVERY undeclared origin branch, with no grace, by one question
-- does integration (or the trunk) now contain it? By ancestry, else by CONTENT (:func:`landed`, built on the
judge LOSSLESS-DELETE uses: a squash-landed or forge-synced branch carries other shas). A landed open PR is
closed (:func:`dev_lab.dev.prlanded.close_pr`), then its branch is lease-deleted; anything else is kept and said
with its reason. ``--local`` then reclaims the clean landed worktrees and deletes the landed local branches
(:func:`dev_lab.dev.branchset.apply_local`, then the content judge for those checked out nowhere). It runs
wherever integration moves: the forge's repo-wide serve pass (:func:`serve_sweep`) and the GitHub job a push to
integration runs (``ci_base.toml``); on a workstation, :mod:`dev_lab.dev.reclaimrun` reclaims the local half.

THE USER'S ORDER TO DROP A BRANCH is :func:`discard` (``branchprune discard <branch> --approved "<the user's
words>"``, 2026-11-24): a branch whose history must not be published -- a private second root a ``-s ours`` landing
would put into the mainline -- is deleted WITHOUT landing, only with the user's words, never integration, the trunk
or an open PR head. Its push passes the pre-push row by a grant naming that branch at that sha
(:func:`dev_lab.dev.deletejudge.grant`); it is recorded as one :data:`DISCARDED_EVENT` line and a ``pruned`` alarm
naming the sha and the words. No bundle or backup is kept (R2). A lossy refusal whose own commits carry a root of
their own names this door (:func:`second_root`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.backgroundrun import held
from dev_lab.dev.branchlocal import main
from dev_lab.dev.branchset import BranchSetNotDeclared, apply_local, checked_out, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.deletejudge import ORIGIN, Verdict, grant, judge, unlanded
from dev_lab.dev.forge import _GIT
from dev_lab.dev.forgealarm import PRUNED, Alarm, sound
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.prlanded import close_pr

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DELETED_EVENT',
    'DISCARDED_EVENT',
    'DISCARD_DOOR',
    'DOOR',
    'MERGE_OR_LAND',
    'TASK_HEAD_DOORS',
    'UNAPPROVED',
    'TaskBranches',
    'delete',
    'delete_task',
    'discard',
    'landed',
    'second_root',
    'serve_sweep',
    'sweep',
]

#: The ``event`` of the one structured line each LOSSLESS-DELETE writes.
DELETED_EVENT: Final = 'lab_commons.forge.branch-delete'
#: The door an agent deletes a remote branch through (PUSH-REMOTE-DELETE's remedy names it).
DOOR: Final = 'python -m dev_lab.dev.branchprune delete <branch>...'
#: The ``event`` of the one structured line each approved discard writes (ref, sha, the user's words).
DISCARDED_EVENT: Final = 'lab_commons.forge.branch-discard'
#: The door for the user's order to drop a branch unlanded.
DISCARD_DOOR: Final = 'python -m dev_lab.dev.branchprune discard {branch} --approved "<the user\'s words>"'
#: The refusal of a discard without the user's words.
UNAPPROVED: Final = (
    '[branchprune] discard: --approved "<the user words>" is required: it drops commits held nowhere else, '
    'so only the user orders it'
)
#: What a LOSSY refusal adds: the two doors MERGE-OR-DELETE leaves (D22), never a tag.
MERGE_OR_LAND: Final = (
    'MERGE-OR-DELETE (D22, no tags): MERGE what is still wanted through a PR; or, when that content is already on '
    'integration in another form or retired by a ruling, LAND the branch: merge origin/{branch} into a pr/ branch '
    'with `git merge -s ours`, declare each conflicted file `<path>: <class> -- <why>` and each dropped test '
    '`Merge-Audit: ...`, land the PR, then re-run `branchprune delete {branch}`'
)


def second_root(verdict: Verdict) -> str:
    """The discard door, when *verdict*'s own commits carry a root of their own; else ``''``."""
    if not verdict.roots:
        return ''
    shown = ', '.join(one[:12] for one in verdict.roots)
    return (
        f'; it carries a root of its own ({shown}): a `-s ours` landing would publish that history into the '
        f"mainline, so on the user's order to drop it: {DISCARD_DOOR.format(branch=verdict.branch)}"
    )


def _push_delete(root: Path, branch: str, sha: str) -> str:
    """Delete origin's *branch* if still at *sha* (a lease), through the network door; ``''``, or why not.

    The push runs the pre-push ``lossless-delete`` row, which judges the delete again (:mod:`dev_lab.dev.pushdelete`).
    """
    report = run_network_verb(
        [_GIT, 'push', f'--force-with-lease=refs/heads/{branch}:{sha}', 'origin', '--delete', f'refs/heads/{branch}'],
        cwd=root,
        timeout=300,
    )
    return '' if report.ok else report.remedy


def delete(
    root: Path,
    branches: Sequence[str],
    *,
    client: Client,
    session: str,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
    push: Callable[[Path, str, str], str] = _push_delete,
    alarm: Callable[[Alarm], object] = sound,
) -> int:
    """LOSSLESS-DELETE each of *branches* after a fresh fetch; 0 when every one was deleted, else 1.

    A branch refused for commits on it alone is told its two doors (:data:`MERGE_OR_LAND`); nothing deletes it.
    """
    fetch(root)
    policy = load_policy(root)
    heads = {pr.head: pr.number for pr in pr_list(client)}
    failed = 0
    for branch in branches:
        tip = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{ORIGIN}{branch}^{{commit}}') or '').strip()
        found = judge(root, policy, branch, tip, open_heads=heads)
        why = found.refused or push(root, branch, found.sha)
        if why:
            doors = f'. {MERGE_OR_LAND.format(branch=branch)}{second_root(found)}' if found.lost else ''
            say(why + doors if found.refused else f'{branch}: the delete failed: {why}')
            failed += 1
            continue
        record = {'event': DELETED_EVENT, 'ref': branch, 'sha': found.sha, 'container': found.container}
        say(json.dumps(record | {'session': session or None}))
        body = f'{branch} at {found.sha[:12]}, held by {found.container}; by session {session or "none"}'
        alarm(Alarm(PRUNED, client.forge.repo, f'{branch} deleted (lossless)', body))
        say(f'{branch}: deleted at {found.sha[:12]} -- held by {found.container}')
    return 1 if failed else 0


def discard(
    root: Path,
    branches: Sequence[str],
    *,
    approved: str,
    client: Client,
    session: str,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
    push: Callable[[Path, str, str], str] = _push_delete,
    alarm: Callable[[Alarm], object] = sound,
) -> int:
    """Delete each of *branches* from origin WITHOUT landing it, on the user's *approved* words.

    0 when every one went, 1 when one was kept, 2 with no words. Integration, the trunk and an open PR head are
    never discarded (the judgment's own refusal). The push is a lease on the fetched tip, passing the pre-push row
    by a one-shot grant for that branch at that sha.
    """
    words = ' '.join(approved.split())
    if not words:
        say(UNAPPROVED)
        return 2
    fetch(root)
    policy = load_policy(root)
    heads = {pr.head: pr.number for pr in pr_list(client)}
    failed = 0
    for branch in branches:
        tip = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{ORIGIN}{branch}^{{commit}}') or '').strip()
        found = judge(root, policy, branch, tip, open_heads=heads)
        if found.refused and not found.lost:
            say(found.refused)
            failed += 1
            continue
        with grant(root, branch, found.sha):
            why = push(root, branch, found.sha)
        if why:
            say(f'{branch}: the discard failed: {why}')
            failed += 1
            continue
        record = {'event': DISCARDED_EVENT, 'ref': branch, 'sha': found.sha, 'approved': words}
        say(json.dumps(record | {'session': session or None}))
        body = f'{branch} at {found.sha}, discarded unlanded; approved: "{words}"; by session {session or "none"}'
        alarm(Alarm(PRUNED, client.forge.repo, f'{branch} discarded (approved)', body))
        say(f'{branch}: discarded at {found.sha[:12]} -- approved: "{words}"')
    return 1 if failed else 0


#: Why the sweep keeps a branch: content integration lacks.
NOT_LANDED: Final = '{branch}: kept -- {count} commit(s) not on {integration}, with unlanded content in: {files}'


def landed(root: Path, policy: Policy, ref: str) -> Verdict:
    """Whether *ref* (a full ref name) is contained in origin's integration or trunk: by ancestry, else by content.

    The content judge is :func:`~dev_lab.dev.deletejudge.unlanded` against integration -- every file *ref*'s own
    commits wrote must be identical there -- so a squash-landed or forge-synced branch is landed under other
    shas, and one unlanded line keeps it. No other branch is a holder: that is LOSSLESS-DELETE's wider
    question (:func:`~dev_lab.dev.deletejudge.judge`); the sweep asks only whether integration now includes the branch.

    NO FILE IS EXEMPT HERE, generated ones included: "landed" closes an open PR, and a commit that only relocks
    ``uv.lock`` is work integration lacks (acme-consumer PR #439 was closed and its branch deleted so, 2026-11-02).
    """
    branch = ref.removeprefix(ORIGIN).removeprefix('refs/heads/')
    sha = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}') or '').strip()
    names = (policy.integration, policy.trunk)
    holders = [name for name in names if git_out(root, 'rev-parse', '--verify', '--quiet', f'{ORIGIN}{name}')]
    if not sha or policy.integration not in holders:
        return Verdict(branch, sha, refused=f'{branch}: kept -- it or origin/{policy.integration} is unreadable')
    for name in holders:
        if git_out(root, 'merge-base', '--is-ancestor', sha, f'{ORIGIN}{name}') is not None:
            return Verdict(branch, sha, container=name)
    files = unlanded(root, sha, holders, policy.integration, exempt=frozenset())
    if not files:
        return Verdict(branch, sha, container=f'{policy.integration} (by content: no content it lacks)')
    lost = (git_out(root, 'rev-list', sha, '--not', *(f'{ORIGIN}{name}' for name in holders)) or '').split()
    refused = NOT_LANDED.format(branch=branch, count=len(lost), integration=policy.integration, files=', '.join(files))
    return Verdict(branch, sha, lost=tuple(lost), refused=refused)


def delete_task(
    root: Path,
    slug: str,
    *,
    client: Client,
    session: str,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
    push: Callable[[Path, str, str], str] = _push_delete,
    alarm: Callable[[Alarm], object] = sound,
) -> int:
    """LOSSLESS-DELETE every ``pr/<slug>/*`` head on origin: a closed task prunes its branches (user ruling D25).

    Each head goes through :func:`delete`, so one with an open PR or unlanded content is kept and said by name;
    0 when every head went (or none existed), else 1. Never approved: a closed task's refusals are the user's.
    """
    if not slug or any(c in slug for c in '/*?[\\ '):
        msg = f'{slug!r} is not a task slug (one path segment, no glob characters)'
        raise ValueError(msg)
    fetch(root)
    heads = [name for name in _origin_branches(root) if name.startswith(f'pr/{slug}/')]
    if not heads:
        say(f'task {slug}: no pr/{slug}/* head on origin')
        return 0
    code = delete(root, heads, client=client, session=session, fetch=lambda _r: None, say=say, push=push, alarm=alarm)
    kept = [name for name in heads if git_out(root, 'rev-parse', '--verify', '--quiet', f'{ORIGIN}{name}')]
    say(
        f'task {slug}: {len(heads) - len(kept)} of {len(heads)} head(s) pruned'
        + (f'; kept: {", ".join(kept)}' if kept else '')
    )
    return code


#: The doors an unmerged ``pr/<slug>/*`` head that blocks ``task close`` is told (user ruling 2026-11-24).
TASK_HEAD_DOORS: Final = (
    'Door: MERGE each through a PR; or discard it -- a local one: python -m dev_lab.dev.branchset --discard <branch> '
    '--approved "<the user\'s words>"; an origin one: LAND it with a declared `git merge -s ours` PR, then {door}'
)


def _task_refs(root: Path, slug: str) -> list[str]:
    """Every ``pr/<slug>/*`` head of *root*: local (``refs/heads/``) and origin's (``refs/remotes/origin/``)."""
    if not slug or any(c in slug for c in '/*?[\\ '):
        msg = f'{slug!r} is not a task slug (one path segment, no glob characters)'
        raise ValueError(msg)
    listed = git_out(root, 'for-each-ref', '--format=%(refname)', f'refs/heads/pr/{slug}/', f'{ORIGIN}pr/{slug}/')
    if listed is None:
        msg = f'git could not list the branches of {root}; the task branches were not judged'
        raise OSError(msg)
    return sorted(listed.split())


@dataclass(frozen=True)
class TaskBranches:
    """A task's ``pr/<slug>/*`` heads in one checkout, local and on origin: judged before a close, pruned after it.

    ``task close`` (user ruling 2026-11-24) refuses while :meth:`unmerged` names any head, and once closed runs
    :meth:`prune`: origin's heads through :func:`delete_task` (LOSSLESS-DELETE), the local ones by a pinned
    ``update-ref -d`` when :func:`landed` and checked out nowhere.
    """

    root: Path
    client: Client
    session: str
    fetch: Callable[[Path], None]
    push: Callable[[Path, str, str], str] = _push_delete
    alarm: Callable[[Alarm], object] = field(default=sound)

    def unmerged(self, slug: str) -> list[str]:
        """After a fresh fetch, one line per ``pr/<slug>/*`` head integration does not contain; ``[]`` when none."""
        self.fetch(self.root)
        refs = _task_refs(self.root, slug)
        if not refs:
            return []
        policy = load_policy(self.root)
        return [found.refused for ref in refs if (found := landed(self.root, policy, ref)).refused]

    def prune(self, slug: str) -> list[str]:
        """Delete every merged ``pr/<slug>/*`` head, origin's then the local ones; the lines said."""
        said: list[str] = []
        delete_task(self.root, slug, client=self.client, session=self.session, fetch=self.fetch, say=said.append,
                    push=self.push, alarm=self.alarm)  # fmt: skip
        policy, busy = load_policy(self.root), checked_out(self.root)
        for ref in _task_refs(self.root, slug):
            if not ref.startswith('refs/heads/'):
                continue
            name = ref.removeprefix('refs/heads/')
            found = landed(self.root, policy, ref)
            if found.refused or name in busy:
                said.append(f'kept     local   {found.refused or f"{name}: checked out in a worktree"}')
                continue
            done = git_out(self.root, 'update-ref', '-d', ref, found.sha) is not None
            said.append(
                f'{"deleted " if done else "FAILED  "} local   {name}  ({found.sha[:10]}, held by {found.container})'
            )
        return said


def _origin_branches(root: Path) -> list[str]:
    listed = git_out(root, 'for-each-ref', '--format=%(refname)', ORIGIN)
    if listed is None:
        msg = f'git could not list the origin refs of {root}; nothing was swept'
        raise OSError(msg)
    return sorted(ref.removeprefix(ORIGIN) for ref in listed.split())


def sweep(
    root: Path,
    *,
    client: Client,
    session: str,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
    local: bool = False,
    push: Callable[[Path, str, str], str] = _push_delete,
    alarm: Callable[[Alarm], object] = sound,
) -> int:
    """Delete every undeclared branch integration now contains; 0 unless a landed branch failed to delete.

    Origin first: a landed open PR is closed, then its branch is lease-deleted at the judged sha. With *local*,
    the local branches and clean landed worktrees follow. A kept branch is said with its reason, never a failure.
    """
    fetch(root)
    policy = load_policy(root)
    keep = declared_branchset(root).declared | {policy.integration, policy.trunk, 'HEAD'}
    opened = {pr.head: pr for pr in pr_list(client)}
    tip = (git_out(root, 'rev-parse', f'{ORIGIN}{policy.integration}') or '').strip()
    deleted: list[Verdict] = []
    failed = 0
    for name in _origin_branches(root):
        if name in keep:
            continue
        found = landed(root, policy, f'{ORIGIN}{name}')
        if found.refused:
            say(found.refused)
            continue
        if name in opened:
            close_pr(client, opened[name], head=found.sha, merged_by=tip, session=session, say=say)
        why = push(root, name, found.sha)
        if why:
            say(f'{name}: the delete failed: {why}')
            failed += 1
            continue
        record = {'event': DELETED_EVENT, 'ref': name, 'sha': found.sha, 'container': found.container}
        say(json.dumps(record | {'session': session or None}))
        deleted.append(found)
    if deleted:
        body = '\n'.join(f'{one.branch} {one.sha[:12]} held by {one.container}' for one in deleted)
        alarm(Alarm(PRUNED, client.forge.repo, f'{len(deleted)} landed branch(es) deleted from origin', body))
    if local:
        _sweep_local(root, policy, keep, say)
    return 1 if failed else 0


def _sweep_local(root: Path, policy: Policy, keep: frozenset[str], say: Callable[[str], None]) -> None:
    """Reclaim clean landed worktrees, then delete the landed local branches; under the per-repo reclaim lock."""
    with held(root) as mine:
        if not mine:
            say('[sweep] local: another run holds the reclaim lock; nothing done locally')
            return
        for line in apply_local(root, declared_branchset(root)) or ('[sweep] local: git could not read branches',):
            say(line)
        busy = checked_out(root)
        for name in (git_out(root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/') or '').split():
            if name in keep or name in busy:
                continue
            found = landed(root, policy, f'refs/heads/{name}')
            if found.refused:
                say(f'kept     local   {found.refused}')
                continue
            done = git_out(root, 'update-ref', '-d', f'refs/heads/{name}', found.sha) is not None
            say(f'{"deleted " if done else "FAILED  "} local   {name}  ({found.sha[:10]}, held by {found.container})')


def serve_sweep(root: Path, client: Client, *, say: Callable[[str], None], alarm: Callable[[Alarm], object]) -> int:
    """The serve pass's step: :func:`sweep` of origin over the refs the tick fetched; a failure only alarms."""
    try:
        return sweep(root, client=client, session='forge-serve', fetch=lambda _r: None, say=say, alarm=alarm)
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        alarm(Alarm(PRUNED, client.forge.repo, 'the landed-branch sweep failed', str(failed)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
