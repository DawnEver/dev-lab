"""THE BUNDLE REVIEW: ``forge review prepare`` on the runner, ``forge review judge`` on the isolated judge host.

A repo whose integration branch declares ``[tool.dev_lab.review] where = "judge"`` is reviewed this way, and only
this way (the serve skips it, :func:`dev_lab.dev.forgereview.review_pull`). User decisions 2026-11-03; the judge
trusts NOTHING the producer wrote that it can read or derive from the forge (D3):

* PREPARE writes a bundle; where it goes, and the only two sources the judge reads one from -- the base's prepare
  run's own artifact, or a declared preparer's bound pointer -- is :mod:`~dev_lab.dev.forgereview_pointer`.
* JUDGE (:func:`judge_pending`) runs on a host holding only its own forge token and model key, as the declared
  ``judge_login``. For each open, non-draft PR into the trusted integration branch whose head has a bundle from a
  TRUSTED source (:func:`~dev_lab.dev.forgereview_pointer.trusted_bundle`) and no standing verdict of this
  identity yet (idempotent per head):

  - it reads only the bundle that source holds, located by data the judge derives itself, never by a status;
  - it verifies the bundle (:func:`~dev_lab.dev.reviewbundle.load`, :func:`~dev_lab.dev.reviewbundle.current`
    against the FORGE's merge base, :func:`~dev_lab.dev.reviewbundle.matches_forge` against the forge's own diff);
  - it reads the declaration FRESH from the forge's integration branch, the disposals the forge records on the PR
    (:func:`~dev_lab.dev.forgereview_judge.upheld`), and hands the reviewer the FORGE's diff, never the producer's;
  - a binary change to a path the declaration calls code (:func:`~dev_lab.dev.forgereview_scope.is_code`) is
    ``REQUEST_CHANGES``: no reviewer can read it, so it is never approved unread;
  - it posts a PR REVIEW as its own identity: ``APPROVED`` only when every reviewer ran (``ok`` or ``skipped``,
    at least one ``ok``) and none found a blocking finding, ``REQUEST_CHANGES`` naming them otherwise.

  A bundle that fails verification -- a bad archive, a missing member, a malformed document -- is
  ``REQUEST_CHANGES`` naming why; a failure to READ (a forge call, a download, the command) posts nothing and is
  retried on the next run, and one PR's failure never stops the PRs after it.

The forge's gate is that review: dev-lab's merge, merge-ready and Break-Glass read the declared ``judge_login``'s
latest standing verdict at the head (:func:`~dev_lab.dev.forgereview_declared.review_gate`), and the forge's own
branch protection may require it too. The judge needs PR write and code READ only -- it posts no status.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit

from dev_lab.dev import reviewbundle
from dev_lab.dev._forgebackends import GITHUB
from dev_lab.dev.artefacts import (
    ArtefactRefused,
)
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pages, pr_list
from dev_lab.dev.forgereview_command import run_command
from dev_lab.dev.forgereview_declared import (
    JUDGE,
    Review,
    command_for,
    forge_integration,
    forge_review,
)
from dev_lab.dev.forgereview_findings import Findings, FindingsInvalid, parse_findings
from dev_lab.dev.forgereview_judge import upheld
from dev_lab.dev.forgereview_pointer import prepare, trusted_bundle
from dev_lab.dev.forgereview_rounds import trusted_bodies
from dev_lab.dev.forgereview_runtimes import host_runtimes
from dev_lab.dev.forgereview_scope import gather, is_code
from dev_lab.dev.forgetakeover import runtimes_with
from dev_lab.dev.forgework import client_for
from dev_lab.dev.reviewbundle import BundleRefused
from dev_lab.dev.reviewgate import (
    DeclarationUnread,
    standing_verdicts,
)

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'DEFAULT_TOKEN_FILE',
    'Verdict',
    'forge_merge_base',
    'judge_one',
    'judge_pending',
    'main',
    'post_verdict',
    'reviewed_by',
]

#: Where the judge's own forge token lives by default; ``--token-file`` names another.
DEFAULT_TOKEN_FILE: Final = Path('/etc/forge-bot/gitea-token')

_APPROVE: Final = 'APPROVED'
_CHANGES: Final = 'REQUEST_CHANGES'
_RAN: Final = frozenset({'ok', 'skipped'})

#: What a READ may fail with: posted as nothing, retried on the next run.
_UNREAD: Final = (ForgeCallFailed, ArtefactRefused, OSError, DeclarationUnread)


@dataclass(frozen=True)
class Verdict:
    """What the judge posts on one head: the review event and its body."""

    event: str
    body: str


def reviewed_by(client: Client, pull: PullRequest, login: str) -> bool:
    """Whether *login*'s verdict on *pull*'s current head stands (:func:`~dev_lab.dev.reviewgate.standing_verdicts`)."""
    rows = pages(client, f'{client.repo}/pulls/{pull.number}/reviews', {})
    return bool(standing_verdicts(rows, login=login, head=pull.head_sha))


def forge_merge_base(client: Client, pull: PullRequest) -> str:
    """The merge base the FORGE computes for *pull*: Gitea's ``merge_base``, GitHub's compare ``merge_base_commit``."""
    if client.backend is GITHUB:
        answer: Any = client.call('GET', f'{client.repo}/compare/{pull.base}...{pull.head_sha}')
        found = ((answer or {}).get('merge_base_commit') or {}).get('sha') if isinstance(answer, dict) else None
    else:
        answer = client.call('GET', f'{client.repo}/pulls/{pull.number}')
        found = answer.get('merge_base') if isinstance(answer, dict) else None
    if not found:
        msg = f'#{pull.number}: the forge names no merge base'
        raise OSError(msg)
    return str(found)


def _rendered(found: Findings, bundle: reviewbundle.Bundle) -> Verdict:
    blocking = [one for one in found.findings if one.blocking]
    rest = [one for one in found.findings if not one.blocking]
    who = ', '.join(f'`{one.name}` ({one.provider or "-"}): {one.status}' for one in found.reviewers) or 'none'
    parts = [
        f'**Review** of `{bundle.head_sha[:12]}` over `{bundle.base_sha[:12]}..{bundle.head_sha[:12]}` (bundle)',
        f'Reviewers: {who}',
    ]
    for title, rows in (('Blocking', blocking), ('Not blocking', rest)):
        if rows:
            lines = [
                f'- `{one.id}` **{one.severity}** {one.file}:{one.anchor} [{one.rule}] {one.summary}' for one in rows
            ]
            parts.append(f'### {title}\n' + '\n'.join(lines))
    if not found.findings:
        parts.append('No findings.')
    return Verdict(_CHANGES if blocking else _APPROVE, '\n\n'.join(parts))


def _unread_code(bundle: reviewbundle.Bundle, review: Review) -> Verdict | None:
    """``REQUEST_CHANGES`` naming every binary change to a declared code path: no reviewer can read it."""
    hidden = [one.path for one in bundle.files if one.binary and is_code(one.path, review.code, review.not_code)]
    if not hidden:
        return None
    named = '\n'.join(f'- `{path}`' for path in hidden)
    return Verdict(
        _CHANGES,
        f'**Unreadable code** in `{bundle.head_sha[:12]}`: these code paths hold a NUL, so no reviewer can read '
        f'them; make them text, or declare them `not_code` on the integration branch:\n{named}',
    )


def _verdict_of(out: Findings, bundle: reviewbundle.Bundle, said: str) -> Verdict | str:
    """The verdict on *out* only when every reviewer ran (``ok``/``skipped``, at least one ``ok``); else a line."""
    statuses = [one.status for one in out.reviewers]
    if not statuses or not set(statuses) <= _RAN or 'ok' not in statuses:
        kinds = ', '.join(f'{one.name} {one.status}' for one in out.reviewers) or 'none planned'
        return f'{said}: not every reviewer returned findings ({kinds}); nothing posted'
    return _rendered(out, bundle)


def judge_one(
    client: Client, review: Review, pull: PullRequest, *, runtimes: Mapping[str, Mapping[str, Any]],
    run: Callable[[Sequence[str], Path, Mapping[str, str]], str] = run_command,
) -> Verdict | str | None:  # fmt: skip
    """The verdict on *pull*'s head, a line when nothing can be posted yet (retried), ``None`` with no pointer."""
    said = f'#{pull.number} {pull.head_sha[:12]}'
    with tempfile.TemporaryDirectory(prefix='review-judge-') as scratch:
        where = Path(scratch)
        try:
            bundle = trusted_bundle(client, review, pull, where)
            if bundle is None:
                return None
            diff, merge_base = client.pull_diff(pull.number), forge_merge_base(client, pull)
            gone = upheld(trusted_bodies(client, pull.number, review.reviewers))
            reviewbundle.current(bundle, pull, repo=client.forge.repo, merge_base=merge_base)
            reviewbundle.matches_forge(bundle, diff)
        except BundleRefused as refused:
            return Verdict(_CHANGES, f'**Review bundle refused** for `{pull.head_sha[:12]}`: {refused}')
        except _UNREAD as failed:
            return f'{said}: the bundle or the forge could not be read, retried next run: {failed}'
        if (unread := _unread_code(bundle, review)) is not None:
            return unread
        reviewed = f'{bundle.base_sha}..{bundle.head_sha}'
        argv = command_for(review, reviewed, runtimes, bundle=True)

        def once(filled: Sequence[str], _root: Path) -> str:
            return reviewbundle.judge(bundle, filled, diff=diff, run=lambda final, env: run(final, where, env))

        try:
            out = parse_findings(gather(reviewed, [argv], (), once, where, pr_body=pull.body, disposed=gone))
        except (OSError, FindingsInvalid) as failed:
            return f'{said}: the review command failed, retried next run: {failed}'
    return _verdict_of(out, bundle, said)


