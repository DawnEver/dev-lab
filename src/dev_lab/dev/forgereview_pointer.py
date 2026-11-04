"""WHERE THE JUDGE'S BUNDLE COMES FROM: never from anything a PR-head job can write.

The bundle review (:mod:`~dev_lab.dev.forgereview_bundle`) splits here: one side prepares the bundle, the other
reads it only from a source the judge locates itself (D3, F-680a6bd606f0). TWO sources, and no third:

* THE BASE'S PREPARE RUN (Gitea). The judge lists the runs at the head itself
  (:func:`~dev_lab.dev.reviewgate.review_runs`): event ``pull_request_target``, path
  ``<PREPARE_WORKFLOW>@refs/pull/<n>/head`` -- the base's workflow, run for THIS pull request, which a PR head can
  neither start nor alter -- and CREATED AFTER the PR's last base change in the forge's issue timeline
  (``change_target_branch`` / ``base_ref_changed``): a PR first opened into a branch whose workflow its author
  wrote, then retargeted, keeps that run under the same ref, so it is never a source; a timeline that cannot be
  read approves nothing. Gitea's run has no creation time, so a FIRST attempt's ``started_at`` stands for it and a
  re-run (it keeps the old workflow under a fresh start) never counts after a retarget. The newest such run that
  concluded decides, and only a ``success`` is read: a failed or cancelled run is no source, and a run still
  going decides nothing. The bundle is that run's OWN artifact
  :data:`ARTIFACT` (:func:`~dev_lab.dev.actionsartifact.run_member`), which only a job of that run can upload
  (its runtime token is scoped to it); no commit status, no URL and no store key is consulted. A PR-head workflow
  can post any status naming any run, and write to any store the job token reaches -- none of it is read.
* A DECLARED PREPARER (``[tool.dev_lab.review] preparers``): a login the integration branch names, whose
  :data:`BUNDLE_CONTEXT` status the forge records as written by it -- an identity no Actions job is given (the
  declaration refuses the Actions bot, and a Gitea job's status has a null creator). Its pointer names a store
  :class:`~dev_lab.dev.artefacts.Ref` the judge reads only when BOUND (:func:`bound_ref`) to the head and digest,
  never above :data:`MAX_ARCHIVE_BYTES`, and only :data:`BUNDLE_FILE` out of it, never above
  :data:`MAX_BUNDLE_BYTES`.

Every other pointer is logged and ignored -- on GitHub too, where a same-repository branch's workflow posts as the
Actions bot: no rendered workflow prepares there, so a bot pointer is never a source.

PREPARE (:func:`prepare`) holds no reviewer token. Inside a Gitea Actions job it attaches the bundle to its own run
as :data:`ARTIFACT` and posts nothing; on a preparer's host it uploads through the artefact store the BASE declares
(:func:`~dev_lab.dev.artefacts.store_for` over ``origin/<base>``'s manifest -- the head is data and never chooses)
and points the head at it (:func:`pointer`). The workflow is the base's ``_prepare`` table, which
:mod:`~dev_lab.dev.ciworkflows` renders for every ``where = "judge"`` repo.
"""

from __future__ import annotations

import os
import tarfile
import tempfile
import urllib.parse
import zlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import reviewbundle
from dev_lab.dev._forgebackends import GITHUB
from dev_lab.dev.actionsartifact import ArtifactRefused, run_member, upload
from dev_lab.dev.artefacts import (
    ARCHIVE,
    ATTACHMENT_LIMIT_MB,
    FORGE,
    ArtefactRefused,
    Ref,
    check_key,
    config_from,
    object_key,
    pack,
    resolve,
    run_id,
    store_for,
)
from dev_lab.dev.artefactstores import MB, parsed_run_id
from dev_lab.dev.forgepulls import pages
from dev_lab.dev.forgereview_declared import JUDGE, Review, base_manifest, review_from
from dev_lab.dev.forgestatus import status_history, status_post
from dev_lab.dev.reviewbundle import BundleRefused
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW, RunsUnread, review_runs

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'ARTIFACT',
    'BUNDLE_CONTEXT',
    'BUNDLE_FILE',
    'MAX_ARCHIVE_BYTES',
    'MAX_BUNDLE_BYTES',
    'bound_ref',
    'bundle_at',
    'pointer',
    'prepare',
    'ref_of_pointer',
    'trusted_bundle',
]

