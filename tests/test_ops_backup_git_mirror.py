"""The ``git_mirror`` dumper: every declared repository, on any forge, mirrored into a cache and bundled per repo."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from dev_lab.dev._forgebackends import GITEA
from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgework import Client
from dev_lab.ops.backup import BackupRefused, Dumper, export, git_mirror, metadata
from dev_lab.ops.config import Backup
from dev_lab.ops.config import mirror_name as slug

_GIT = shutil.which('git') or 'git'


def _git(*argv: str, cwd: Path | None = None) -> str:
    return subprocess.run([_GIT, *argv], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8').stdout


def _origin(tmp: Path, name: str) -> tuple[Path, Path]:
    """A bare repository *name* holding one commit, and the work tree that pushes to it."""
    bare, work = tmp / 'forge' / f'{name}.git', tmp / 'work' / name
    _git('init', '--bare', '-b', 'main', str(bare))
    _git('init', '-b', 'main', str(work))
    _commit(work, 'one')
    _git('remote', 'add', 'origin', str(bare), cwd=work)
    _git('push', 'origin', 'main', cwd=work)
    return bare, work


def _commit(work: Path, text: str) -> str:
    (work / 'f.txt').write_text(text, encoding='utf-8')
    _git('add', 'f.txt', cwd=work)
    _git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-m', text, cwd=work)
    return _git('rev-parse', 'HEAD', cwd=work).strip()


def _exported(role: Backup, **dumpers: Dumper) -> dict[str, bytes]:
    out = io.BytesIO()
    export(role, out, dumpers=dumpers or {'git_mirror': git_mirror()})
    with tarfile.open(fileobj=io.BytesIO(out.getvalue())) as archive:
        return {member.name: _read(archive, member) for member in archive.getmembers()}


def _read(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = archive.extractfile(member)
    assert extracted is not None
    return extracted.read()


def _heads(bundle: bytes, tmp: Path) -> str:
    path = tmp / 'check.bundle'
    path.write_bytes(bundle)
    return _git('bundle', 'list-heads', str(path), cwd=tmp)


def _role(tmp: Path, mirrors: tuple[str, ...], **more: object) -> Backup:
    return Backup(
        dumpers=('git_mirror',), tmp=str(tmp / 'tmp'), mirrors=mirrors, mirror_cache=str(tmp / 'cache'), **more
    )


def test_every_mirror_is_one_bundle_named_by_its_url(tmp_path: Path) -> None:
    (tmp_path / 'tmp').mkdir()
    one, _ = _origin(tmp_path, 'one')
    two, _ = _origin(tmp_path, 'two')
    files = _exported(_role(tmp_path, (str(one), str(two))))
    assert sorted(files) == sorted(f'{slug(str(url))}.bundle' for url in (one, two))
    assert 'refs/heads/main' in _heads(files[f'{slug(str(one))}.bundle'], tmp_path)


def test_the_cache_persists_and_a_second_export_carries_the_new_commit(tmp_path: Path) -> None:
    (tmp_path / 'tmp').mkdir()
    bare, work = _origin(tmp_path, 'one')
    role = _role(tmp_path, (str(bare),))
    _exported(role)
    assert (tmp_path / 'cache' / f'{slug(str(bare))}.git').is_dir()
    head = _commit(work, 'two')
    _git('push', 'origin', 'main', cwd=work)
    files = _exported(role)
    assert head in _heads(files[f'{slug(str(bare))}.bundle'], tmp_path)


def test_an_unreachable_mirror_refuses_the_export(tmp_path: Path) -> None:
    (tmp_path / 'tmp').mkdir()
    with pytest.raises(BackupRefused, match='exited'):
        _exported(_role(tmp_path, (str(tmp_path / 'missing.git'),)))


def test_slug_drops_scheme_and_credentials_and_keeps_host_owner_repo() -> None:
    assert slug('https://user:secret@forge.example/owner/name.git') == 'forge.example_owner_name'
    assert slug('git@forge.example:owner/name.git') == 'forge.example_owner_name'


def test_the_metadata_flag_adds_one_json_per_repo(tmp_path: Path) -> None:
    (tmp_path / 'tmp').mkdir()
    bare, _ = _origin(tmp_path, 'one')
    seen: list[tuple[str, str]] = []

    def meta(url: str, token: str) -> Mapping[str, Any]:
        seen.append((url, token))
        return {'pulls': []}

    files = _exported(_role(tmp_path, (str(bare),), mirror_metadata=True), git_mirror=git_mirror(meta=meta))
    assert json.loads(files[f'{slug(str(bare))}.meta.json']) == {'pulls': []}
    assert seen == [(str(bare), '')]


@pytest.mark.parametrize(
    ('kwargs', 'match'),
    [
        ({'mirrors': ()}, 'no mirror'),
        ({'mirror_cache': ''}, 'mirror_cache'),
        ({'mirrors': ('https://h/o/r.git', 'ssh://git@h/o/r.git')}, 'twice'),
        ({'mirror_tokens': {'other.host': '/t'}}, 'serves no mirror'),
    ],
)
def test_a_git_mirror_declaration_that_lies_is_refused(kwargs: dict[str, Any], match: str) -> None:
    values: dict[str, Any] = {'mirrors': ('https://h/o/r.git',), 'mirror_cache': '/c'} | kwargs
    with pytest.raises(ValueError, match=match):
        Backup(dumpers=('git_mirror',), **values)


@dataclass
class _Forge:
    """A forge answering GET paths from a table; every listing fits one page."""

    answers: Mapping[str, Any]
    backend: Any = GITEA
    repo: str = '/api/v1/repos/o/r'
    asked: list[str] = field(default_factory=list)

    def call(self, method: str, path: str) -> object:
        assert method == 'GET'
        self.asked.append(path)
        return self.answers[path.partition('?')[0]]


def test_metadata_reads_pulls_reviews_statuses_and_issues() -> None:
    forge = _Forge(
        {
            '/api/v1/repos/o/r/pulls': [{'number': 7, 'head': {'sha': 'abc'}}],
            '/api/v1/repos/o/r/pulls/7/reviews': [{'id': 1}],
            '/api/v1/repos/o/r/commits/abc/statuses': [{'state': 'success'}],
            '/api/v1/repos/o/r/issues': [{'number': 3}],
        }
    )
    assert metadata(cast('Client', forge)) == {
        'pulls': [{'number': 7, 'head': {'sha': 'abc'}, 'reviews': [{'id': 1}], 'statuses': [{'state': 'success'}]}],
        'issues': [{'number': 3}],
    }
    listings = [
        path for path in forge.asked if path.endswith(('pulls', 'issues')) or '/pulls?' in path or '/issues?' in path
    ]
    assert listings
    assert all('state=all' in path for path in listings)


class _Answer:
    status = 200

    def getheader(self, _name: str) -> None:
        return None

    def read(self) -> bytes:
        return b'[]'


@dataclass
class _Connection:
    headers: list[Mapping[str, str]]

    def request(self, _method: str, _path: str, *, body: object, headers: Mapping[str, str]) -> None:
        assert body is None
        self.headers.append(headers)

    def getresponse(self) -> _Answer:
        return _Answer()

    def close(self) -> None:
        pass


def test_a_client_without_a_token_reads_anonymously() -> None:
    sent: list[Mapping[str, str]] = []
    client = Client(forge_of_url('https://forge.example/o/r.git'), '', transport=lambda _h, _t: _Connection(sent))
    assert metadata(client) == {'pulls': [], 'issues': []}
    assert sent
    assert not any('Authorization' in headers for headers in sent)