def post_verdict(client: Client, pull: PullRequest, verdict: Verdict) -> None:
    """Post *verdict* as a PR review on *pull*'s head, in the forge's own event spelling."""
    event = 'APPROVE' if client.backend is GITHUB and verdict.event == _APPROVE else verdict.event
    body = {'body': verdict.body, 'event': event, 'commit_id': pull.head_sha}
    client.call('POST', f'{client.repo}/pulls/{pull.number}/reviews', body)


def judge_pending(
    client: Client, *, runtimes: Mapping[str, Mapping[str, Any]],
    run: Callable[[Sequence[str], Path, Mapping[str, str]], str] = run_command,
) -> list[str]:  # fmt: skip
    """Judge every open head into the trusted integration branch that has a bundle and no verdict of ours; lines.

    One PR's failure is its own line: the PRs after it are judged all the same.
    """
    integration = forge_integration(client)
    review = forge_review(client, integration)
    if review.where != JUDGE:
        return [f'{integration} declares where = {review.where!r}: the judge reviews no PR of this repo']
    me = client.whoami()
    if me != review.judge_login:
        return [f'{integration} declares judge_login = {review.judge_login!r}; this host is {me!r}: it judges nothing']
    said = []
    for pull in pr_list(client):
        if pull.base != integration or pull.draft or not pull.head_sha:
            continue
        try:
            if reviewed_by(client, pull, me):
                continue
            outcome = judge_one(client, review, pull, runtimes=runtimes, run=run)
            if isinstance(outcome, Verdict):
                post_verdict(client, pull, outcome)
                said.append(f'#{pull.number} {pull.head_sha[:12]}: {outcome.event}')
            elif outcome is not None:
                said.append(outcome)
        except (*_UNREAD, ValueError) as failed:
            said.append(f'#{pull.number} {pull.head_sha[:12]}: not judged, retried next run: {failed}')
    return said


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge review', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    making = verbs.add_parser('prepare', help="build a PR head's review bundle and publish it to the judge")
    making.add_argument('--pr', type=int, required=True)
    making.add_argument('--repo', type=Path, help='the clone holding the head (default: the working directory)')
    judging = verbs.add_parser('judge', help='review every prepared head as this host, posting PR reviews')
    judging.add_argument('--url', required=True, help="the repository's web URL (the judge holds no checkout)")
    judging.add_argument('--token-file', type=Path, default=DEFAULT_TOKEN_FILE, help='the judge token')
    judging.add_argument(
        '--runtime', action='append', default=[], metavar='NAME.KEY=VALUE',
        help="a [runtimes] value over this host's machine file, e.g. ai_lab.python=/opt/ai-lab/bin/python",
    )  # fmt: skip
    return parser


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge review prepare --pr N`` | ``forge review judge --url U``: exit 0 done, 2 refused."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    here = Path.cwd() if cwd is None else cwd
    try:
        if args.verb == 'prepare':
            root = args.repo or here
            emit(f'[review] {prepare(root, client or client_for(root), args.pr)}')
            return 0
        token = args.token_file.read_text(encoding='utf-8').strip() if client is None else ''
        judge = client or client_for(here, url=args.url, token=token)
        for line in judge_pending(judge, runtimes=runtimes_with(host_runtimes(), args.runtime)):
            emit(f'[review] {line}')
    except (BundleRefused, ArtefactRefused, DeclarationUnread, ForgeCallFailed, OSError, ValueError) as failed:
        emit(f'[review] refused: {failed}', err=True)
        return 2
    return 0
