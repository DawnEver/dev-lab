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
AN AGENT'S DELETION and THE LANDED SWEEP live in :mod:`dev_lab.dev.branchdelete` (LOSSLESS-DELETE,
LANDED-BRANCHES-SWEPT); this module keeps their command line (``delete``, ``sweep``) and the workstation's
``PostToolUse`` hook (:func:`post_push`), which detaches ``sweep --local`` when a shell call pushed integration.


EACH DELETION IS PINNED to the sha the survey judged: the live tip is read from the forge first, and a
branch that moved is kept -- a new tip is somebody's new work. Each deletion is one structured line
(:data:`EVENT`: ref, sha, rule), and the tick raises ONE :data:`~dev_lab.dev.forgealarm.PRUNED` alarm
naming every branch it deleted, and one :data:`~dev_lab.dev.forgealarm.STALE_BRANCH` alarm naming every
unmerged stale one.
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

from dev_lab.dev.branchdelete import DOOR, ORIGIN, delete, sweep
from dev_lab.dev.branchset import BranchSet, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgealarm import PRUNED, STALE_BRANCH, Alarm
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgework import ForgeCallFailed, client_for
from dev_lab.dev.labsession import ENV
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.pushwatch import pushed_head
from dev_lab.dev.reclaimrun import detach_argv

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'DELETABLE',
    'DELETE',
    'EPHEMERAL',
    'EVENT',
    'MERGED',
    'STALE',
    'UNMERGED',
    'Row',
    'listing',
    'main',
    'post_push',
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
    refs = (f'{ORIGIN}{policy.integration}', f'{ORIGIN}{policy.trunk}')
    return tuple(ref for ref in refs if git_out(root, 'rev-parse', '--verify', '--quiet', ref))


def survey(
    root: Path, branchset: BranchSet, policy: Policy, *, open_heads: Iterable[str], now: datetime
) -> tuple[Row, ...]:
    """Every undeclared origin branch of *root* idle past the grace, as a :class:`Row`; read from local refs.

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
        ref, sha, stamp = line.split('\t')
        name = ref.removeprefix(ORIGIN)
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
    counted = git_out(root, 'rev-list', '--left-right', '--count', f'{row.sha}...{ORIGIN}{integration}')
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


#: Where a detached sweep writes its lines (``output/logs/<yy>/<mm>/<dd>/<kind>/``).
_LOG_KIND: Final = 'prune'
#: A push older than this is not the one the shell call just made.
POST_PUSH_WINDOW_S: Final = 600.0


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
    entry = git_out(cwd, 'reflog', 'show', '-1', '--date=unix', '--format=%gs%x09%gd', f'{ORIGIN}{integration}')
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
