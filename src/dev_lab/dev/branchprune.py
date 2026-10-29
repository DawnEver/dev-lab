"""MERGED-BRANCHES-PRUNED: the forge deletes the origin branches integration has finished with.

User ruling 2026-10-13: "origin should not carry this much garbage -- build the mechanism." The forge's
``branchset`` status (:mod:`dev_lab.dev.forgeheadgate`) reds a PR head its set does not admit, but branches
still FINISH, and a finished branch left on origin is debt nobody owns. So EVERY serving host surveys origin
on its serve tick (:func:`serve_prune`), after the tick's ``git fetch --prune``. No host owns this: a
deletion is pinned to the judged sha, so two hosts racing delete once and the second finds it gone (a no-op).

AN ORIGIN BRANCH IS A ROW of :func:`survey` when it is NOT declared (the branch set, the integration branch,
the trunk) and its tip has sat idle -- its committer date -- for at least ``grace_hours``. Then:

* MERGED (:data:`MERGED`): its tip is an ancestor of origin's integration branch or trunk, and no open pull
  request has it as head. Deleted (:data:`DELETE`) when the repo declares ``prune_merged = true``, else
  listed as :data:`DELETABLE` -- what ``forge integration`` and ``forge queue`` print.
* EPHEMERAL (:data:`EPHEMERAL`): it lies in a declared ephemeral namespace (``[tool.dev_lab.branchset]
  ephemeral``, e.g. ``pr/*``) and no open pull request has it as head: its PR merged or closed. Always
  DELETED -- declaring the namespace IS the opt-in, and a PR head outlives its PR by nothing but the grace.
* UNMERGED (:data:`UNMERGED`): anything else. ALARMED with its age (:data:`STALE`), NEVER deleted: its
  commits exist nowhere else.

THE SERVE TICK'S DELETION IS DATA: the opt-in is a reviewed edit of the repo's ``[tool.dev_lab.branchset]``.
AN AGENT'S DELETION IS LOSSLESS-DELETE (user ruling 2026-10-21): never a raw push (``PUSH-REMOTE-DELETE``), only
:data:`DOOR`, which after a fresh fetch deletes a branch only when every commit on it is on integration or on
another live origin branch or open PR head (:func:`judge` names that container) or, by CONTENT, when no file its
own commits wrote is identical on integration, generated files aside -- a branch of forge sync merges holds no
work -- and otherwise refuses naming the commits and the files carrying unlanded content.
The delete is a lease on the judged sha through the network door, recorded as one
:data:`DELETED_EVENT` line and a ``pruned`` alarm naming the ``Lab-Session`` and the container.

EACH DELETION IS PINNED to the sha the survey judged: the live tip is read from the forge first, and a
branch that moved is kept -- a new tip is somebody's new work. Each deletion is one structured line
(:data:`EVENT`: ref, sha, rule), and the tick raises ONE :data:`~dev_lab.dev.forgealarm.PRUNED` alarm
naming every branch it deleted, and one :data:`~dev_lab.dev.forgealarm.STALE_BRANCH` alarm naming every
unmerged stale one.

LANDED-BRANCHES-SWEPT (user ruling 2026-10-29: "after a merge, clean up every branch it now includes -- as a
mechanism, in every repo"): :func:`sweep` judges EVERY undeclared origin branch, with no grace, by one question
-- does integration (or the trunk) now contain it? By ancestry, else by CONTENT (:func:`landed`, built on the
judge LOSSLESS-DELETE uses: a squash-landed or forge-synced branch carries other shas). A landed open PR is
closed (:func:`dev_lab.dev.prlanded.close_pr`), then its branch is lease-deleted; anything else is kept and said
with its reason. ``--local`` then reclaims the clean landed worktrees and deletes the landed local branches
(:func:`dev_lab.dev.branchset.apply_local`, then the content judge for those checked out nowhere). It runs
wherever integration moves: the forge's repo-wide serve pass (:func:`serve_sweep`), the GitHub job a push to
integration runs (``ci_base.toml``), and on a workstation the ``PostToolUse`` hook (:func:`post_push`), which
detaches ``sweep --local`` when the shell call pushed integration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.branchset import BranchSet, BranchSetNotDeclared, apply_local, checked_out, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.forge import _GIT, fetch_origin
from dev_lab.dev.forgealarm import PRUNED, STALE_BRANCH, Alarm, sound
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgework import ForgeCallFailed, client_for
from dev_lab.dev.labsession import ENV
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.prlanded import close_pr
from dev_lab.dev.pushwatch import pushed_head
from dev_lab.dev.reclaimrun import detach_argv, held

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DELETABLE',
    'DELETE',
    'DELETED_EVENT',
    'DOOR',
    'EPHEMERAL',
    'EVENT',
    'MERGED',
    'STALE',
    'UNMERGED',
    'Row',
    'Verdict',
    'delete',
    'judge',
    'landed',
    'listing',
    'main',
    'post_push',
    'prune',
    'serve_prune',
    'serve_sweep',
    'survey',
    'sweep',
]

#: The ``event`` of the one structured line each deletion writes.
EVENT: Final = 'lab_commons.forge.prune'

#: The rules a row is judged by.
MERGED: Final = 'merged-idle'
UNMERGED: Final = 'unmerged-stale'
EPHEMERAL: Final = 'ephemeral-done'

#: What happens to a row: deleted (opted in), listed for a human (not opted in), alarmed (unmerged).
DELETE: Final = 'delete'
DELETABLE: Final = 'deletable'
STALE: Final = 'stale'

_ORIGIN: Final = 'refs/remotes/origin/'
_HOUR_S: Final = 3600.0
#: The forge's answer for a branch that does not exist.
_NOT_FOUND: Final = 404


@dataclass(frozen=True)
class Row:
    """One undeclared origin branch idle past the grace, the rule it falls under, and what is done to it."""

    ref: str
    sha: str
    rule: str
    action: str
    idle_h: float

    def line(self) -> str:
        """The row as a human reads it."""
        return f'{self.action:<9} {self.ref}  {self.sha[:12]}  {self.rule}, idle {self.idle_h:.0f} h'


def _holders(root: Path, policy: Policy) -> tuple[str, ...]:
    refs = (f'{_ORIGIN}{policy.integration}', f'{_ORIGIN}{policy.trunk}')
    return tuple(ref for ref in refs if git_out(root, 'rev-parse', '--verify', '--quiet', ref))


def survey(
    root: Path, branchset: BranchSet, policy: Policy, *, open_heads: Iterable[str], now: datetime
) -> tuple[Row, ...]:
    """Every undeclared origin branch of *root* idle past the grace, as a :class:`Row`; read from local refs.

    Raises:
        OSError: git could not list origin's refs -- an unread origin is not a clean one.

    """
    listed = git_out(root, 'for-each-ref', '--format=%(refname)%09%(objectname)%09%(committerdate:unix)', _ORIGIN)
    if listed is None:
        msg = f'git could not list the origin refs of {root}; nothing was judged'
        raise OSError(msg)
    keep = branchset.declared | {policy.integration, policy.trunk, 'HEAD'}
    heads = frozenset(open_heads)
    holders = _holders(root, policy)
    rows: list[Row] = []
    for line in listed.splitlines():
        ref, sha, stamp = line.split('\t')
        name = ref.removeprefix(_ORIGIN)
        idle_h = (now - datetime.fromtimestamp(int(stamp), tz=UTC)).total_seconds() / _HOUR_S
        if name in keep or idle_h < branchset.grace_hours:
            continue
        if branchset.is_ephemeral(name):
            if name not in heads:
                rows.append(Row(name, sha, EPHEMERAL, DELETE, idle_h))
            continue
        merged = any(git_out(root, 'merge-base', '--is-ancestor', sha, holder) is not None for holder in holders)
        if not merged:
            rows.append(Row(name, sha, UNMERGED, STALE, idle_h))
        elif name not in heads:
            rows.append(Row(name, sha, MERGED, DELETE if branchset.prune_merged else DELETABLE, idle_h))
    return tuple(sorted(rows, key=lambda row: row.ref))


def listing(root: Path, client: Client, *, now: datetime) -> tuple[Row, ...]:
    """*root*'s declared branch set and policy, the open pull requests' heads, and the :func:`survey` they give."""
    heads = {pr.head for pr in pr_list(client)}
    return survey(root, declared_branchset(root), load_policy(root), open_heads=heads, now=now)


def _live_tip(client: Client, name: str) -> str | None:
    """The branch's tip as the forge sees it now; ``None`` when it is already gone."""
    try:
        commit = client.call('GET', f'{client.repo}/branches/{urllib.parse.quote(name, safe="/")}')['commit']
    except ForgeCallFailed as failed:
        attempts = failed.report.attempts
        if attempts and attempts[-1].returncode == _NOT_FOUND:
            return None
        raise
    return str(commit.get('id') or commit.get('sha') or '')


