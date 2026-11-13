"""LANDED-BRANCH-CONTINUES: a push onto a merged PR's branch is carried by a continuation PR the forge opens.

User-approved design 2026-11-07: review KNOWLEDGE is reused, the merged PR OBJECT never is. A merged PR stays the
immutable record of what was reviewed and tested at its head, so a commit pushed onto its branch afterwards is not
refused (NO-PUSH-ONTO-A-CLOSED-PR refuses only a PR closed unmerged, :mod:`dev_lab.dev.closedpush`): the forge opens
a NEW PR from the same branch into the same base, titled ``<title> (continues #N)`` and bodied ``Continues #N``.

A BRANCH IS CONTINUED (:func:`continuation`) when the newest PR of it into the integration branch
(:func:`~dev_lab.dev.forgepulls.pr_by_head`, one forge call) is MERGED and its head is not the branch's tip. Its
PRs are chained in the branch's one review record (:func:`dev_lab.dev.branchreview.chained`): the continuation's
review reads only the increment since the landed head, and carries the predecessors' findings
(:mod:`dev_lab.dev.branchreview`), summarised in the body it opens with.

WHO OPENS IT, the same function on both forges:

* Gitea: every serve tick's repo-wide pass (:func:`serve_continue_landed`), before the prune, over every origin
  branch that is not the integration branch or the trunk, has no open PR, and whose tip integration does not
  contain -- read from the tick's fetched refs, so a branch costs a forge call only while it holds unlanded work
  and no PR.
* GitHub: the ``continue.yml`` workflow on a push to any other branch runs ``forge pr continue --head <branch>
  --sha <sha>`` (:func:`main`). A PR the job token opens starts no workflow, so the job then dispatches ci.yml on
  the branch with the PR's number (``workflow_dispatch``, ``-f pr=<N>``): that run is the PR's, at its head sha.
  An integration branch with no ``pyproject.toml`` -- a repo's first adoption -- declares nothing, so nothing
  continues and the job exits 0, saying so.

A person or agent runs ``python -m dev_lab.dev.forge pr continue [--head <branch> --sha <sha>]``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.branchreview import carried_after, chained, context
from dev_lab.dev.checkout import git_out
from dev_lab.dev.forgealarm import PRUNED, Alarm
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_by_head, pr_list
from dev_lab.dev.forgereview_declared import review_at
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import load_policy

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'candidates',
    'continuation',
    'continue_landed',
    'continues_body',
    'continues_title',
    'main',
    'open_continuation',
    'serve_continue_landed',
]  # fmt: skip

_ORIGIN: Final = 'refs/remotes/origin/'
_CONTINUES: Final = re.compile(r'\s*\(continues #\d+\)$')


def continuation(client: Client, branch: str, base: str, tip: str) -> PullRequest | None:
    """The merged PR *branch* (at *tip*) continues into *base*; ``None``: its newest PR open, closed, or at *tip*."""
    newest = pr_by_head(client, branch, base)
    return newest if newest is not None and newest.merged and newest.head_sha != tip else None


def continues_title(landed: PullRequest) -> str:
    """``<landed's title> (continues #N)``: a continuation of a continuation names its own predecessor alone."""
    return f'{_CONTINUES.sub("", landed.title)} (continues #{landed.number})'


def continues_body(landed: PullRequest, carried: str) -> str:
    """The continuation's body: what it continues, where its review starts, and what it carries."""
    said = (
        f'Continues #{landed.number}: `{landed.head}` landed at `{landed.head_sha[:12]}` there, and this PR carries '
        f'what was pushed onto it after. #{landed.number} stays the record of what was reviewed and tested at its '
        'head; this PR is reviewed for the increment from that head alone.'
    )
    return f'{said}\n\n{carried}' if carried else said


def open_continuation(client: Client, landed: PullRequest, *, reviewers: Sequence[str] = ()) -> PullRequest:
    """Open the continuation of merged *landed* from its branch and chain both in the branch's review record.

    Its body carries what the chain's reviews found (:func:`~dev_lab.dev.branchreview.context`) as it stands at
    the opening; the review re-reads it when it runs. *reviewers* are the declared review producers' logins.
    """
    record = chained(client, landed.head, landed.number)
    carry = carried_after(client, record, record.prs, reviewers)
    body = continues_body(landed, context(carry) if carry else '')
    pull = client.pr_create(continues_title(landed), body, head=landed.head, base=landed.base, draft=False)
    chained(client, landed.head, pull.number)
    return pull


