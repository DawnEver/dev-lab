"""THE BUNDLE REVIEW: ``forge review prepare`` on the runner, ``forge review judge`` on the isolated judge host.

A repo whose integration branch declares ``[tool.dev_lab.review] where = "judge"`` is reviewed this way, and only
this way (the serve skips it, :func:`dev_lab.dev.forgereview.review_pull`). User decisions 2026-11-03:

* PREPARE (:func:`prepare`) runs where the PR's code may run and holds no reviewer token. It builds the
  :mod:`~dev_lab.dev.reviewbundle` of the PR head, uploads it through the repo's artefact store
  (:func:`~dev_lab.dev.artefacts.store_for`), and posts ONE commit status on the head, :data:`BUNDLE_CONTEXT`:
  its description is the bundle's digest, its target URL the store's :class:`~dev_lab.dev.artefacts.Ref`
  (:func:`pointer`). The status is a POINTER, never a credential: whoever posts it, the judge trusts nothing in
  it that it does not verify itself.
* JUDGE (:func:`judge_pending`) runs on a host holding only its own forge token and model key. For each open,
  non-draft PR into the trusted integration branch whose head carries a pointer and no review of this identity
  yet (idempotent per head), it downloads the bundle, verifies it (:func:`~dev_lab.dev.reviewbundle.load`,
  :func:`~dev_lab.dev.reviewbundle.current`, :func:`~dev_lab.dev.reviewbundle.matches_forge` against the forge's
  own diff), reads the review declaration FRESH from the forge's integration branch (the bundle's copy is only
  cross-checked), runs the declared ``bundle`` command over plain files and posts a PR REVIEW as its own identity:
  ``APPROVED`` with no blocking finding, else ``REQUEST_CHANGES`` naming them. A bundle that fails verification is
  ``REQUEST_CHANGES`` naming why; a failure to READ (a forge call, a download, the command) posts nothing and is
  retried on the next run.

The forge's gate is that review (branch protection: one required approval from an allowlist naming the judge's
login); the judge's login needs PR write and code READ only -- it posts no status.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit

from dev_lab.dev import reviewbundle
from dev_lab.dev._forgebackends import GITHUB
from dev_lab.dev.artefacts import ARCHIVE, ArtefactRefused, Ref, load_config, pack, resolve, run_id, store_for, unpack
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pages, pr_list
from dev_lab.dev.forgereview_command import run_command
from dev_lab.dev.forgereview_declared import (
    JUDGE,
    Review,
    command_for,
    forge_integration,
    forge_review,
    review_from,
)
from dev_lab.dev.forgereview_findings import Findings, FindingsInvalid, parse_findings
from dev_lab.dev.forgereview_runtimes import host_runtimes
from dev_lab.dev.forgereview_scope import gather
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgetakeover import runtimes_with
from dev_lab.dev.forgework import client_for
from dev_lab.dev.reviewbundle import BundleRefused
from dev_lab.dev.reviewgate import DeclarationUnread

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'BUNDLE_CONTEXT',
    'BUNDLE_FILE',
    'DEFAULT_TOKEN_FILE',
    'Verdict',
    'judge_one',
    'judge_pending',
    'main',
    'pointer',
    'post_verdict',
    'prepare',
    'ref_of_pointer',
    'reviewed_by',
]

#: The commit status naming a head's prepared bundle: description the digest, target URL the store's Ref.
BUNDLE_CONTEXT: Final = 'review/bundle'

#: The one member of a bundle's archive.
BUNDLE_FILE: Final = 'bundle.json'

#: The run-id ``platform`` of a bundle's archive (:func:`~dev_lab.dev.artefacts.run_id`).
_PLATFORM: Final = 'review'

#: Where the judge's own forge token lives by default; ``--token-file`` names another.
DEFAULT_TOKEN_FILE: Final = Path('/etc/forge-bot/gitea-token')

_SCHEME: Final = 'artefact'
_APPROVE: Final = 'APPROVED'
_CHANGES: Final = 'REQUEST_CHANGES'
#: The review states a judge's verdict leaves, as each forge reports them back.
_VERDICT_STATES: Final = frozenset({'APPROVED', 'REQUEST_CHANGES', 'CHANGES_REQUESTED'})


def pointer(ref: Ref) -> str:
    """*ref* as the status's target URL: ``artefact:?backend=..&ref=..&bytes=..&sha256=..``."""
    return f'{_SCHEME}:?{urllib.parse.urlencode(ref.manifest())}'


