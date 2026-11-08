"""VERIFYING A PACKED ARCHIVE: only the restricted tar the packer emits, every payload against its index.

Ported from the 2026-10-15 artefact-member-index work. The archive is stdlib gzip decompressed in
process, so the old decompressor-child faults (a non-zero exit, a child that never stops writing, a
child left unreaped) have no subject here; their gzip equivalents -- a bad CRC, a truncated member --
are tested in their place.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.dev import artefactpack, artefactscan
from dev_lab.dev.artefactindex import MemberFact
from dev_lab.dev.artefactstores import ARCHIVE, ArtefactRefused, OutputBudgetRefused, Ref

PACK_LIMITS = {'max_members': 100, 'max_index_bytes': 65536, 'max_path_bytes': 4096}


def _ref_of(archive: Path) -> Ref:
    return Ref('folder', f'archive{ARCHIVE}', archive.stat().st_size, hashlib.sha256(archive.read_bytes()).hexdigest())


@pytest.mark.parametrize('mtime', [None, -1, 2**34])
def test_newpack_stream_verifies_actual_pack(tmp_path: Path, mtime: int | None) -> None:
    tree = tmp_path / 'tree'
    tree.mkdir()
    for name, data in [('plain', b'payload'), ('café', b''), ('x' * 120, b'long')]:
        (tree / name).write_bytes(data)
    os.link(tree / 'plain', tree / 'hardlink')
    if mtime is not None:  # an out-of-octal integer timestamp exercises the packer's local PAX path
        try:
            os.utime(tree / 'plain', (mtime, mtime))
        except (OSError, OverflowError, ValueError) as error:
            pytest.xfail(f'this filesystem cannot hold mtime {mtime}: {error}')
    packed = artefactpack.pack(tree, artefactpack.collect(tree, ['*']), tmp_path / 'archive', **PACK_LIMITS)
    decoded = gzip.decompress(packed.path.read_bytes())
    verified = artefactscan.verify_newpack_stream(
        io.BytesIO(decoded), packed.members, max_metadata_bytes=4096, max_uncompressed_bytes=len(decoded), **PACK_LIMITS
    )
    assert verified == packed.members


@pytest.mark.parametrize(
    'fault',
    [
        'metadata',
        'checksum',
        'link',
        'global',
        'unknown',
        'duplicate',
        'size',
        'digest',
        'truncated',
        'tail',
        'order',
        'budget',
        'legacy',
    ],
)
def test_newpack_stream_refuses_untrusted_tar(fault: str) -> None:
    info = tarfile.TarInfo('file')
    info.size = 3
    if fault == 'link':
        info.type = tarfile.SYMTYPE
    if fault == 'unknown':
        info.pax_headers = {'comment': 'not produced'}
    header = info.tobuf(format=tarfile.PAX_FORMAT)
    if fault == 'legacy':
        header = info.tobuf(format=tarfile.GNU_FORMAT)
    data = header + b'abc' + bytes(509) + bytes(1024)
    if fault in ('metadata', 'global'):
        pax = tarfile.TarInfo('././@PaxHeader')
        pax.type = tarfile.XHDTYPE if fault == 'metadata' else tarfile.XGLTYPE
        pax.size = 1000000000
        data = pax.tobuf()
    if fault == 'duplicate':
        body = b'12 path=one\n12 path=two\n'
        pax = tarfile.TarInfo('././@PaxHeader')
        pax.type, pax.size = tarfile.XHDTYPE, len(body)
        data = pax.tobuf() + body + bytes((-len(body)) % 512) + data
    if fault == 'checksum':
        data = b'X' + data[1:]
    if fault == 'truncated':
        data = data[:513]
    if fault == 'tail':
        data += b'not zero'
    expected = (
        MemberFact(
            'other' if fault == 'order' else 'file',
            4 if fault == 'size' else 3,
            '0' * 64 if fault == 'digest' else hashlib.sha256(b'abc').hexdigest(),
        ),
    )
    stream = io.BytesIO(data)
    with pytest.raises(ArtefactRefused):
        artefactscan.verify_newpack_stream(
            stream,
            expected,
            max_metadata_bytes=4096,
            max_uncompressed_bytes=511 if fault == 'budget' else 100000,
            **PACK_LIMITS,
        )
    if fault == 'metadata':
        assert stream.tell() == 512, 'the oversized PAX body is never read'


def test_planted_control_the_untrusted_tar_fixture_verifies_unfaulted() -> None:
    info = tarfile.TarInfo('file')
    info.size = 3
    data = info.tobuf(format=tarfile.PAX_FORMAT) + b'abc' + bytes(509) + bytes(1024)
    expected = (MemberFact('file', 3, hashlib.sha256(b'abc').hexdigest()),)
    verified = artefactscan.verify_newpack_stream(
        io.BytesIO(data), expected, max_metadata_bytes=4096, max_uncompressed_bytes=100000, **PACK_LIMITS
    )
    assert verified == expected


def test_newpack_stream_short_reads_and_exact_total_budget() -> None:
    class ShortReads(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            return super().read(min(size if size is not None and size >= 0 else 7, 7))

    info = tarfile.TarInfo('file')
    info.pax_headers = {'size': '3', 'mtime': '-1'}
    data = info.tobuf(format=tarfile.PAX_FORMAT) + b'abc' + bytes(509) + bytes(2048)
    facts = (MemberFact('file', 3, hashlib.sha256(b'abc').hexdigest()),)
    exact = {'max_metadata_bytes': 100, 'max_uncompressed_bytes': len(data), **PACK_LIMITS}
    assert artefactscan.verify_newpack_stream(ShortReads(data), facts, **exact) == facts
    with pytest.raises(OutputBudgetRefused):
        artefactscan.verify_newpack_stream(ShortReads(data), facts, **dict(exact, max_uncompressed_bytes=len(data) - 1))


def test_newpack_metadata_budget_refuses_before_body_read() -> None:
    class RecordingReads(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None
            assert 0 <= size <= 512
            return super().read(size)

    header = tarfile.TarInfo('././@PaxHeader')
    header.type, header.size = tarfile.XHDTYPE, 10**9
    stream = RecordingReads(header.tobuf())
    with pytest.raises(OutputBudgetRefused, match='metadata'):
        artefactscan.verify_newpack_stream(
            stream,
            (MemberFact('file', 0, hashlib.sha256(b'').hexdigest()),),
            max_metadata_bytes=100,
            max_uncompressed_bytes=10**10,
            **PACK_LIMITS,
        )
    assert stream.tell() == 512


@pytest.mark.parametrize(
    'pax',
    [
        b'12 path=one\n12 path=two\n',
        b'99 path=x\n',
        b'0 path=x\n',
        b'11 size=-1\n',
        b'12 mtime=.1\n',
        b'10 path=\xff\n',
    ],
)
def test_newpack_stream_refuses_malformed_pax(pax: bytes) -> None:
    header = tarfile.TarInfo('././@PaxHeader')
    header.type, header.size = tarfile.XHDTYPE, len(pax)
    data = header.tobuf() + pax + bytes((-len(pax)) % 512)
    with pytest.raises(ArtefactRefused):
        artefactscan.verify_newpack_stream(
            io.BytesIO(data),
            (MemberFact('file', 0, hashlib.sha256(b'').hexdigest()),),
            max_metadata_bytes=100,
            max_uncompressed_bytes=10000,
            **PACK_LIMITS,
        )


# --- a local archive: authenticated before it is decompressed -------------------------------------


@pytest.mark.parametrize('fault', ['none', 'hash', 'length', 'budget', 'malformed', 'truncated', 'crc', 'changed'])
def test_newpack_archive_authenticates_before_decompressing(
    tmp_path: Path, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'source').write_bytes(b'payload')
    packed = artefactpack.pack(tree, [tree / 'source'], tmp_path / 'packed', **PACK_LIMITS)
    archive = tmp_path / 'archive'
    data = packed.path.read_bytes()
    if fault == 'malformed':
        data = gzip.compress(b'not a tar')
    if fault == 'truncated':
        data = gzip.compress(gzip.decompress(data)[:513])
    if fault == 'crc':
        data = data[:-8] + bytes([data[-8] ^ 1]) + data[-7:]
    archive.write_bytes(data)
    ref = _ref_of(archive)
    if fault == 'hash':
        ref = Ref(ref.backend, ref.key, ref.bytes, '0' * 64)
    if fault == 'length':
        ref = Ref(ref.backend, ref.key, ref.bytes + 1, ref.sha256)
    opened: list[object] = []
    real: Callable[..., gzip.GzipFile] = gzip.GzipFile

    def decompressor(*args: object, **kwargs: object) -> gzip.GzipFile:
        opened.append(True)
        if fault == 'changed':
            with archive.open('ab') as tail:
                tail.write(b'changed')
        return real(*args, **kwargs)

    monkeypatch.setattr(artefactscan.gzip, 'GzipFile', decompressor)
    options = dict(
        PACK_LIMITS,
        max_metadata_bytes=4096,
        max_uncompressed_bytes=20000,
        max_compressed_bytes=ref.bytes - 1 if fault == 'budget' else ref.bytes,
    )
    if fault == 'none':
        assert artefactscan.verify_newpack_archive(archive, ref, packed.members, **options) == packed.members
    else:
        with pytest.raises(ArtefactRefused):
            artefactscan.verify_newpack_archive(archive, ref, packed.members, **options)
    assert bool(opened) == (fault not in ('hash', 'length', 'budget')), 'nothing is decompressed unauthenticated'


@pytest.mark.parametrize('fault', ['bool_bytes', 'bad_sha', 'directory', 'leaf_alias', 'parent_alias'])
def test_newpack_archive_refuses_identity_before_reading(tmp_path: Path, fault: str) -> None:
    path = tmp_path / 'archive'
    path.write_bytes(b'archive')
    ref = Ref(
        'folder',
        f'archive{ARCHIVE}',
        True if fault == 'bool_bytes' else 7,
        'bad' if fault == 'bad_sha' else hashlib.sha256(b'archive').hexdigest(),
    )
    if fault == 'directory':
        path = tmp_path
    if fault in ('leaf_alias', 'parent_alias'):
        alias = tmp_path / 'alias'
        try:
            alias.symlink_to(tmp_path if fault == 'parent_alias' else path, target_is_directory=fault == 'parent_alias')
        except (OSError, NotImplementedError) as error:
            pytest.xfail(f'symlinks unavailable: {error}')
        path = alias / 'archive' if fault == 'parent_alias' else alias
    with pytest.raises(ArtefactRefused):
        artefactscan.verify_newpack_archive(
            path,
            ref,
            (),
            max_compressed_bytes=100,
            max_metadata_bytes=100,
            max_uncompressed_bytes=1000,
            **PACK_LIMITS,
        )
