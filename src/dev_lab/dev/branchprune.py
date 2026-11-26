"""MERGED-BRANCHES-PRUNED: the forge deletes the origin branches integration has finished with.

User ruling 2026-10-13: "origin should not carry this much garbage -- build the mechanism." The forge's
``session-branch`` status (:mod:`dev_lab.dev.forgeheadgate`) reds a PR head its set does not admit, but branches
still FINISH, and a finished branch left on origin is debt nobody owns. So EVERY serving host surveys origin
on its serve tick (:func:`serve_prune`), after the tick's ``git fetch --prune``. No host owns this: a
deletion is pinned to the judged sha, so two hosts racing delete once and the second finds it gone (a no-op).

AN ORIGIN BRANCH IS A ROW of :func:`survey` when it is NOT declared (the branch set, the integration branch,
the trunk) and it has sat idle -- since its last push or PR activity (:mod:`dev_lab.dev.branchactivity`), never its
committer date -- for at least ``max_idle_hours``; a branch with no activity on record is listed UNKNOWN
(:data:`UNKNOWN_IDLE`) and nothing is done to it. MERGED means LANDED: an ancestor whose landing merge kept its
content (:func:`~dev_lab.dev.deletejudge.landed`), so a branch an ``-s ours`` merge only made an ancestor is UNMERGED
(dev-lab #611). Then:

* MERGED (:data:`MERGED`): its tip is an ancestor of origin's integration branch or trunk, and no open pull
  request has it as head. Deleted (:data:`DELETE`) when the repo declares ``prune_merged = true``, else
  listed as :data:`DELETABLE` -- what ``forge integration`` and ``forge queue`` print.
* EPHEMERAL (:data:`EPHEMERAL`): it lies in a declared ephemeral namespace (``[tool.dev_lab.branchset]
  ephemeral``, e.g. ``pr/*``), it is MERGED, and no open pull request has it as head. Always DELETED --
  declaring the namespace IS the opt-in, and a landed PR head outlives its PR by nothing but the grace.
* UNMERGED (:data:`UNMERGED`): anything else, ephemeral or not. LISTED and ALARMED with its age (:data:`STALE`)
  with what dropping it would discard and its two doors -- MERGE it through a PR, or, only on the user's words,
  ``branchprune discard`` it (:data:`~dev_lab.dev.branchdelete.MERGE_OR_DISCARD`) -- NEVER deleted: its commits
  exist nowhere else, and the survey deletes nothing LOSSLESS-DELETE would refuse (D30, user 2026-11-17, retiring
  the delete of an unmerged no-PR ephemeral head).

THE SERVE TICK'S DELETION IS DATA: the opt-in is a reviewed edit of the repo's ``[tool.dev_lab.branchset]``.
AN AGENT'S DELETION, THE USER'S DISCARD and THE LANDED SWEEP live in :mod:`dev_lab.dev.branchdelete`
(LOSSLESS-DELETE, ``discard <branch> --approved "<words>"``, LANDED-BRANCHES-SWEPT); this module keeps their command
line (``delete``, ``discard``, ``tag``, ``task``, ``sweep``).


EACH DELETION IS PINNED to the sha the survey judged: the live tip is read from the forge first, and a
branch that moved is kept -- a new tip is somebody's new work. Each deletion is one structured line
(:data:`EVENT`: ref, sha, rule), and the tick raises ONE :data:`~dev_lab.dev.forgealarm.PRUNED` alarm
naming every branch it deleted, and one :data:`~dev_lab.dev.forgealarm.STALE_BRANCH` alarm naming every
unmerged stale one.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import urllib.parse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev._branch_tags import delete_contained_tags
from dev_lab.dev.branchactivity import UNKNOWN, Activity, activity_of, idle_hours
from dev_lab.dev.branchdelete import DOOR, MERGE_OR_DISCARD, UNAPPROVED, delete, delete_task, discard, sweep
from dev_lab.dev.branchset import BranchSet, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.deletejudge import ORIGIN, landed, would_discard
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgealarm import PRUNED, STALE_BRANCH, Alarm
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.labsession import ENV
from dev_lab.dev.lanepolicy import Policy, load_policy

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DELETABLE',
    'DELETE',
    'EPHEMERAL',
    'EVENT',
    'MERGED',
    'STALE',
    'UNKNOWN_IDLE',
    'UNMERGED',
    'Row',
    'listing',
    'main',
    'prune',
    'serve_prune',
    'survey',
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
#: Listed, never acted on: the forge records no push or PR activity, so how long it sat idle is UNKNOWN.
UNKNOWN_IDLE: Final = 'unknown-idle'

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
    idle_h: float | None

    @property
    def idle(self) -> str:
        """The idle age as printed: hours, or UNKNOWN when the forge records no activity."""
        return UNKNOWN if self.idle_h is None else f'{self.idle_h:.0f} h'

    def line(self) -> str:
        """The row as a human reads it."""
        return f'{self.action:<9} {self.ref}  {self.sha[:12]}  {self.rule}, idle {self.idle}'


def _holders(root: Path, policy: Policy) -> tuple[str, ...]:
    refs = (f'{ORIGIN}{policy.integration}', f'{ORIGIN}{policy.trunk}')
    return tuple(ref for ref in refs if git_out(root, 'rev-parse', '--verify', '--quiet', ref))


def survey(
    root: Path,
    branchset: BranchSet,
    policy: Policy,
    *,
    open_heads: Iterable[str],
    now: datetime,
    activity: Activity,
) -> tuple[Row, ...]:
    """Every undeclared origin branch of *root* idle past the grace, as a :class:`Row`; read from local refs.

    Idle is the branch's last push or PR *activity* (:mod:`dev_lab.dev.branchactivity`); a branch whose activity
    the forge does not record is an :data:`UNKNOWN` row, listed and never deleted. MERGED is LANDED -- an ancestor
    of integration or the trunk whose landing merge kept its content (:func:`~dev_lab.dev.deletejudge.landed`);
    a branch only an ``-s ours`` merge made an ancestor is UNMERGED.

    Raises:
        OSError: git could not list origin's refs -- an unread origin is not a clean one.

    """
    listed = git_out(root, 'for-each-ref', '--format=%(refname)%09%(objectname)%09%(committerdate:unix)', ORIGIN)
    if listed is None:
        msg = f'git could not list the origin refs of {root}; nothing was judged'
        raise OSError(msg)
    keep = branchset.declared | {policy.integration, policy.trunk, 'HEAD'}
    heads = frozenset(open_heads)
    holders = _holders(root, policy)
    rows: list[Row] = []
    for line in listed.splitlines():
        ref, sha, stamp = line.split('	')
        name = ref.removeprefix(ORIGIN)
        if name in keep:
            continue
        committed = datetime.fromtimestamp(int(stamp), tz=UTC)
        idle_h = idle_hours(name, committed, now=now, bound=branchset.max_idle_hours, activity=activity)
        if idle_h is not None and idle_h < branchset.max_idle_hours:
            continue
        if branchset.is_ephemeral(name) and name in heads:
            continue  # its open PR owns it
        merged = landed(root, sha, holders)
        if idle_h is None:
            rows.append(Row(name, sha, MERGED if merged else UNMERGED, UNKNOWN_IDLE, None))
        elif not merged:
            rows.append(Row(name, sha, UNMERGED, STALE, idle_h))
        elif branchset.is_ephemeral(name):
            rows.append(Row(name, sha, EPHEMERAL, DELETE, idle_h))
        elif name not in heads:
            rows.append(Row(name, sha, MERGED, DELETE if branchset.prune_merged else DELETABLE, idle_h))
    return tuple(sorted(rows, key=lambda row: row.ref))


def listing(root: Path, client: Client, *, now: datetime) -> tuple[Row, ...]:
    """*root*'s declared branch set and policy, the open pull requests' heads, and the :func:`survey` they give."""
    heads = {pr.head for pr in pr_list(client)}
    policy = load_policy(root)
    activity = activity_of(client, policy.integration)
    return survey(root, declared_branchset(root), policy, open_heads=heads, now=now, activity=activity)


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


def _delete(client: Client, row: Row, say: Callable[[str], None], merged_now: Callable[[str], bool]) -> bool:
    """Delete *row*'s branch if its live tip is still the judged sha AND still merged now; whether it was deleted."""
    live = _live_tip(client, row.ref)
    if live != row.sha:
        state = 'gone already' if live is None else f'moved to {live[:12]}'
        say(f'[prune] kept {row.ref}: {state} since the survey judged {row.sha[:12]}')
        return False
    if not merged_now(row.sha):
        say(f'[prune] kept {row.ref}: {row.sha[:12]} is no longer held by integration or the trunk at delete time')
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
    counted = git_out(root, 'rev-list', '--left-right', '--count', f'{row.sha}...{ORIGIN}{integration}')
    ahead, behind = counted.split() if counted else ('?', '?')
    return (
        f'{row.ref} {row.sha[:12]} idle {row.idle}, not merged: {ahead} ahead, {behind} behind {integration}\n'
        f'  land it:   python -m dev_lab.dev.forge pr create --head {row.ref} --base {integration} '
        f'--title "<what it does>"\n'
        f'  dropping it discards {would_discard(root, row.sha, integration)}\n'
        f'  {MERGE_OR_DISCARD.format(branch=row.ref)}'
    )