#: The artifact the base's prepare run attaches the bundle to, on its own run.
ARTIFACT: Final = 'review-bundle'

#: A base-branch change in an issue timeline: Gitea's ``type``, GitHub's ``event``.
_BASE_CHANGED: Final = frozenset({'change_target_branch', 'base_ref_changed'})

#: The commit status naming a head's prepared bundle: description the digest, target URL the store's Ref.
BUNDLE_CONTEXT: Final = 'review/bundle'

#: The one member of a bundle's archive the judge reads.
BUNDLE_FILE: Final = 'bundle.json'

#: The largest archive the judge fetches: the forge attachment limit, the store a bundle goes to by default.
MAX_ARCHIVE_BYTES: Final = ATTACHMENT_LIMIT_MB * MB

#: The largest ``bundle.json`` the judge reads out of an archive: a gzip bomb stops here.
MAX_BUNDLE_BYTES: Final = 4 * MAX_ARCHIVE_BYTES

#: The run-id ``platform`` of a bundle's archive (:func:`~dev_lab.dev.artefacts.run_id`).
_PLATFORM: Final = 'review'

#: How many hex digits of the digest name the archive (the run id's ``account``).
_DIGEST_ID: Final = 16

_SCHEME: Final = 'artefact'


def pointer(ref: Ref) -> str:
    """*ref* as a preparer's status target URL: ``artefact:?backend=..&ref=..``."""
    return f'{_SCHEME}:?{urllib.parse.urlencode(ref.manifest())}'


def _fields(url: str) -> dict[str, str]:
    scheme, _, query = url.partition(':?')
    if scheme != _SCHEME:
        return {}
    return {key: values[0] for key, values in urllib.parse.parse_qs(query).items()}


def ref_of_pointer(url: str) -> Ref:
    """The :class:`Ref` a :func:`pointer` names; anything else is :class:`BundleRefused`."""
    try:
        return Ref.of(_fields(url))
    except (KeyError, ValueError):
        msg = f'the {BUNDLE_CONTEXT} status names no artefact Ref: {url[:200]!r}'
        raise BundleRefused(msg) from None


def bound_ref(ref: Ref, *, repo: str, head: str, digest: str) -> None:
    """Refuse *ref* unless it is the key THIS judge derives for *head*'s bundle of *digest*, and small enough.

    The run id is ``<head12>-review-<digest16>-<stamp>``; the key is that id's archive in the store's own layout
    (flat on the forge, ``<repo>/<yyyy>/<mm>/<dd>/`` elsewhere). Nothing else -- no other path, no other head --
    is ever fetched.
    """
    ident = PurePosixPath(ref.key).name.removesuffix(ARCHIVE)
    try:
        parsed = parsed_run_id(ident)
        expected = ident + ARCHIVE if ref.backend == FORGE else object_key(repo, ident) + ARCHIVE
        check_key(expected)
    except ArtefactRefused as bad:
        raise BundleRefused(str(bad)) from None
    named = (parsed['sha'], parsed['platform'], parsed['account'])
    wanted = (head[:12], _PLATFORM, digest.removeprefix('sha256:')[:_DIGEST_ID])
    if named != wanted or ref.key != expected:
        msg = f'the {BUNDLE_CONTEXT} Ref {ref.backend}:{ref.key[:200]!r} is not the bundle of {head[:12]} {digest[:19]}'
        raise BundleRefused(msg)
    if not 0 < ref.bytes <= MAX_ARCHIVE_BYTES:
        msg = f'the {BUNDLE_CONTEXT} archive claims {ref.bytes} bytes; the judge reads 1..{MAX_ARCHIVE_BYTES}'
        raise BundleRefused(msg)


