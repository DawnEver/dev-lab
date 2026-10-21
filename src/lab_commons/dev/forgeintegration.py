"""``forge integration``: the integration tick -- integration's standing for EVERY open child branch.

A child branch is an ``origin`` branch the schedule's one rule classes (``classes_by_ref``) or the head
of an open pull request on ``origin`` (fetched as ``pull/N/head``). PRs are opened on the forge only; GitHub is
a push mirror and is never read. The tick never writes a child;
it REPORTS on it -- and, where ``[tool.lab_commons.integrator] pr_merges_since`` is declared, asks the forge to
MERGE a PR that is green, clean and audit-passing (:mod:`lab_commons.dev.forgemerge`), saying in its comment
what is missing otherwise. Per child branch, against ``origin/<integration>`` and with no
checkout (:mod:`lab_commons.dev.trialmerge`):

* merged into integration at <sha>, or deferred and why (conflicts / parts not green / ready, waiting);
* behind N, clean or the conflicting files;
* its watched upstream set (``DOWNSTREAM-SYNCS-INTEGRATION``: integration unless opted in);
* the head's ``tests/<part>`` states, with the open ``area:*`` issues that cite the head;
* promoted to the trunk at <sha>, once the trunk holds it.

WHERE IT IS SAID. On a PR, as ONE comment found by a hidden marker and updated in place
(:func:`lab_commons.dev.forgepulls.comment_upsert`) -- a second tick changes nothing. Without a PR, as
a commit status in context :data:`CONTEXT` on the head, posted only when it differs. A PR opened
against the trunk is first RETARGETED to integration, with a comment saying why.

The tick FETCHES (origin, and each PR head) through the retry wrapper; everything after is a read
of the object store and the forge. Last, every undeclared origin branch idle past its grace is listed
(:func:`lab_commons.dev.branchprune.listing`): ``deletable`` when the repo has not opted into pruning. Deleting
is the serve tick's, never this verb's, and so is issue hygiene (:func:`lab_commons.dev.forgetidy.tidy`).

``forge serve`` runs this tick every tick, and a child that CONFLICTS with integration or is more than the
lane policy's ``behind_max`` behind it is an ``integration`` alarm (:func:`alarms`), kept as one forge issue
beside the integrator's prompts.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.compute.model import Schedule
from lab_commons.dev.branchprune import listing
from lab_commons.dev.branchset import BranchSetNotDeclared, declared_branchset
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, fetch_origin
from lab_commons.dev.forgealarm import INTEGRATION, Alarm
from lab_commons.dev.forgemerge import decide, merge
from lab_commons.dev.forgepulls import ListingIncomplete, Marker, comment_upsert, pr_list, pr_retarget
from lab_commons.dev.forgeschedule import load_schedule
from lab_commons.dev.forgestatus import CommitStatus, status_list, status_post
from lab_commons.dev.forgesync import upstreams
from lab_commons.dev.forgework import GITEA, Client, ForgeCallFailed, PullRequest, client_for
from lab_commons.dev.lanepolicy import Policy, load_policy
from lab_commons.dev.netverb import run_network_verb
from lab_commons.dev.platformparts import CONTEXT_PREFIX, UNCLAIMED, standing
from lab_commons.dev.trialmerge import contains, merged_at, rev, trial
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

__all__ = ['CONTEXT', 'Child', 'Feedback', 'Ticked', 'alarms', 'feedback', 'main', 'retarget_note', 'settle', 'tick']

#: The commit-status context a child branch without a PR carries its integration line in.
CONTEXT: Final = 'integration'

_TRACKING: Final = 'refs/remotes/origin/'
_PULLS: Final = 'refs/lab-commons/pulls/'


@dataclass(frozen=True)
class Child:
    """One child branch: its name, its head commit, where its feedback goes (a PR number, or none)."""

    branch: str
    head: str
    client: Client
    pr: int | None = None


@dataclass(frozen=True)
class Feedback:
    """What the tick says about one child: the full text, and the one-line status form of it."""

    text: str
    state: str
    summary: str
    behind: int = 0
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ticked:
    """One tick: a line per child (and per retarget), and each child with what was said about it."""

    lines: tuple[str, ...]
    said: tuple[tuple[Child, Feedback], ...]


def alarms(said: Sequence[tuple[Child, Feedback]], policy: Policy, repo: str) -> list[Alarm]:
    """An ``integration`` alarm per child that conflicts with integration or is past ``behind_max``."""
    found = []
    for child, one in said:
        why = [f'conflicts in {", ".join(one.conflicts)}'] if one.conflicts else []
        why += [f'{one.behind} behind (bound {policy.behind_max})'] if one.behind > policy.behind_max else []
        if why:
            subject = f'{child.branch} needs a sync with {policy.integration}'
            body = f'{child.branch} at {child.head[:12]}: {"; ".join(why)} (python -m lab_commons.dev.forge sync)'
            found.append(Alarm(INTEGRATION, repo, subject, body, about=f'sync {child.branch}@{child.head[:12]}'))
    return found


def _line(statuses: Sequence[CommitStatus]) -> list[str]:
    return [
        f'  - `{s.context}` {s.state}: {s.description}' + (f' ([record]({s.url}))' if s.url else '')
        for s in statuses
        if s.context.startswith(CONTEXT_PREFIX)
    ] or ['  - no `tests/<part>` part posted yet']


def _areas(client: Client, head: str) -> list[str]:
    issues = client.issue_list(state='open', limit=50)
    return [f'#{i.number} [{i.title}]({i.url})' for i in issues if i.title.startswith('area:') and head[:12] in i.body]


def feedback(root: Path, child: Child, policy: Policy) -> Feedback:
    """The integration text for *child*, from the object store and the forge; writes nothing."""
    base, trunk = f'{_TRACKING}{policy.integration}', f'{_TRACKING}{policy.trunk}'
    statuses = status_list(child.client, child.head)
    standing_now = standing(statuses, head=child.head)
    result = standing_now.result
    merge = merged_at(root, base, child.head)
    tried = trial(root, base, child.head)
    if merge is not None:
        state, verdict = 'success', f'merged into `{policy.integration}` at {merge}'
    elif not tried.clean:
        state, verdict = 'failure', f'deferred: conflicts with `{policy.integration}`'
    elif result is Conclusion.FAIL:
        state, verdict = 'failure', 'deferred: a `tests/<part>` part FAILED'
    elif result is Conclusion.PASS:
        state, verdict = 'pending', 'ready: clean and every part PASS; waiting for the integrator to merge'
    elif standing_now.reading == UNCLAIMED:
        state, verdict = 'pending', 'deferred: UNCLAIMED -- no producer has posted a `tests/<part>` status yet'
    else:
        state, verdict = 'pending', 'deferred: INCONCLUSIVE -- the posted `tests/<part>` statuses do not settle yet'
    position = 'clean' if tried.clean else 'conflicts in ' + ', '.join(f'`{f}`' for f in tried.conflicts)
    promoted = (
        f'promoted to `{policy.trunk}` (it holds {merge})'
        if merge is not None and rev(root, trunk) is not None and contains(root, trunk, merge)
        else f'not yet on `{policy.trunk}`'
    )
    watched = ', '.join(f'`{r}`' for r in upstreams(root, child.branch, policy))
    areas = _areas(child.client, child.head)
    text = '\n'.join(
        [
            f'**Integration** of `{child.branch}` at `{child.head[:12]}`',
            f'- {verdict}',
            f'- behind `{policy.integration}` by {tried.behind}; {position}',
            f'- syncs from: {watched}',
            f'- parts (standing {standing_now.reading}):',
            *_line(statuses),
            f'- area issues: {", ".join(areas) if areas else "none cite this head"}',
            f'- {promoted}',
        ]
    )
    summary = f'{verdict.replace("`", "")}; behind {tried.behind}' + (
        '' if tried.clean else f'; {len(tried.conflicts)} conflict(s)'
    )
    return Feedback(text, state, summary, tried.behind, tuple(tried.conflicts))


def retarget_note(policy: Policy) -> str:
    """The comment a trunk-targeted PR receives when it is pointed at integration."""
    return (
        f'Retargeted from `{policy.trunk}` to `{policy.integration}`: every pull request lands on '
        f'`{policy.integration}`, the coordination branch only the integrator merges into. '
        f'`{policy.trunk}` moves only by fast-forward to an `{policy.integration}` commit whose every '
        f'`tests/<part>` part is a full PASS.'
    )


def _fetch_pull(root: Path, remote: str, number: int) -> str:
    ref = f'{_PULLS}{remote}/{number}'
    report = run_network_verb(
        [_GIT, 'fetch', '--quiet', remote, f'+refs/pull/{number}/head:{ref}'], cwd=root, timeout=300
    )
    if not report.ok:
        raise OSError(report.remedy)
    found = rev(root, ref)
    if found is None:
        msg = f'pull {number} on {remote} fetched no commit'
        raise OSError(msg)
    return found


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


def _lanes(root: Path, policy: Policy, schedule: Schedule) -> list[tuple[str, str]]:
    found = []
    for line in _git(root, 'for-each-ref', '--format=%(refname) %(objectname)', _TRACKING).splitlines():
        ref, sha = line.split(' ')
        branch = ref.removeprefix(_TRACKING)
        if schedule.class_of(branch) is not None and branch not in {policy.trunk, policy.integration}:
            found.append((branch, sha))
    return found


def _publish(child: Child, said: Feedback) -> str:
    if child.pr is not None:
        action, _ = comment_upsert(child.client, child.pr, kind=Marker.INTEGRATION, text=said.text)
        return f'comment {action}'
    current = next((s for s in status_list(child.client, child.head) if s.context == CONTEXT), None)
    if current is not None and (current.state, current.description) == (said.state, said.summary[:140]):
        return 'status unchanged'
    status_post(child.client, child.head, context=CONTEXT, state=said.state, description=said.summary)
    return 'status posted'


def settle(root: Path, child: Child, policy: Policy, said: Feedback) -> Feedback:
    """Merge PR *child* through the forge when nothing is missing; *said* with the outcome added as a line.

    Only where ``pr_merges_since`` is declared and the forge is gitea; an already-merged child is left alone.
    """
    if child.pr is None or not policy.pr_merges_since or child.client.backend is not GITEA or said.state == 'success':
        return said
    statuses = status_list(child.client, child.head)
    found = decide(root, policy, branch=child.branch, number=child.pr, head=child.head, statuses=statuses)
    if found.ready:
        ephemeral = declared_branchset(root).is_ephemeral(child.branch)
        merge(child.client, child.pr, head=child.head, message=found.message, delete_branch=ephemeral)
        line, summary = f'merged by the forge into `{policy.integration}` (a merge commit)', 'merged by the forge'
    else:
        line = 'the forge merges it once it has: ' + '; '.join(found.missing)
        summary = f'{said.summary}; auto-merge waits'
    return dataclasses.replace(said, text=f'{said.text}\n- {line}', summary=summary)


def tick(
    root: Path,
    origin: Client,
    policy: Policy,
    *,
    fetch_pull: Callable[[Path, str, int], str] = _fetch_pull,
) -> Ticked:
    """One pass over every child branch on *origin*: its open PRs into integration, then the classed lanes."""
    lines: list[str] = []
    said: list[tuple[Child, Feedback]] = []
    children: list[Child] = []
    for listed in pr_list(origin):
        pr = _retarget(origin, listed, policy) if listed.base == policy.trunk else listed
        if pr is not listed:
            lines.append(f'#{pr.number} retargeted {policy.trunk} -> {policy.integration}')
        if pr.base != policy.integration:
            continue
        children.append(Child(pr.head, fetch_pull(root, 'origin', pr.number), origin, pr.number))
    with_pr = {child.branch for child in children}
    children += [Child(b, sha, origin) for b, sha in _lanes(root, policy, load_schedule(root)) if b not in with_pr]
    for child in children:
        one = settle(root, child, policy, feedback(root, child, policy))
        said.append((child, one))
        where = f'#{child.pr}' if child.pr is not None else child.head[:12]
        lines.append(f'{child.branch} {where}: {one.summary} -- {_publish(child, one)}')
    return Ticked(tuple(lines), tuple(said))


def _retarget(client: Client, pr: PullRequest, policy: Policy) -> PullRequest:
    moved = pr_retarget(client, pr.number, policy.integration)
    client.issue_comment(pr.number, retarget_note(policy))
    return moved


def main(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None, fetch: Callable[[Path], None] = fetch_origin
) -> int:
    """``forge integration``: one tick; exit 1 when the forge or a fetch fails."""
    argparse.ArgumentParser(prog='lab_commons.dev.forge integration', description=__doc__.splitlines()[0]).parse_args(
        list(sys.argv[1:] if argv is None else argv)
    )
    root = Path.cwd() if cwd is None else cwd
    try:
        fetch(root)
        origin, policy = client_for(root), load_policy(root)
        branches = (f'branch: {row.line()}' for row in listing(root, origin, now=datetime.now(UTC)))
        lines = [*tick(root, origin, policy).lines, *branches]
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete) as failed:
        emit(f'[integration] {failed}', err=True)
        return 1
    except (OSError, ValueError) as exc:
        emit(f'[integration] {exc}', err=True)
        return 1
    for line in lines or ['no open child branch']:
        emit(f'[integration] {line}')
    return 0