def _delete(client: Client, row: Row, say: Callable[[str], None]) -> bool:
    """Delete *row*'s branch if its live tip is still the judged sha; whether it was deleted."""
    live = _live_tip(client, row.ref)
    if live != row.sha:
        state = 'gone already' if live is None else f'moved to {live[:12]}'
        say(f'[prune] kept {row.ref}: {state} since the survey judged {row.sha[:12]}')
        return False
    path = client.backend.branch_delete.format(name=urllib.parse.quote(row.ref, safe='/'))
    try:
        client.call('DELETE', f'{client.repo}/{path}')
    except ForgeCallFailed:
        if _live_tip(client, row.ref) is not None:
            raise
        say(f'[prune] {row.ref}: another host deleted it first (a no-op here)')
        return False
    say(json.dumps({'event': EVENT, 'ref': row.ref, 'sha': row.sha, 'rule': row.rule}))
    return True


def _stale_entry(root: Path, row: Row, integration: str) -> str:
    """One stale row: where it stands against integration, and the two decisions -- land it, or abandon it."""
    counted = git_out(root, 'rev-list', '--left-right', '--count', f'{row.sha}...{_ORIGIN}{integration}')
    ahead, behind = counted.split() if counted else ('?', '?')
    return (
        f'{row.ref} {row.sha[:12]} idle {row.idle_h:.0f} h, not merged: {ahead} ahead, {behind} behind {integration}\n'
        f'  land it:   python -m dev_lab.dev.forge pr create --head {row.ref} --base {integration} '
        f'--title "<what it does>"\n'
        f'  abandon it (a human; its {ahead} commit(s) exist nowhere else): git push origin --delete {row.ref}'
    )


