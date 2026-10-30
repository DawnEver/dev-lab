"""LOSSLESS-DELETE and LANDED-BRANCHES-SWEPT: a branch is deleted only when its content is held elsewhere.

The command line is :mod:`dev_lab.dev.branchprune` (``delete``, ``sweep``); the idle-age prune is there too.

AN AGENT'S DELETION IS LOSSLESS-DELETE (user ruling 2026-10-21): never a raw push (``PUSH-REMOTE-DELETE``), only
:data:`DOOR`, which after a fresh fetch deletes a branch only when every commit on it is on integration or on
another live origin branch or open PR head (:func:`judge` names that container) or, by CONTENT, when no file its
own commits wrote is identical on integration, generated files aside -- a branch of forge sync merges holds no
work -- and otherwise refuses naming the commits and the files carrying unlanded content.
The delete is a lease on the judged sha through the network door, recorded as one
:data:`DELETED_EVENT` line and a ``pruned`` alarm naming the ``Lab-Session`` and the container.

LANDED-BRANCHES-SWEPT (user ruling 2026-10-29: "after a merge, clean up every branch it now includes -- as a
mechanism, in every repo"): :func:`sweep` judges EVERY undeclared origin branch, with no grace, by one question
-- does integration (or the trunk) now contain it? By ancestry, else by CONTENT (:func:`landed`, built on the
judge LOSSLESS-DELETE uses: a squash-landed or forge-synced branch carries other shas). A landed open PR is
closed (:func:`dev_lab.dev.prlanded.close_pr`), then its branch is lease-deleted; anything else is kept and said
with its reason. ``--local`` then reclaims the clean landed worktrees and deletes the landed local branches
(:func:`dev_lab.dev.branchset.apply_local`, then the content judge for those checked out nowhere). It runs
wherever integration moves: the forge's repo-wide serve pass (:func:`serve_sweep`), the GitHub job a push to
integration runs (``ci_base.toml``), and on a workstation the ``PostToolUse`` hook
(:func:`dev_lab.dev.branchprune.post_push`), which detaches ``sweep --local`` when the shell call pushed integration.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.branchset import BranchSetNotDeclared, apply_local, checked_out, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.forge import _GIT
from dev_lab.dev.forgealarm import PRUNED, Alarm, sound
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgework import ForgeCallFailed
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.prlanded import close_pr
from dev_lab.dev.reclaimrun import held

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DELETED_EVENT',
    'DOOR',
    'ORIGIN',
    'Verdict',
    'delete',
    'judge',
    'landed',
    'serve_sweep',
    'sweep',
]

#: Where the fetched origin branches live.
ORIGIN: Final = 'refs/remotes/origin/'

#: The ``event`` of the one structured line each LOSSLESS-DELETE writes.
DELETED_EVENT: Final = 'lab_commons.forge.branch-delete'
#: The door an agent deletes a remote branch through (PUSH-REMOTE-DELETE's remedy names it).
DOOR: Final = 'python -m dev_lab.dev.branchprune delete <branch>...'
#: Its refusals, each said once, here.
LOSSY: Final = '{branch}: refused -- {count} commit(s) exist on it alone ({commits}), with unlanded content in: {files}'
PROTECTED: Final = '{branch}: refused -- it is {why}, never deleted'
_FIRST: Final = 5


@dataclass(frozen=True)
class Verdict:
    """What LOSSLESS-DELETE judged of one branch: its tip, the container holding it, or why it is kept."""

    branch: str
    sha: str = ''
    container: str = ''
    lost: tuple[str, ...] = ()
    refused: str = ''


def judge(root: Path, policy: Policy, branch: str, *, open_heads: dict[str, int]) -> Verdict:
    """Whether deleting origin's *branch* loses nothing; read from the fetched remote-tracking refs alone.

    Lossless when every commit on it is on integration, or on another live origin branch or open PR head; else,
    by content, when no file its own commits wrote differs from integration (:func:`_unlanded`) -- a branch
    of sync merges whose tip tree is integration's, or differs only in a generated file, holds nothing to lose.
    """
    if branch in {policy.integration, policy.trunk}:
        return Verdict(branch, refused=PROTECTED.format(branch=branch, why='the integration branch or the trunk'))
    if branch in open_heads:
        why = f'the head of open PR #{open_heads[branch]}'
        return Verdict(branch, refused=PROTECTED.format(branch=branch, why=why))
    sha = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{ORIGIN}{branch}^{{commit}}') or '').strip()
    if not sha:
        return Verdict(branch, refused=f'{branch}: not on origin (gone already)')
    listed = (git_out(root, 'for-each-ref', '--format=%(refname)', ORIGIN) or '').split()
    others = [name for name in (ref.removeprefix(ORIGIN) for ref in listed) if name not in {branch, 'HEAD'}]
    others.sort(key=lambda name: (name != policy.integration, name not in open_heads, name))
    for name in others:
        if git_out(root, 'merge-base', '--is-ancestor', sha, f'{ORIGIN}{name}') is not None:
            label = f'open PR #{open_heads[name]} ({name})' if name in open_heads else name
            return Verdict(branch, sha, container=label)
    lost = (git_out(root, 'rev-list', sha, '--not', *(f'{ORIGIN}{name}' for name in others)) or '').split()
    unlanded = _unlanded(root, sha, others, policy.integration) if lost else ()
    if not unlanded:
        by_content = f'{policy.integration} (by content: no content {policy.integration} lacks)'
        return Verdict(branch, sha, container=by_content if lost else 'the union of the other origin branches')
    shown = ', '.join(one[:12] for one in lost[:_FIRST]) + (' ...' if len(lost) > _FIRST else '')
    files = ', '.join(unlanded)
    refused = LOSSY.format(branch=branch, count=len(lost), commits=shown, files=files)
    return Verdict(branch, sha, lost=tuple(lost), refused=refused)


def _unlanded(root: Path, sha: str, others: Sequence[str], integration: str) -> tuple[str, ...]:
    """The files its own commits wrote whose tree entry at *sha* is not *integration*'s; FAILS CLOSED.

    The commits on *sha* alone name the files they wrote: a plain commit every file it changes, a merge only the
    files it resolved (``--cc``: differing from every parent), so a sync merge of integration names none. Of those,
    a file the family generates (:data:`~dev_lab.dev.famfiles.GENERATED`) is regenerated, never lost. Any other
    whose ``(mode, blob)`` at the tip differs from integration's -- added (even empty), changed, re-moded or deleted
    -- is unlanded. A file integration changed after the branch landed it is refused too: a branch-side edit and
    integration moving ahead are not told apart, because a false refusal is safe and a false delete is not. Paths
    travel NUL-separated (``-z``), never quoted, and git failing to answer refuses every candidate.
    """
    tip_only = [sha, '--not', *(f'{ORIGIN}{name}' for name in others)]
    written = git_out(root, 'log', '-z', '--format=', '--name-only', '--cc', *tip_only)
    if written is None:
        return ("(git could not list the branch's files)",)
    candidates = sorted({path.strip('\n') for path in written.split('\0')} - {''} - GENERATED)
    if not candidates:
        return ()
    entries = [_entries(root, rev, candidates) for rev in (f'{ORIGIN}{integration}', sha)]
    if entries[0] is None or entries[1] is None:
        return tuple(candidates)
    return tuple(path for path in candidates if entries[0].get(path) != entries[1].get(path))


def _entries(root: Path, rev: str, paths: Sequence[str]) -> dict[str, str] | None:
    """``{path: 'mode blob'}`` for *paths* in *rev*'s tree (absent ones omitted); ``None`` when git could not answer."""
    listed = git_out(root, 'ls-tree', '-z', '--full-tree', rev, '--', *paths)
    if listed is None:
        return None
    found: dict[str, str] = {}
    for record in filter(None, listed.split('\0')):
        meta, path = record.split('\t', 1)
        mode, _, blob = meta.split()
        found[path] = f'{mode} {blob}'
    return found