def prepare(
    root: Path, client: Client, number: int, *,
    env: Mapping[str, str] | None = None, now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:  # fmt: skip
    """Build PR *number*'s bundle from *root* (a clone holding its head) and publish it; the line.

    Inside a Gitea Actions job (*env*, default the process's) it becomes this run's :data:`ARTIFACT` and nothing is
    posted: the judge finds the run itself. Anywhere else -- a declared preparer's host -- it goes to the artefact
    store ``origin/<base>`` declares (the head is DATA and never chooses) and the head is pointed at it.
    Refused unless ``origin/<base>`` declares ``where = "judge"``: a ``serve`` repo has no judge to read it (the
    judge re-reads the declaration from the forge, so this is a courtesy, never the check).
    """
    env = os.environ if env is None else env
    pull = client.pr_view(number)
    manifest = base_manifest(root, pull.base)
    if review_from(*manifest).where != JUDGE:
        msg = f'#{number}: the base does not declare [tool.dev_lab.review] where = "{JUDGE}": no judge reads it'
        raise BundleRefused(msg)
    bundle = reviewbundle.prepare(root, repo=client.forge.repo, pull=pull)
    data, digest = reviewbundle.dump(bundle)
    said = f'#{number} {pull.head_sha[:12]}: bundle {digest[:19]}'
    if env.get('GITEA_ACTIONS') == 'true':
        try:
            artifact = upload(ARTIFACT, {BUNDLE_FILE: data}, env=env)
        except ArtifactRefused as refused:
            raise BundleRefused(str(refused)) from None
        return f'{said} attached to this run as artifact {ARTIFACT} ({artifact})'
    with tempfile.TemporaryDirectory(prefix='review-bundle-') as scratch:
        tree = Path(scratch) / 'tree'
        tree.mkdir()
        (tree / BUNDLE_FILE).write_bytes(data)
        archive = pack(tree, [tree / BUNDLE_FILE], Path(scratch) / f'bundle{ARCHIVE}')
        store = store_for(config_from(*manifest), client, client.forge.repo, size=archive.stat().st_size)
        ident = run_id(pull.head_sha, _PLATFORM, digest.removeprefix('sha256:')[:_DIGEST_ID], now())
        ref = store.put(ident, archive)
    target = pointer(ref)
    status_post(client, pull.head_sha, context=BUNDLE_CONTEXT, state='success', description=digest, target_url=target)
    return f'{said} stored as {ref.backend}:{ref.key}'


def _when(stamp: object) -> datetime:
    """An aware forge timestamp; anything else is :class:`~dev_lab.dev.reviewgate.RunsUnread` (never a pass)."""
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        when = None
    if when is None or when.tzinfo is None:
        msg = f'the forge answered no timestamp: {str(stamp)[:40]!r}'
        raise RunsUnread(msg)
    return when


def _base_changed(client: Client, number: int) -> datetime | None:
    """When PR *number*'s base branch last changed, from the forge's issue timeline; ``None`` when it never did."""
    events = pages(client, f'{client.repo}/issues/{number}/timeline', {})
    changed = [
        _when(event.get('created_at')) for event in events
        if isinstance(event, dict) and (event.get('type') or event.get('event')) in _BASE_CHANGED
    ]  # fmt: skip
    return max(changed, default=None)


def _created(run: Mapping[str, object]) -> datetime:
    """When *run* was created: ``created_at`` (GitHub), else a FIRST attempt's ``started_at`` (Gitea).

    Gitea's run carries no creation time, and a re-run keeps the run -- and the workflow it was started from --
    under a fresh start time, so a later attempt's start proves nothing: it reads as the epoch.
    """
    if run.get('created_at'):
        return _when(run['created_at'])
    if int(str(run.get('run_attempt') or 1)) > 1:
        return datetime.min.replace(tzinfo=UTC)
    return _when(run.get('started_at'))


def _prepared_by_run(client: Client, pull: PullRequest) -> reviewbundle.Bundle | None:
    """The bundle the base's newest CONCLUDED prepare run of *pull* attached to itself, when it succeeded."""
    since = _base_changed(client, pull.number)
    runs = [
        run for run in review_runs(client, pull.head_sha, workflow=PREPARE_WORKFLOW, pull=pull.number)
        if since is None or _created(run) > since
    ]  # fmt: skip
    concluded = next((run for run in runs if run.get('conclusion')), None)
    if concluded is None:
        return None
    if concluded.get('conclusion') != 'success':
        emit(f'[review] #{pull.number}: prepare run {concluded.get("id")} {concluded.get("conclusion")}: no bundle')
        return None
    try:
        data = run_member(
            client, int(concluded['id']), artifact=ARTIFACT, member=BUNDLE_FILE,
            limit=MAX_ARCHIVE_BYTES, member_limit=MAX_BUNDLE_BYTES,
        )  # fmt: skip
    except ArtifactRefused as refused:
        raise BundleRefused(str(refused)) from None
    return None if data is None else reviewbundle.load(data, reviewbundle.digest_of(data))


def _preparer_pointer(client: Client, review: Review, pull: PullRequest) -> CommitStatus | None:
    """The latest :data:`BUNDLE_CONTEXT` ``success`` on *pull*'s head a declared preparer wrote; ``None`` when none.

    Read over the head's whole history (:func:`~dev_lab.dev.forgestatus.status_history`), newest first, so another
    poster's pointer -- logged and skipped -- never shadows a preparer's.
    """
    for one in reversed(status_history(client, pull.head_sha)):
        if one.context != BUNDLE_CONTEXT:
            continue
        if one.creator in review.preparers and one.state == 'success':
            return one
        emit(f'[review] #{pull.number}: ignored a {BUNDLE_CONTEXT} pointer by {one.creator or "a null creator"}')
    return None


def trusted_bundle(client: Client, review: Review, pull: PullRequest, scratch: Path) -> reviewbundle.Bundle | None:
    """*pull*'s head's bundle from a TRUSTED source (module docstring), loaded; ``None`` while there is none.

    Raises:
        BundleRefused: the trusted source holds a bad bundle (too large, unreadable, malformed, unbound).

    """
    if client.backend is not GITHUB and (bundle := _prepared_by_run(client, pull)) is not None:
        return bundle
    found = _preparer_pointer(client, review, pull)
    return None if found is None else bundle_at(client, pull, found, scratch)


def _member(archive: Path) -> bytes:
    """:data:`BUNDLE_FILE`'s bytes out of *archive*, capped; anything else in it is never extracted."""
    try:
        with tarfile.open(archive, mode='r:gz') as tar:
            member = tar.getmember(BUNDLE_FILE)
            if not member.isfile() or member.size > MAX_BUNDLE_BYTES:
                msg = f'{BUNDLE_FILE} is no regular file of at most {MAX_BUNDLE_BYTES} bytes'
                raise BundleRefused(msg)
            read = tar.extractfile(member)
            data = read.read(MAX_BUNDLE_BYTES + 1) if read is not None else b''
    except (KeyError, tarfile.TarError, EOFError, zlib.error) as bad:
        msg = f'the bundle archive cannot be read: {type(bad).__name__}: {bad}'
        raise BundleRefused(msg) from None
    if len(data) != member.size:
        msg = f'{BUNDLE_FILE} is not the {member.size} bytes its archive says'
        raise BundleRefused(msg)
    return data


def bundle_at(client: Client, pull: PullRequest, found: CommitStatus, scratch: Path) -> reviewbundle.Bundle:
    """The bundle the trusted pointer *found* names, read and loaded; :class:`BundleRefused` if it is bad."""
    ref = ref_of_pointer(found.url)
    bound_ref(ref, repo=client.forge.repo, head=pull.head_sha, digest=found.description)
    archive = resolve(ref.manifest(), scratch / 'fetched', client=client, repo=client.forge.repo)
    return reviewbundle.load(_member(archive), found.description)
