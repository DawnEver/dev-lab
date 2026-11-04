"""The backup role: one tar out of the forge host, unpacked and kept on the backup host, copied off-site safely."""

from __future__ import annotations

import hashlib
import io
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dev_lab.ops.backup import BackupRefused, export, pull
from dev_lab.ops.config import Backup, Offsite
from dev_lab.ops.offsite import AwsCli, key_for, upload

NOW = datetime(2026, 11, 4, 3, 30, tzinfo=UTC)
STAMP = '20261104T033000Z'


def _dumper(name: str, content: bytes) -> Callable[[Backup, Path], Path]:
    def dump(_role: Backup, tmp: Path) -> Path:
        path = tmp / name
        path.write_bytes(content)
        return path

    return dump


def test_export_writes_one_tar_of_every_dump(tmp_path: Path) -> None:
    role = Backup(dumpers=('a', 'b'), tmp=str(tmp_path))
    out = io.BytesIO()
    export(role, out, dumpers={'a': _dumper('a.zip', b'zip'), 'b': _dumper('b.pgdump', b'pg')})
    with tarfile.open(fileobj=io.BytesIO(out.getvalue())) as archive:
        assert sorted(archive.getnames()) == ['a.zip', 'b.pgdump']
    assert not list(tmp_path.iterdir())  # the work directory is removed


def test_an_empty_dump_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    role = Backup(dumpers=('a', 'b'), tmp=str(tmp_path))
    out = io.BytesIO()
    with pytest.raises(BackupRefused, match='empty'):
        export(role, out, dumpers={'a': _dumper('a.zip', b'zip'), 'b': _dumper('b.pgdump', b'')})
    assert out.getvalue() == b''


def test_an_unknown_dumper_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BackupRefused, match='unknown dumper'):
        export(Backup(dumpers=('mysql',), tmp=str(tmp_path)), io.BytesIO(), dumpers={})


def _tar(members: dict[str, bytes]) -> Callable[[Backup, Path], None]:
    def fetch(_role: Backup, target: Path) -> None:
        with tarfile.open(target, 'w') as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    return fetch


def test_pull_unpacks_into_a_stamped_directory(tmp_path: Path) -> None:
    role = Backup(source='x@y', dest=str(tmp_path))
    kept = pull(role, NOW, fetch=_tar({'a.zip': b'zip', 'b.pgdump': b'pg'}))
    assert kept == tmp_path / STAMP
    assert sorted(path.name for path in kept.iterdir()) == ['a.zip', 'b.pgdump']
    assert [path.name for path in tmp_path.iterdir()] == [STAMP]


@pytest.mark.parametrize('members', [{'a.zip': b'zip', 'b.pgdump': b''}, {}])
def test_pull_refuses_an_empty_file_or_stream_and_keeps_nothing(tmp_path: Path, members: dict[str, bytes]) -> None:
    with pytest.raises(BackupRefused, match='empty'):
        pull(Backup(source='x@y', dest=str(tmp_path)), NOW, fetch=_tar(members))
    assert list(tmp_path.iterdir()) == []


def test_retention_removes_only_stamped_backups_past_the_declared_days(tmp_path: Path) -> None:
    for days in (20, 15, 13):
        (tmp_path / (NOW - timedelta(days=days)).strftime('%Y%m%dT%H%M%SZ')).mkdir()
    (tmp_path / 'notes').mkdir()
    pull(Backup(source='x@y', dest=str(tmp_path), retention_days=14), NOW, fetch=_tar({'a.zip': b'zip'}))
    left = sorted(path.name for path in tmp_path.iterdir())
    assert left == sorted([(NOW - timedelta(days=13)).strftime('%Y%m%dT%H%M%SZ'), STAMP, 'notes'])


@dataclass
class FakeStore:
    short: int = 0
    objects: dict[str, int] = field(default_factory=dict)

    def put(self, key: str, path: Path) -> None:
        assert key not in self.objects, 'the bucket forbids overwrite'
        self.objects[key] = path.stat().st_size - self.short

    def size(self, key: str) -> int | None:
        return self.objects.get(key)


_SITE = Offsite(endpoint='https://s3.example', bucket='b', label='host-a', max_put_bytes=100)


def test_keys_carry_the_label_the_stamp_and_the_content_hash(tmp_path: Path) -> None:
    dump = tmp_path / 'gitea-dump.zip'
    dump.write_bytes(b'one')
    assert key_for('host-a', STAMP, dump) == f'host-a/{STAMP}/gitea-dump-{hashlib.sha256(b"one").hexdigest()[:16]}.zip'
    other = tmp_path / 'again' / 'gitea-dump.zip'
    other.parent.mkdir()
    other.write_bytes(b'two')
    assert key_for('host-a', STAMP, other) != key_for('host-a', STAMP, dump)  # never an overwrite


def test_upload_puts_each_file_once_and_verifies_its_size(tmp_path: Path) -> None:
    files = [tmp_path / 'a.zip', tmp_path / 'b.pgdump']
    for path in files:
        path.write_bytes(path.name.encode())
    store = FakeStore()
    keys = upload(_SITE, store, STAMP, files)
    assert sorted(store.objects) == sorted(keys)


def test_a_file_above_the_single_put_limit_is_refused_before_any_put(tmp_path: Path) -> None:
    big = tmp_path / 'big.zip'
    big.write_bytes(b'x' * 101)
    store = FakeStore()
    with pytest.raises(BackupRefused, match='single-PUT limit'):
        upload(_SITE, store, STAMP, [big])
    assert store.objects == {}


def test_a_remote_size_mismatch_is_refused(tmp_path: Path) -> None:
    dump = tmp_path / 'a.zip'
    dump.write_bytes(b'abc')
    with pytest.raises(BackupRefused, match='size'):
        upload(_SITE, FakeStore(short=1), STAMP, [dump])


def test_the_cli_store_refuses_a_config_that_is_not_path_style(tmp_path: Path) -> None:
    config = tmp_path / 'aws.config'
    config.write_text('[default]\nregion = r\n', encoding='utf-8')
    with pytest.raises(ValueError, match='addressing_style = path'):
        AwsCli(Offsite(endpoint='https://s', bucket='b', label='l', config_file=str(config)))
