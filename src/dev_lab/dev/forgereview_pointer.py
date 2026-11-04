"""THE BUNDLE POINTER: what ``forge review prepare`` writes on a PR head, and what the judge will believe of it.

The bundle review (:mod:`~dev_lab.dev.forgereview_bundle`) splits at this pointer: one side writes it, the
other trusts it only after deriving everything it can from the forge itself (D3).

* PREPARE (:func:`prepare`) runs where the PR's code may run and holds no reviewer token. It builds the
  :mod:`~dev_lab.dev.reviewbundle` of the PR head, uploads it through the artefact store the BASE declares
  (:func:`~dev_lab.dev.artefacts.store_for` over ``origin/<base>``'s manifest -- the head is data and never
  chooses), and posts ONE commit status on the head, :data:`BUNDLE_CONTEXT`: its description is the bundle's
  digest, its target URL the store's :class:`~dev_lab.dev.artefacts.Ref` and the run that prepared it
  (:func:`pointer`). The status is a POINTER, never a credential.
* READ (:func:`bundle_at`): only a Ref BOUND to that head and digest in the store layout the judge derives itself
  (:func:`bound_ref`), never above :data:`MAX_ARCHIVE_BYTES`, and only :data:`BUNDLE_FILE` out of it, never above
  :data:`MAX_BUNDLE_BYTES`.

WHO MAY POINT (:func:`trusted_pointer`): a declared ``preparers`` login, or the forge's CI identity -- on GitHub its
Actions bot; on Gitea, whose Actions statuses all carry a null creator, only a pointer naming a run of the BASE's
:data:`~dev_lab.dev.reviewgate.PREPARE_WORKFLOW` at this head (``pull_request_target``,
:func:`~dev_lab.dev.reviewgate.review_runs`), which a PR head can neither start nor alter. Every
other pointer is logged and ignored. RESIDUAL, on record: on GitHub a same-repository branch's own workflow posts
as the same bot; what it could point at is still verified by the judge. The workflow is the base's ``_prepare``
table, which :mod:`~dev_lab.dev.ciworkflows` renders for every ``where = "judge"`` repo.
"""

from __future__ import annotations

import tarfile
import tempfile
import urllib.parse
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import reviewbundle
from dev_lab.dev._forgebackends import GITHUB
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
from dev_lab.dev.forgereview_declared import JUDGE, Review, base_manifest, review_from
from dev_lab.dev.forgestatus import status_history, status_post
from dev_lab.dev.reviewbundle import BundleRefused
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW, github_posted, job_run_url, review_runs, run_path

if TYPE_CHECKING:
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'BUNDLE_CONTEXT',
    'BUNDLE_FILE',
    'MAX_ARCHIVE_BYTES',
    'MAX_BUNDLE_BYTES',
    'bound_ref',
    'bundle_at',
    'pointer',
    'prepare',
    'ref_of_pointer',
    'trusted_pointer',
]

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

_RUN_FIELD: Final = 'run'


def pointer(ref: Ref, *, run: str = '') -> str:
    """*ref* (and the *run* that prepared it) as the status's target URL: ``artefact:?backend=..&ref=..&run=..``."""
    fields = ref.manifest() | ({_RUN_FIELD: run} if run else {})
    return f'{_SCHEME}:?{urllib.parse.urlencode(fields)}'


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


def prepare(root: Path, client: Client, number: int, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> str:
    """Build PR *number*'s bundle from *root* (a clone holding its head), store it, point the head at it; the line.

    Refused unless ``origin/<base>`` declares ``where = "judge"``: a ``serve`` repo has no judge to read it (the
    judge re-reads the declaration from the forge, so this is a courtesy, never the check). The artefact store is
    the one ``origin/<base>`` declares too -- the head is DATA and never chooses where its bundle goes.
    """
    pull = client.pr_view(number)
    manifest = base_manifest(root, pull.base)
    if review_from(*manifest).where != JUDGE:
        msg = f'#{number}: the base does not declare [tool.dev_lab.review] where = "{JUDGE}": no judge reads it'
        raise BundleRefused(msg)
    bundle = reviewbundle.prepare(root, repo=client.forge.repo, pull=pull)
    data, digest = reviewbundle.dump(bundle)
    with tempfile.TemporaryDirectory(prefix='review-bundle-') as scratch:
        tree = Path(scratch) / 'tree'
        tree.mkdir()
        (tree / BUNDLE_FILE).write_bytes(data)
        archive = pack(tree, [tree / BUNDLE_FILE], Path(scratch) / f'bundle{ARCHIVE}')
        store = store_for(config_from(*manifest), client, client.forge.repo, size=archive.stat().st_size)
        ident = run_id(pull.head_sha, _PLATFORM, digest.removeprefix('sha256:')[:_DIGEST_ID], now())
        ref = store.put(ident, archive)
    target = pointer(ref, run=job_run_url(client))
    status_post(client, pull.head_sha, context=BUNDLE_CONTEXT, state='success', description=digest, target_url=target)
    return f'#{number} {pull.head_sha[:12]}: bundle {digest[:19]} stored as {ref.backend}:{ref.key}'


def trusted_pointer(client: Client, review: Review, pull: PullRequest) -> CommitStatus | None:
    """The latest :data:`BUNDLE_CONTEXT` status on *pull*'s head a TRUSTED poster wrote; ``None`` when none.

    Read over the head's whole history (:func:`~dev_lab.dev.forgestatus.status_history`), newest first, so an
    untrusted pointer -- logged and skipped -- never shadows a trusted one (module docstring: WHO MAY POINT).
    """
    owner, repo = client.forge.owner, client.forge.repo
    runs: list[frozenset[str]] = []

    def prepared_here(status: CommitStatus) -> bool:
        if client.backend is GITHUB:
            return github_posted(status)
        if status.creator != '':
            return False
        if not runs:
            listed = review_runs(client, pull.head_sha, workflow=PREPARE_WORKFLOW)
            runs.append(frozenset(path for one in listed if (path := run_path(one.get('html_url') or '', owner, repo))))
        named = run_path(_fields(status.url).get(_RUN_FIELD, ''), owner, repo)
        return bool(named) and named in runs[0]

    for one in reversed(status_history(client, pull.head_sha)):
        if one.context != BUNDLE_CONTEXT:
            continue
        if one.creator in review.preparers or prepared_here(one):
            return one
        emit(f'[review] #{pull.number}: ignored a {BUNDLE_CONTEXT} pointer by {one.creator or "a null creator"}')
    return None


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