def prune(
    root: Path,
    client: Client,
    *,
    now: datetime,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> tuple[Row, ...]:
    """One pass over origin: delete what the declaration allows, alarm what was deleted and what is stale.

    Reads the branch set and the integration policy from *root*; the refs must be fetched already.
    """
    rows = listing(root, client, now=now)
    deleted = [row for row in rows if row.action == DELETE and _delete(client, row, say)]
    repo = client.forge.repo
    if deleted:
        body = '\n'.join(f'{row.ref} {row.sha[:12]} ({row.rule}, idle {row.idle_h:.0f} h)' for row in deleted)
        alarm(Alarm(PRUNED, repo, f'{len(deleted)} merged branch(es) deleted from origin', body))
    stale = [row for row in rows if row.action == STALE]
    if stale:
        integration = load_policy(root).integration
        body = '\n'.join(_stale_entry(root, row, integration) for row in stale)
        body += f'\nan agent deletes one whose commits all live elsewhere: {DOOR}'
        alarm(Alarm(STALE_BRANCH, repo, f'{len(stale)} unmerged branch(es) idle on origin', body))
    return rows


def serve_prune(
    root: Path,
    client: Client,
    *,
    now: datetime,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
) -> tuple[Row, ...]:
    """The serve tick's step on any host: :func:`prune`; a failure only alarms."""
    try:
        return prune(root, client, now=now, say=say, alarm=alarm)
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        alarm(Alarm(PRUNED, client.forge.repo, 'the origin branch prune failed', str(failed)))
        return ()


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
    sha = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{_ORIGIN}{branch}^{{commit}}') or '').strip()
    if not sha:
        return Verdict(branch, refused=f'{branch}: not on origin (gone already)')
    listed = (git_out(root, 'for-each-ref', '--format=%(refname)', _ORIGIN) or '').split()
    others = [name for name in (ref.removeprefix(_ORIGIN) for ref in listed) if name not in {branch, 'HEAD'}]
    others.sort(key=lambda name: (name != policy.integration, name not in open_heads, name))
    for name in others:
        if git_out(root, 'merge-base', '--is-ancestor', sha, f'{_ORIGIN}{name}') is not None:
            label = f'open PR #{open_heads[name]} ({name})' if name in open_heads else name
            return Verdict(branch, sha, container=label)
    lost = (git_out(root, 'rev-list', sha, '--not', *(f'{_ORIGIN}{name}' for name in others)) or '').split()
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
    tip_only = [sha, '--not', *(f'{_ORIGIN}{name}' for name in others)]
    written = git_out(root, 'log', '-z', '--format=', '--name-only', '--cc', *tip_only)
    if written is None:
        return ("(git could not list the branch's files)",)
    candidates = sorted({path.strip('\n') for path in written.split('\0')} - {''} - GENERATED)
    if not candidates:
        return ()
    entries = [_entries(root, rev, candidates) for rev in (f'{_ORIGIN}{integration}', sha)]
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
#: Where a detached sweep writes its lines (``output/logs/<yy>/<mm>/<dd>/<kind>/``).
_LOG_KIND: Final = 'prune'
#: A push older than this is not the one the shell call just made.
POST_PUSH_WINDOW_S: Final = 600.0


def landed(root: Path, policy: Policy, ref: str) -> Verdict:
    """Whether *ref* (a full ref name) is contained in origin's integration or trunk: by ancestry, else by content.

    The content judge is :func:`_unlanded` against integration -- every file *ref*'s own commits wrote must be
    identical there, generated files aside -- so a squash-landed or forge-synced branch is landed under other
    shas, and one unlanded line keeps it. No other branch is a holder: that is LOSSLESS-DELETE's wider
    question (:func:`judge`); the sweep asks only whether integration now includes the branch.
    """
    branch = ref.removeprefix(_ORIGIN).removeprefix('refs/heads/')
    sha = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}') or '').strip()
    names = (policy.integration, policy.trunk)
    holders = [name for name in names if git_out(root, 'rev-parse', '--verify', '--quiet', f'{_ORIGIN}{name}')]
    if not sha or policy.integration not in holders:
        return Verdict(branch, sha, refused=f'{branch}: kept -- it or origin/{policy.integration} is unreadable')
    for name in holders:
        if git_out(root, 'merge-base', '--is-ancestor', sha, f'{_ORIGIN}{name}') is not None:
            return Verdict(branch, sha, container=name)
    unlanded = _unlanded(root, sha, holders, policy.integration)
    if not unlanded:
        return Verdict(branch, sha, container=f'{policy.integration} (by content: no content it lacks)')
    lost = (git_out(root, 'rev-list', sha, '--not', *(f'{_ORIGIN}{name}' for name in holders)) or '').split()
    files = ', '.join(unlanded)
    refused = NOT_LANDED.format(branch=branch, count=len(lost), integration=policy.integration, files=files)
    return Verdict(branch, sha, lost=tuple(lost), refused=refused)