def prune(
    root: Path,
    client: Client,
    *,
    now: datetime,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
    fetch: Callable[[Path], None] = fetch_origin,
) -> tuple[Row, ...]:
    """One pass over origin: delete what the declaration allows, alarm what was deleted and what is stale.

    Reads the branch set and the integration policy from *root*; the refs must be fetched already. Before each
    deletion origin is *fetch*-ed again and the judged sha re-checked as an ancestor of integration or the trunk,
    so a base rewound since the survey keeps the branch (the survey's answer is never trusted at delete time).
    """
    rows = listing(root, client, now=now)
    policy = load_policy(root)

    def merged_now(sha: str) -> bool:
        fetch(root)
        return landed(root, sha, _holders(root, policy))

    deleted = [row for row in rows if row.action == DELETE and _delete(client, row, say, merged_now)]
    repo = client.forge.repo
    if deleted:
        body = '\n'.join(f'{row.ref} {row.sha[:12]} ({row.rule}, idle {row.idle})' for row in deleted)
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


#: Where ``sweep --log`` writes its lines (``output/logs/<yy>/<mm>/<dd>/<kind>/``).
_LOG_KIND: Final = 'prune'


def _write_log(root: Path, lines: Sequence[str]) -> None:
    now = datetime.now().astimezone()
    log = root / 'output' / 'logs' / now.strftime('%y/%m/%d') / _LOG_KIND / f'{now:%H%M%S}-{os.getpid()}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('\n'.join(lines) + '\n', encoding='utf-8')