def _push_delete(root: Path, branch: str, sha: str) -> str:
    """Delete origin's *branch* if still at *sha* (a lease), through the network door; ``''``, or why not."""
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
    """LOSSLESS-DELETE each of *branches* after a fresh fetch; 0 when every one was deleted, else 1."""
    fetch(root)
    policy = load_policy(root)
    heads = {pr.head: pr.number for pr in pr_list(client)}
    failed = 0
    for branch in branches:
        found = judge(root, policy, branch, open_heads=heads)
        why = found.refused or push(root, branch, found.sha)
        if why:
            say(why if found.refused else f'{branch}: the delete failed: {why}')
            failed += 1
            continue
        record = {'event': DELETED_EVENT, 'ref': branch, 'sha': found.sha, 'container': found.container}
        say(json.dumps(record | {'session': session or None}))
        body = f'{branch} at {found.sha[:12]}, held by {found.container}; by session {session or "none"}'
        alarm(Alarm(PRUNED, client.forge.repo, f'{branch} deleted (lossless)', body))
        say(f'{branch}: deleted at {found.sha[:12]} -- held by {found.container}')
    return 1 if failed else 0


#: Why the sweep keeps a branch: content integration lacks.
NOT_LANDED: Final = '{branch}: kept -- {count} commit(s) not on {integration}, with unlanded content in: {files}'


def landed(root: Path, policy: Policy, ref: str) -> Verdict:
    """Whether *ref* (a full ref name) is contained in origin's integration or trunk: by ancestry, else by content.

    The content judge is :func:`_unlanded` against integration -- every file *ref*'s own commits wrote must be
    identical there, generated files aside -- so a squash-landed or forge-synced branch is landed under other
    shas, and one unlanded line keeps it. No other branch is a holder: that is LOSSLESS-DELETE's wider
    question (:func:`judge`); the sweep asks only whether integration now includes the branch.
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
    unlanded = _unlanded(root, sha, holders, policy.integration)
    if not unlanded:
        return Verdict(branch, sha, container=f'{policy.integration} (by content: no content it lacks)')
    lost = (git_out(root, 'rev-list', sha, '--not', *(f'{ORIGIN}{name}' for name in holders)) or '').split()
    files = ', '.join(unlanded)
    refused = NOT_LANDED.format(branch=branch, count=len(lost), integration=policy.integration, files=files)
    return Verdict(branch, sha, lost=tuple(lost), refused=refused)


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