def _origin_branches(root: Path) -> list[str]:
    listed = git_out(root, 'for-each-ref', '--format=%(refname)', _ORIGIN)
    if listed is None:
        msg = f'git could not list the origin refs of {root}; nothing was swept'
        raise OSError(msg)
    return sorted(ref.removeprefix(_ORIGIN) for ref in listed.split())


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
    tip = (git_out(root, 'rev-parse', f'{_ORIGIN}{policy.integration}') or '').strip()
    deleted: list[Verdict] = []
    failed = 0
    for name in _origin_branches(root):
        if name in keep:
            continue
        found = landed(root, policy, f'{_ORIGIN}{name}')
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


def _write_log(root: Path, lines: Sequence[str]) -> None:
    now = datetime.now().astimezone()
    log = root / 'output' / 'logs' / now.strftime('%y/%m/%d') / _LOG_KIND / f'{now:%H%M%S}-{os.getpid()}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _main_of(cwd: Path) -> Path | None:
    """The main checkout of the repository *cwd* lies in, from a linked worktree too; ``None`` outside git."""
    common = git_out(cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if not common:
        return None
    path = Path(common.strip()).resolve()
    return path.parent if path.name == '.git' else None


def _pushed_integration(cwd: Path, now: float) -> bool:
    """Whether origin's integration tracking ref was last moved by a push, within :data:`POST_PUSH_WINDOW_S`."""
    try:
        integration = load_policy(cwd).integration
    except (OSError, ValueError):
        return False
    entry = git_out(cwd, 'reflog', 'show', '-1', '--date=unix', '--format=%gs%x09%gd', f'{_ORIGIN}{integration}')
    subject, _, selector = (entry or '').strip().partition('\t')
    stamp = selector.rpartition('@{')[2].rstrip('}')
    return subject == 'update by push' and stamp.isdigit() and now - int(stamp) <= POST_PUSH_WINDOW_S


def _detach_sweep(root: Path) -> None:
    detach_argv(root, ['-m', 'dev_lab.dev.branchprune', 'sweep', '--local', '--log'])


def post_push(
    argv: Sequence[str],
    *,
    stdin: TextIO | None = None,
    detach: Callable[[Path], None] = _detach_sweep,
    clock: Callable[[], float] = time.time,
) -> int:
    """The ``PostToolUse`` hook on the shell tools: a call that pushed integration detaches ``sweep --local``.

    Read off the remote-tracking ref's reflog -- git records ``update by push`` there -- so every spelling of the
    push counts (a refspec, an upstream, the retry wrapper) and a fetch never does. Never blocks; always 0.
    """
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    try:
        cwd = Path(payload.get('cwd') or Path.cwd())
        root = _main_of(cwd)
        if root is not None and pushed_head(cwd, command) is not None and _pushed_integration(cwd, clock()):
            detach(root)
    except OSError:
        return 0
    return 0


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``python -m dev_lab.dev.branchprune {delete <branch>... | sweep [--local] [--log] | post-push}``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.branchprune', description=main.__doc__)
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('delete').add_argument('branches', nargs='+')
    swept = verbs.add_parser('sweep')
    swept.add_argument('--local', action='store_true', help='also local branches and clean landed worktrees')
    swept.add_argument('--log', action='store_true', help=f'write to output/logs/.../{_LOG_KIND}/, not the console')
    verbs.add_parser('post-push')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.verb == 'post-push':
        return post_push([])
    root = Path.cwd() if cwd is None else cwd
    lines: list[str] = []
    say: Callable[[str], None] = lines.append if args.verb == 'sweep' and args.log else emit
    try:
        client = client_for(root)
        session = os.environ.get(ENV, '')
        if args.verb == 'delete':
            return delete(root, args.branches, client=client, session=session, fetch=fetch_origin, say=say)
        return sweep(root, client=client, session=session, fetch=fetch_origin, say=say, local=args.local)
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        if say is emit:
            emit(f'[branchprune] {failed}', err=True)
        else:
            say(f'[branchprune] {failed}')
        return 2
    finally:
        if lines:
            _write_log(root, lines)


if __name__ == '__main__':
    raise SystemExit(main())