def candidates(root: Path, *, integration: str, trunk: str, open_heads: frozenset[str]) -> dict[str, str]:
    """``{branch: tip}`` of every origin branch that may continue a landed PR, read from fetched refs alone.

    Not the integration branch or the trunk, no open PR has it, and neither of them contains its tip.
    """
    listed = git_out(root, 'for-each-ref', '--format=%(refname)%09%(objectname)', _ORIGIN)
    if listed is None:
        msg = f'git could not list the origin refs of {root}; nothing was judged'
        raise OSError(msg)
    holders = [f'{_ORIGIN}{name}' for name in (integration, trunk) if name]
    out: dict[str, str] = {}
    for line in listed.splitlines():
        ref, sha = line.split('\t')
        name = ref.removeprefix(_ORIGIN)
        if name in {integration, trunk, 'HEAD'} or name in open_heads:
            continue
        if any(git_out(root, 'merge-base', '--is-ancestor', sha, holder) is not None for holder in holders):
            continue
        out[name] = sha
    return out


def continue_landed(
    client: Client, branches: Mapping[str, str], *, integration: str, say: Callable[[str], None],
    reviewers: Sequence[str] = (),
) -> tuple[PullRequest, ...]:  # fmt: skip
    """Open the continuation of every one of *branches* (``{branch: tip}``) whose newest PR merged; those opened."""
    opened = []
    for branch, tip in sorted(branches.items()):
        landed = continuation(client, branch, integration, tip)
        if landed is None:
            continue
        pull = open_continuation(client, landed, reviewers=reviewers)
        say(f'[forge] {branch}: #{pull.number} continues #{landed.number} '
            f'(landed {landed.head_sha[:12]}, tip {tip[:12]})')  # fmt: skip
        opened.append(pull)
    return tuple(opened)


def serve_continue_landed(
    root: Path, client: Client, *, say: Callable[[str], None], alarm: Callable[[Alarm], object]
) -> None:
    """The serve tick's step: :func:`continue_landed` over :func:`candidates`; a failure only alarms."""
    try:
        policy = load_policy(root)
        heads = frozenset(pr.head for pr in pr_list(client))
        found = candidates(root, integration=policy.integration, trunk=policy.trunk, open_heads=heads)
        reviewers = review_at(root, policy.integration).reviewers
        continue_landed(client, found, integration=policy.integration, say=say, reviewers=reviewers)
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        alarm(Alarm(PRUNED, client.forge.repo, 'opening continuation pull requests failed', str(failed)))


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge pr continue [--head <branch> --sha <sha>]``: continue one pushed branch, or every candidate."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge pr continue', description=main.__doc__)
    parser.add_argument('--head', help='the pushed branch (default: every candidate in the fetched origin refs)')
    parser.add_argument('--sha', help="the pushed tip (required with --head: a CI checkout's refs are not origin's)")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if bool(args.head) != bool(args.sha):
        parser.error('--head and --sha go together')
    root = Path.cwd() if cwd is None else cwd
    try:
        policy = load_policy(root)
        if git_out(root, 'ls-tree', '--name-only', f'origin/{policy.integration}', '--', 'pyproject.toml') == '':
            emit(
                f'[forge] pr continue: origin/{policy.integration} declares nothing (first adoption); nothing continues'
            )
            return 0
        forge = client or client_for(root)
        if args.head:
            if args.head in {policy.integration, policy.trunk}:
                emit(f'[forge] pr continue: {args.head} is the integration branch or the trunk; nothing continues')
                return 0
            found = {args.head: args.sha}
        else:
            heads = frozenset(pr.head for pr in pr_list(forge))
            found = candidates(root, integration=policy.integration, trunk=policy.trunk, open_heads=heads)
        reviewers = review_at(root, policy.integration).reviewers
        opened = continue_landed(forge, found, integration=policy.integration, say=emit, reviewers=reviewers)
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        emit(f'[forge] pr continue: {failed}', err=True)
        return 2
    if not opened:
        emit('[forge] pr continue: no branch continues a merged PR')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