def ref_of_pointer(url: str) -> Ref:
    """The :class:`Ref` a :func:`pointer` names; anything else is :class:`BundleRefused`."""
    scheme, _, query = url.partition(':?')
    fields = {key: values[0] for key, values in urllib.parse.parse_qs(query).items()}
    msg = f'the {BUNDLE_CONTEXT} status names no artefact Ref: {url[:200]!r}'
    if scheme != _SCHEME:
        raise BundleRefused(msg)
    try:
        return Ref.of(fields)
    except (KeyError, ValueError):
        raise BundleRefused(msg) from None


def prepare(root: Path, client: Client, number: int, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> str:
    """Build PR *number*'s bundle from *root* (a clone holding its head), store it, point the head at it; the line.

    Refused unless the bundle's own base declaration says ``where = "judge"``: a ``serve`` repo has no judge to
    read it (the judge re-reads the declaration from the forge, so this is a courtesy, never the check).
    """
    pull = client.pr_view(number)
    bundle = reviewbundle.prepare(root, repo=client.forge.repo, pull=pull, base=f'origin/{pull.base}')
    if review_from(bundle.declaration or '', f'{bundle.base_sha[:12]}:pyproject.toml').where != JUDGE:
        msg = f'#{number}: the base does not declare [tool.dev_lab.review] where = "{JUDGE}": no judge reads it'
        raise BundleRefused(msg)
    data, digest = reviewbundle.dump(bundle)
    with tempfile.TemporaryDirectory(prefix='review-bundle-') as scratch:
        tree = Path(scratch) / 'tree'
        tree.mkdir()
        (tree / BUNDLE_FILE).write_bytes(data)
        archive = pack(tree, [tree / BUNDLE_FILE], Path(scratch) / f'bundle{ARCHIVE}')
        store = store_for(load_config(root), client, client.forge.repo, size=archive.stat().st_size)
        ident = run_id(pull.head_sha, _PLATFORM, digest.removeprefix('sha256:')[:16], now())
        ref = store.put(ident, archive)
    status_post(
        client, pull.head_sha, context=BUNDLE_CONTEXT, state='success', description=digest, target_url=pointer(ref)
    )
    return f'#{number} {pull.head_sha[:12]}: bundle {digest[:19]} stored as {ref.backend}:{ref.key}'


@dataclass(frozen=True)
class Verdict:
    """What the judge posts on one head: the review event and its body."""

    event: str
    body: str


def reviewed_by(client: Client, pull: PullRequest, login: str) -> bool:
    """Whether *login* already left a verdict review on *pull*'s current head: the judge's idempotence."""
    for row in pages(client, f'{client.repo}/pulls/{pull.number}/reviews', {}):
        who = (row.get('user') or {}).get('login')
        if who == login and row.get('commit_id') == pull.head_sha and row.get('state') in _VERDICT_STATES:
            return True
    return False


def _bundle_of(client: Client, pull: PullRequest, scratch: Path) -> reviewbundle.Bundle | None:
    """The verified bundle the head's pointer names; ``None`` with no pointer. :class:`BundleRefused` if untrusted."""
    found = next((one for one in status_list(client, pull.head_sha) if one.context == BUNDLE_CONTEXT), None)
    if found is None or found.state != 'success':
        return None
    ref = ref_of_pointer(found.url)
    archive = resolve(ref.manifest(), scratch / 'fetched', client=client, repo=client.forge.repo)
    data = (unpack(archive, scratch / 'unpacked') / BUNDLE_FILE).read_bytes()
    bundle = reviewbundle.load(data, found.description)
    reviewbundle.current(bundle, pull, repo=client.forge.repo)
    reviewbundle.matches_forge(bundle, client.pull_diff(pull.number))
    return bundle


def _rendered(found: Findings, bundle: reviewbundle.Bundle, notes: Sequence[str]) -> Verdict:
    blocking = [one for one in found.findings if one.blocking]
    rest = [one for one in found.findings if not one.blocking]
    who = ', '.join(f'`{one.name}` ({one.provider or "-"}): {one.status}' for one in found.reviewers) or 'none'
    parts = [
        f'**Review** of `{bundle.head_sha[:12]}` over `{bundle.base_sha[:12]}..{bundle.head_sha[:12]}` (bundle)',
        f'Reviewers: {who}',
        *notes,
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


def judge_one(
    client: Client, review: Review, pull: PullRequest, *, runtimes: Mapping[str, Mapping[str, Any]],
    run: Callable[[Sequence[str], Path], str] = run_command,
) -> Verdict | str | None:  # fmt: skip
    """The verdict on *pull*'s head, a line when nothing can be posted yet (retried), ``None`` with no pointer."""
    with tempfile.TemporaryDirectory(prefix='review-judge-') as scratch:
        where = Path(scratch)
        try:
            bundle = _bundle_of(client, pull, where)
        except BundleRefused as refused:
            return Verdict(_CHANGES, f'**Review bundle refused** for `{pull.head_sha[:12]}`: {refused}')
        if bundle is None:
            return None
        notes = []
        try:
            same = review_from(bundle.declaration or '', 'the bundle') == review
        except ValueError:
            same = False
        if not same:
            notes.append("Note: the bundle's base declaration differs from the integration branch's; the latter ran.")
        reviewed = f'{bundle.base_sha}..{bundle.head_sha}'
        argv = command_for(review, reviewed, runtimes, bundle=True)

        def once(filled: Sequence[str], _root: Path) -> str:
            return reviewbundle.judge(bundle, filled, run=lambda final: run(final, where))

        try:
            found = parse_findings(gather(reviewed, [argv], (), once, where, pr_body=pull.body, disposed={}))
        except (OSError, FindingsInvalid) as failed:
            return f'#{pull.number} {pull.head_sha[:12]}: the review command failed, retried next run: {failed}'
    if not any(one.status in {'ok', 'skipped'} for one in found.reviewers):
        kinds = ', '.join(f'{one.name} {one.status}' for one in found.reviewers) or 'none planned'
        return f'#{pull.number} {pull.head_sha[:12]}: no reviewer returned findings ({kinds}); nothing posted'
    return _rendered(found, bundle, notes)


def post_verdict(client: Client, pull: PullRequest, verdict: Verdict) -> None:
    """Post *verdict* as a PR review on *pull*'s head, in the forge's own event spelling."""
    event = 'APPROVE' if client.backend is GITHUB and verdict.event == _APPROVE else verdict.event
    body = {'body': verdict.body, 'event': event, 'commit_id': pull.head_sha}
    client.call('POST', f'{client.repo}/pulls/{pull.number}/reviews', body)


def judge_pending(
    client: Client, *, runtimes: Mapping[str, Mapping[str, Any]],
    run: Callable[[Sequence[str], Path], str] = run_command,
) -> list[str]:  # fmt: skip
    """Judge every open head into the trusted integration branch that has a bundle and no verdict of ours; lines."""
    integration = forge_integration(client)
    review = forge_review(client, integration)
    if review.where != JUDGE:
        return [f'{integration} declares where = {review.where!r}: the judge reviews no PR of this repo']
    me = client.whoami()
    said = []
    for pull in pr_list(client):
        if pull.base != integration or pull.draft or not pull.head_sha or reviewed_by(client, pull, me):
            continue
        outcome = judge_one(client, review, pull, runtimes=runtimes, run=run)
        if isinstance(outcome, Verdict):
            post_verdict(client, pull, outcome)
            said.append(f'#{pull.number} {pull.head_sha[:12]}: {outcome.event}')
        elif outcome is not None:
            said.append(outcome)
    return said


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge review', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    making = verbs.add_parser('prepare', help="build a PR head's review bundle, store it, point the head at it")
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
