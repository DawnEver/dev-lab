"""The run's own artifact: written with the job's runtime token, read as one capped member of one named artifact.

PLANTED CONTROLS: a well-formed upload makes the four v4 calls in order, scoped to the run and job the token names,
and the member it zipped reads back; against it a token naming no scope, a refused RPC, two artifacts of one name,
an oversized archive or member, a missing member and a non-zip are each refused, and a run holding none is ``None``.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from dev_lab.dev.actionsartifact import TWIRP, ArtifactRefused, run_member, upload, zipped

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.forgework import Client


def _token(scope: str) -> str:
    claims = base64.urlsafe_b64encode(json.dumps({'scp': scope}).encode()).decode().rstrip('=')
    return f'e30.{claims}.sig'


_ENV = {
    'ACTIONS_RUNTIME_TOKEN': _token('Actions.Runner:1:2 Actions.Results:41:42'),
    'ACTIONS_RUNTIME_URL': 'https://forge.local/api/actions_pipeline/',
}


class Wire:
    """The forge's results service: records each exchange, answers each RPC."""

    def __init__(self, *, ok: bool = True) -> None:
        """*ok*: whether each RPC answers ok."""
        self.sent: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.ok = ok

    def __call__(self, method: str, url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        self.sent.append((method, url, body, dict(headers)))
        if url.endswith('CreateArtifact'):
            return json.dumps({'ok': self.ok, 'signedUploadUrl': 'https://forge.local/up?sig=s'}).encode()
        if url.endswith('FinalizeArtifact'):
            return json.dumps({'ok': self.ok, 'artifactId': '77'}).encode()
        return b''


def test_an_upload_is_scoped_to_its_own_run_and_job_and_reads_back() -> None:
    wire = Wire()
    assert upload('review-bundle', {'bundle.json': b'{}'}, env=_ENV, send=wire) == '77'
    (create, block, listing, final) = wire.sent
    root = 'https://forge.local/' + TWIRP
    assert [(one[0], one[1].split('?')[0]) for one in wire.sent] == [
        ('POST', root + 'CreateArtifact'), ('PUT', 'https://forge.local/up'),
        ('PUT', 'https://forge.local/up'), ('POST', root + 'FinalizeArtifact'),
    ]  # fmt: skip
    assert create[3]['Authorization'] == f'Bearer {_ENV["ACTIONS_RUNTIME_TOKEN"]}'
    ids = json.loads(create[2])
    assert (ids['workflowRunBackendId'], ids['workflowJobRunBackendId'], ids['name']) == ('41', '42', 'review-bundle')
    assert 'comp=block&blockid=' in block[1]
    assert 'comp=blocklist' in listing[1]
    assert json.loads(final[2])['size'] == str(len(block[2]))
    forge = Forge({1: [{'id': 5, 'name': 'review-bundle', 'size_in_bytes': len(block[2])}]}, {5: block[2]})
    client = cast('Client', forge)
    assert run_member(client, 1, artifact='review-bundle', member='bundle.json', limit=10**6, member_limit=10) == b'{}'


@pytest.mark.parametrize(
    'env', [{**_ENV, 'ACTIONS_RUNTIME_TOKEN': _token('Actions.Runner:1:2')}, {**_ENV, 'ACTIONS_RUNTIME_TOKEN': 'x'}]
)
def test_a_token_naming_no_results_scope_writes_nothing(env: dict[str, str]) -> None:
    wire = Wire()
    with pytest.raises(ArtifactRefused, match='scope'):
        upload('a', {'f': b''}, env=env, send=wire)
    assert wire.sent == []


def test_a_refused_rpc_is_refused() -> None:
    with pytest.raises(ArtifactRefused, match='CreateArtifact'):
        upload('a', {'f': b''}, env=_ENV, send=Wire(ok=False))


class Forge:
    repo = '/api/v1/repos/o/r'

    def __init__(self, listed: dict[int, list[dict[str, Any]]], blobs: dict[int, bytes]) -> None:
        """Run id to its artifact rows, and artifact id to its zip."""
        self.listed, self.blobs, self.downloaded = listed, blobs, []

    def call(self, method: str, path: str) -> dict[str, Any]:
        assert method == 'GET'
        return {'artifacts': self.listed[int(path.split('/')[-2])]}

    def download(self, url: str) -> bytes:
        ident = int(url.split('/')[-2])
        self.downloaded.append(ident)
        return self.blobs[ident]


def _read(
    rows: list[dict[str, Any]], blob: bytes = b'', *, limit: int = 1000, member_limit: int = 1000
) -> bytes | None:
    forge = Forge({1: rows}, {5: blob})
    client = cast('Client', forge)
    return run_member(client, 1, artifact='b', member='bundle.json', limit=limit, member_limit=member_limit)


def test_a_run_holding_no_unexpired_artifact_of_the_name_holds_none() -> None:
    assert _read([]) is None
    assert _read([{'id': 5, 'name': 'other', 'size_in_bytes': 1}]) is None
    assert _read([{'id': 5, 'name': 'b', 'size_in_bytes': 1, 'expired': True}]) is None


@pytest.mark.parametrize(
    ('rows', 'blob', 'caps', 'match'),
    [
        (
            [{'id': 5, 'name': 'b', 'size_in_bytes': 1}, {'id': 6, 'name': 'b', 'size_in_bytes': 1}],
            b'',
            {},
            'undecided',
        ),
        ([{'id': 5, 'name': 'b', 'size_in_bytes': 5000}], b'', {}, 'claims'),
        ([{'id': 5, 'name': 'b', 'size_in_bytes': 1}], b'x' * 2000, {}, 'downloaded'),
        (
            [{'id': 5, 'name': 'b', 'size_in_bytes': 1}],
            zipped({'bundle.json': b'x' * 50}),
            {'member_limit': 10},
            'at most',
        ),
        ([{'id': 5, 'name': 'b', 'size_in_bytes': 1}], zipped({'other': b'{}'}), {}, 'cannot be read'),
        ([{'id': 5, 'name': 'b', 'size_in_bytes': 1}], b'not a zip', {}, 'cannot be read'),
    ],
)
def test_anything_but_one_capped_member_of_one_artifact_is_refused(
    rows: list[dict[str, Any]], blob: bytes, caps: dict[str, int], match: str
) -> None:
    with pytest.raises(ArtifactRefused, match=match):
        _read(rows, blob, **caps)