#: RETIRED-NAMES-REGISTERED: the spellings of the tag-held delete D22 retired (2026-11-17: "no tags -- either merge
#: or delete"), each refused by name with the door that replaced it, never parsed as unknown.
RETIRED: Final = {
    'delete-tag': 'tags are no place to keep work (D22); a branch is merged or deleted: ' + DOOR,
    '--approved': 'no tag-held delete (D22); a refused branch names its doors: MERGE it, or on the user words '
    'discard it: python -m dev_lab.dev.branchprune discard <branch> --approved "<the user words>"; a landed one: '
    + DOOR,
}


def retired(argv: Sequence[str]) -> str:
    """The refusal naming the first retired spelling in *argv* and its door; ``''`` when none."""
    if list(argv[:1]) == ['discard']:
        argv = [word for word in argv if word.partition('=')[0] != '--approved']
    for word in argv:
        door = RETIRED.get(word.partition('=')[0])
        if door:
            return f'[branchprune] `{word.partition("=")[0]}` is retired: {door}'
    return ''


def _unapproved(argv: Sequence[str]) -> str:
    """:data:`~dev_lab.dev.branchdelete.UNAPPROVED` when a ``discard`` carries no words of the user's; else ``''``."""
    if list(argv[:1]) != ['discard']:
        return ''
    given = [
        word.partition('=')[2] if '=' in word else ''.join(argv[at + 1 : at + 2])
        for at, word in enumerate(argv)
        if word.partition('=')[0] == '--approved'
    ]
    return '' if any(one.strip() for one in given) else UNAPPROVED


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``python -m dev_lab.dev.branchprune {delete B... | tag T... | task S | sweep}``."""
    words = list(sys.argv[1:] if argv is None else argv)
    if why := retired(words) or _unapproved(words):
        emit(why, err=True)
        return 2
    parser = argparse.ArgumentParser(prog='dev_lab.dev.branchprune', description=main.__doc__)
    verbs = parser.add_subparsers(dest='verb', required=True)
    deleted = verbs.add_parser('delete', help='a branch whose content is held elsewhere')
    deleted.add_argument('branches', nargs='+')
    discarded = verbs.add_parser('discard', help='a branch the user ordered dropped unlanded (their words required)')
    discarded.add_argument('branches', nargs='+')
    discarded.add_argument('--approved', default='', help="the user's own words ordering the drop (required)")
    tagged = verbs.add_parser('tag', help='an origin tag whose commit integration or the trunk contains (recorded)')
    tagged.add_argument('tags', nargs='+')
    tasked = verbs.add_parser('task', help="a closed task's pr/<slug>/* heads, each deleted losslessly or named")
    tasked.add_argument('slug')
    swept = verbs.add_parser('sweep')
    swept.add_argument('--local', action='store_true', help='also local branches and clean landed worktrees')
    swept.add_argument('--log', action='store_true', help=f'write to output/logs/.../{_LOG_KIND}/, not the console')
    args = parser.parse_args(words)
    root = Path.cwd() if cwd is None else cwd
    lines: list[str] = []
    say: Callable[[str], None] = lines.append if args.verb == 'sweep' and args.log else emit
    try:
        client = client_for(root)
        session = os.environ.get(ENV, '')
        if args.verb in {'delete', 'discard'}:
            door = functools.partial(discard, approved=args.approved) if args.verb == 'discard' else delete
            return door(root, args.branches, client=client, session=session, fetch=fetch_origin, say=say)
        if args.verb == 'tag':
            return delete_contained_tags(root, args.tags, fetch=fetch_origin, say=say)
        if args.verb == 'task':
            return delete_task(root, args.slug, client=client, session=session, fetch=fetch_origin, say=say)
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
