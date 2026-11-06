"""THE RUN'S OWN ARTIFACT: a file only one Actions run can attach to itself, and what a reader takes out of it.

The forge binds an artifact to the run that uploaded it. The upload authenticates with the job's
``ACTIONS_RUNTIME_TOKEN``, which the runner hands that job alone and whose ``scp`` claim names the run and job it
writes for (``Actions.Results:<run>:<job>``); no other run -- a PR-head workflow included -- and no user's token can
add to or replace another run's artifacts. So bytes read from ``actions/runs/{id}/artifacts`` of a run the READER
chose are what that run wrote. A later delete can remove them, never forge them: the reader then finds none.

* :func:`upload` -- from inside a job: one zip of named members through the artifact v4 protocol the forge serves
  under :data:`TWIRP` (Gitea 1.22+, GitHub) -- CreateArtifact, the zip as one block, the block list,
  FinalizeArtifact with the zip's sha256. Every exchange is retried through the one forge loop
  (:func:`~dev_lab.dev.forgefailure.retried`): a 5xx, a dropped connection or a rate limit is tried again, a
  refusal is not, and a lost CreateArtifact answer retried is refused by the forge as a duplicate, never doubled.
* :func:`run_member` -- one member of the one unexpired artifact of a name in a run, the archive capped before and
  after download, the member capped, nothing else extracted.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgefailure import RATE_HEADERS, Answer, retried

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from email.message import Message

    from dev_lab.dev.forgework import Client

    #: One HTTP exchange: ``(method, url, body, headers) -> answer bytes``; a refusal raises :class:`OSError`.
    type Send = Callable[[str, str, bytes, Mapping[str, str]], bytes]

    #: One HTTP exchange as answered, a refusal included: ``(method, url, body, headers) -> Answer``.
    type Exchange = Callable[[str, str, bytes, Mapping[str, str]], Answer]

__all__ = ['TWIRP', 'ArtifactRefused', 'retrying', 'run_member', 'upload', 'zipped']

#: The artifact v4 service, under the forge's results URL.
TWIRP: Final = 'twirp/github.actions.results.api.v1.ArtifactService/'

#: The one block a small artifact is uploaded as (the block list names it again).
_BLOCK: Final = base64.b64encode(b'block-000000').decode()

#: Where act_runner points ``ACTIONS_RUNTIME_URL``: the instance root plus this.
_PIPELINE: Final = 'api/actions_pipeline/'

_SCOPE: Final = re.compile(r'Actions\.Results:(\d+):(\d+)')


class ArtifactRefused(ValueError):
    """An artifact cannot be written from here, or what a run holds is not one readable member within its cap."""


def _scope(token: str) -> tuple[str, str]:
    """The run and job the runtime *token* writes for, from its ``scp`` claim (the signature is the forge's check)."""
    try:
        claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=='))
    except (IndexError, ValueError, binascii.Error):
        claims = {}
    found = _SCOPE.search(str(claims.get('scp', '')) if isinstance(claims, dict) else '')
    if found is None:
        msg = 'ACTIONS_RUNTIME_TOKEN names no Actions.Results:<run>:<job> scope: no artifact can be written'
        raise ArtifactRefused(msg)
    return found.group(1), found.group(2)


def _results_url(env: Mapping[str, str]) -> str:
    url = env.get('ACTIONS_RESULTS_URL') or env.get('ACTIONS_RUNTIME_URL', '').removesuffix(_PIPELINE)
    if not url:
        msg = 'neither ACTIONS_RESULTS_URL nor ACTIONS_RUNTIME_URL is set: this is no Actions job'
        raise ArtifactRefused(msg)
    return url.rstrip('/') + '/'


def _urllib_once(method: str, url: str, body: bytes, headers: Mapping[str, str]) -> Answer:
    if urllib.parse.urlsplit(url).scheme not in {'http', 'https'}:
        msg = f'the artifact service named a non-HTTP URL: {url[:80]!r}'
        raise ArtifactRefused(msg)
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310
            return Answer(answer.status, answer.read(), _rate(answer.headers))
    except urllib.error.HTTPError as refused:
        return Answer(refused.code, refused.read(), _rate(refused.headers))


def _rate(headers: Message | None) -> dict[str, str]:
    """The :data:`RATE_HEADERS` an answer sent (a bare ``HTTPError`` may carry no headers)."""
    return {name: value for name in RATE_HEADERS if headers is not None and (value := headers.get(name))}


def retrying(exchange: Exchange, *, sleep: Callable[[float], None] = time.sleep) -> Send:
    """*exchange* as a :data:`Send` through the one forge retry loop; its last refusal raises ``ForgeCallFailed``.

    The report names the URL's path only: a signed upload URL's query is its credential.
    """

    def send(method: str, url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        label = (method, urllib.parse.urlsplit(url).path)
        answer = retried(label, lambda: exchange(method, url, body, headers), sleep=sleep)
        return answer.payload if isinstance(answer, Answer) else b''

    return send


def zipped(members: Mapping[str, bytes]) -> bytes:
    """*members* as one deflated zip, in name order: the artifact format both forges download."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            archive.writestr(name, members[name])
    return out.getvalue()


def upload(
    name: str, members: Mapping[str, bytes], *, env: Mapping[str, str] | None = None, send: Send | None = None
) -> str:
    """Attach *members* to THIS job's run as artifact *name*; the forge's artifact id."""
    env = os.environ if env is None else env
    send = retrying(_urllib_once) if send is None else send
    token = env.get('ACTIONS_RUNTIME_TOKEN', '')
    run, job = _scope(token)
    twirp = _results_url(env) + TWIRP
    auth = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    ids = {'workflowRunBackendId': run, 'workflowJobRunBackendId': job, 'name': name}

    def rpc(verb: str, body: dict[str, Any]) -> dict[str, Any]:
        answer = json.loads(send('POST', twirp + verb, json.dumps(body).encode(), auth) or b'{}')
        if not isinstance(answer, dict) or answer.get('ok') is not True:
            msg = f'{verb} of artifact {name!r} was refused: {str(answer)[:200]}'
            raise ArtifactRefused(msg)
        return answer

    data = zipped(members)
    signed = str(rpc('CreateArtifact', {**ids, 'version': 4}).get('signedUploadUrl') or '')
    if not signed:
        msg = f'CreateArtifact of {name!r} answered no signedUploadUrl'
        raise ArtifactRefused(msg)
    joined = signed + ('&' if '?' in signed else '?')
    blob = {'x-ms-blob-type': 'BlockBlob', 'Content-Type': 'application/octet-stream'}
    send('PUT', f'{joined}comp=block&blockid={urllib.parse.quote(_BLOCK)}', data, blob)
    listing = f'<?xml version="1.0" encoding="utf-8"?><BlockList><Latest>{_BLOCK}</Latest></BlockList>'
    send('PUT', f'{joined}comp=blocklist', listing.encode(), {'Content-Type': 'text/xml'})
    digest = f'sha256:{hashlib.sha256(data).hexdigest()}'
    return str(rpc('FinalizeArtifact', {**ids, 'size': str(len(data)), 'hash': digest}).get('artifactId') or '')


def run_member(client: Client, run: int, *, artifact: str, member: str, limit: int, member_limit: int) -> bytes | None:
    """*member* of run *run*'s artifact *artifact*, as the forge holds it; ``None`` when the run holds none.

    Raises:
        ArtifactRefused: two artifacts of the name, an archive over *limit* or a member over *member_limit*, a bad
            zip, no such member.
        OSError: the forge answered no list of the run's artifacts (a read failure, retried).

    """
    listed: Any = client.call('GET', f'{client.repo}/actions/runs/{run}/artifacts')
    rows = listed.get('artifacts') if isinstance(listed, dict) else None
    if not isinstance(rows, list):
        msg = f'the artifacts of run {run}: the forge answered no list'
        raise OSError(msg)
    named = [row for row in rows if row.get('name') == artifact and not row.get('expired')]
    if not named:
        return None
    if len(named) > 1:
        msg = f'run {run} holds {len(named)} artifacts named {artifact!r}: which one it wrote is undecided'
        raise ArtifactRefused(msg)
    (row,) = named
    if not 0 < int(row.get('size_in_bytes') or 0) <= limit:
        msg = f'artifact {artifact!r} of run {run} claims {row.get("size_in_bytes")} bytes; read are 1..{limit}'
        raise ArtifactRefused(msg)
    data = client.download(f'{client.repo}/actions/artifacts/{int(row["id"])}/zip')
    if len(data) > limit:
        msg = f'artifact {artifact!r} of run {run} downloaded {len(data)} bytes, over {limit}'
        raise ArtifactRefused(msg)
    return _member(data, member, member_limit)


def _member(data: bytes, member: str, limit: int) -> bytes:
    """*member*'s bytes out of zip *data*, capped at *limit*; nothing else in it is ever extracted."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(member)
            if info.is_dir() or info.file_size > limit:
                msg = f'{member} is no regular file of at most {limit} bytes'
                raise ArtifactRefused(msg)
            with archive.open(info) as read:
                out = read.read(limit + 1)
    except (KeyError, zipfile.BadZipFile, EOFError, ValueError) as bad:
        if isinstance(bad, ArtifactRefused):
            raise
        msg = f'the artifact cannot be read: {type(bad).__name__}: {bad}'
        raise ArtifactRefused(msg) from None
    if len(out) != info.file_size:
        msg = f'{member} is not the {info.file_size} bytes its archive says'
        raise ArtifactRefused(msg)
    return out
