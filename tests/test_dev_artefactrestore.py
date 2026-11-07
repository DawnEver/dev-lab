"""MATERIALIZING A SELECTION: a fresh owned root, its receipt last, and only what it owns cleaned up.

Ported from the 2026-10-15 artefact-member-index work; the archive is real stdlib gzip, so the old
decompressor-exit fault is a gzip CRC fault here.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import IO, Self, TypedDict, cast

import pytest

from dev_lab.dev import artefactpack, artefactrestore, artefactscan
from dev_lab.dev.artefactindex import MemberFact
from dev_lab.dev.artefactstores import ARCHIVE, ArtefactRefused, OutputBudgetRefused, Ref

PACK_LIMITS = {'max_members': 100, 'max_index_bytes': 65536, 'max_path_bytes': 4096}


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str = ''
) -> tuple[Path, Ref, tuple[MemberFact, ...], Path]:
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'selected').write_bytes(b'x' * 100000)
    (tree / 'zero').write_bytes(b'')
    (tree / 'unselected').write_bytes(b'not selected')
    names = ('selected', 'zero', 'unselected')
    if fault == 'nested':
        (tree / 'a' / 'b').mkdir(parents=True)
        (tree / 'selected').rename(tree / 'a' / 'b' / 'x')
        (tree / 'zero').rename(tree / 'a' / 'y')
        names = ('a/b/x', 'a/y', 'unselected')
    packed = artefactpack.pack(tree, [tree / name for name in names], tmp_path / 'packed', **PACK_LIMITS)
    data = packed.path.read_bytes()
    if fault == 'unselected':
        data = gzip.compress(gzip.decompress(data).replace(b'not selected', b'bad selected'))
    if fault == 'crc':
        data = data[:-8] + bytes([data[-8] ^ 1]) + data[-7:]
    archive = tmp_path / 'archive'
    archive.write_bytes(data)
    ref = Ref('folder', f'archive{ARCHIVE}', archive.stat().st_size, hashlib.sha256(data).hexdigest())
    if fault == 'changed':
        real = artefactscan._scan

        def and_the_source_moves(
            stream: IO[bytes],
            facts: tuple[MemberFact, ...],
            max_metadata_bytes: int,
            max_uncompressed_bytes: int,
            output: artefactscan.MemberSink | None,
        ) -> tuple[MemberFact, ...]:
            verified = real(stream, facts, max_metadata_bytes, max_uncompressed_bytes, output)
            with archive.open('ab') as tail:
                tail.write(b'changed')
            return verified

        monkeypatch.setattr(artefactscan, '_scan', and_the_source_moves)
    parent = tmp_path / 'restored'
    parent.mkdir()
    return archive, ref, packed.members, parent


class _Options(TypedDict):
    max_members: int
    max_index_bytes: int
    max_path_bytes: int
    max_compressed_bytes: int
    max_metadata_bytes: int
    max_uncompressed_bytes: int
    max_entries: int
    max_bytes: int
    case_sensitive: bool


def _options(ref: Ref, *, max_entries: int = 10, max_bytes: int = 200000) -> _Options:
    return _Options(
        max_members=PACK_LIMITS['max_members'],
        max_index_bytes=PACK_LIMITS['max_index_bytes'],
        max_path_bytes=PACK_LIMITS['max_path_bytes'],
        max_compressed_bytes=ref.bytes,
        max_metadata_bytes=4096,
        max_uncompressed_bytes=200000,
        max_entries=max_entries,
        max_bytes=max_bytes,
        case_sensitive=False,
    )


@pytest.mark.parametrize('fault', ['', 'empty', 'unselected', 'crc', 'changed', 'entries', 'bytes'])
def test_materialize_newpack_receipt_last_and_exact_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    archive, ref, facts, parent = _fixture(tmp_path, monkeypatch, fault)
    paths = [] if fault == 'empty' else ['selected', 'zero']
    receipt = json.dumps(
        {'schema': 'lab-commons-materialized-v1', 'archive': ref.manifest(), 'selected_paths': paths},
        sort_keys=True,
        ensure_ascii=True,
    ).encode()
    entries = len(paths) + 2
    size = (100000 if paths else 0) + len(receipt)
    options = _options(ref, max_entries=entries - (fault == 'entries'), max_bytes=size - (fault == 'bytes'))
    if fault in ('unselected', 'crc', 'changed', 'entries', 'bytes'):
        with pytest.raises(ArtefactRefused):
            artefactrestore.materialize_newpack_archive(archive, ref, facts, paths, parent, **options)
        assert list(parent.iterdir()) == []
    else:
        root = artefactrestore.materialize_newpack_archive(archive, ref, facts, paths, parent, **options)
        assert root.parent == parent
        assert (root / 'materialization-complete.json').read_bytes() == receipt
        assert sorted(path.name for path in root.iterdir()) == sorted([*paths, 'materialization-complete.json'])
        if paths:
            assert (root / 'selected').read_bytes() == b'x' * 100000
            assert (root / 'zero').read_bytes() == b''


@pytest.mark.parametrize(
    'name',
    [
        'CON',
        'aux.txt',
        'COM1.bin',
        'x.',
        'x ',
        'a<b',
        'a?b',
        'materialization-complete.json/x',
        'MATERIALIZATION-COMPLETE.JSON',
    ],
)
def test_materialization_refuses_target_names_before_root(tmp_path: Path, name: str) -> None:
    fact = MemberFact(name, 0, hashlib.sha256(b'').hexdigest())
    with pytest.raises(ArtefactRefused):
        artefactrestore.materialize_newpack_archive(
            tmp_path / 'absent',
            Ref('folder', 'x', 1, '0' * 64),
            (fact,),
            [name],
            tmp_path,
            max_compressed_bytes=1,
            max_metadata_bytes=100,
            max_uncompressed_bytes=10000,
            max_entries=10,
            max_bytes=10000,
            case_sensitive=True,
            **PACK_LIMITS,
        )
    assert list(tmp_path.iterdir()) == []


class _OutputBoundary:
    def __init__(self, path: Path, stream: IO[bytes], fault: str, held: Path) -> None:
        self.path, self.stream, self.fault, self.held = path, stream, fault, held

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.stream.close()
        if self.fault == 'foreign' and self.path.name == 'selected':
            self.path.rename(self.held)
            self.path.write_bytes(b'foreign replacement')

    def fileno(self) -> int:
        return self.stream.fileno()

    def flush(self) -> None:
        self.stream.flush()

    def write(self, data: bytes) -> int:
        if self.fault == 'write' or (self.fault == 'receipt' and self.path.name == 'materialization-complete.json'):
            self.stream.write(data[:3])
            msg = 'real output boundary failed'
            raise OSError(msg)
        return self.stream.write(data[:3] if self.fault == 'short' else data)


@pytest.mark.parametrize('fault', ['short', 'write', 'receipt', 'foreign'])
def test_materialization_real_output_boundary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    archive, ref, facts, parent = _fixture(tmp_path, monkeypatch)
    original_open = cast('Callable[..., IO[bytes]]', Path.open)

    def output_open(path: Path, mode: str = 'r', *args: object, **kwargs: object) -> object:
        stream = original_open(path, mode, *args, **kwargs)
        held = tmp_path / 'held-original'
        return _OutputBoundary(path, stream, fault, held) if mode == 'xb' and path.is_relative_to(parent) else stream

    monkeypatch.setattr(Path, 'open', output_open)
    options = _options(ref)
    if fault == 'short':  # PLANTED CONTROL: short writes are completed, not lost
        root = artefactrestore.materialize_newpack_archive(archive, ref, facts, ['selected', 'zero'], parent, **options)
        assert (root / 'selected').read_bytes() == b'x' * 100000
        assert (root / 'materialization-complete.json').is_file()
    elif fault == 'foreign':
        with pytest.raises(ArtefactRefused, match='cleanup incomplete'):
            artefactrestore.materialize_newpack_archive(archive, ref, facts, ['selected'], parent, **options)
        (root,) = parent.iterdir()
        assert (root / 'selected').read_bytes() == b'foreign replacement', 'a foreign file is never deleted'
        assert not (root / 'materialization-complete.json').exists()
    else:
        with pytest.raises(OSError, match='boundary failed'):
            artefactrestore.materialize_newpack_archive(archive, ref, facts, ['selected'], parent, **options)
        assert list(parent.iterdir()) == []


@pytest.mark.parametrize('max_entries', [5, 6])
def test_materialization_nested_parents_exact_entry_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_entries: int
) -> None:
    archive, ref, facts, parent = _fixture(tmp_path, monkeypatch, 'nested')
    options = _options(ref, max_entries=max_entries)
    if max_entries == 5:
        with pytest.raises(OutputBudgetRefused):
            artefactrestore.materialize_newpack_archive(archive, ref, facts, ['a/b/x', 'a/y'], parent, **options)
        assert list(parent.iterdir()) == []
    else:
        root = artefactrestore.materialize_newpack_archive(archive, ref, facts, ['a/b/x', 'a/y'], parent, **options)
        assert (root / 'a' / 'b' / 'x').read_bytes() == b'x' * 100000
        assert (root / 'a' / 'y').read_bytes() == b''
        assert len(list(root.rglob('*'))) + 1 == 6


def test_materialization_compressed_budget_precedes_destination_access(tmp_path: Path) -> None:
    with pytest.raises(OutputBudgetRefused, match='compressed'):
        artefactrestore.materialize_newpack_archive(
            tmp_path / 'absent',
            Ref('folder', 'x', 2, '0' * 64),
            (),
            [],
            tmp_path / 'absent-parent',
            max_compressed_bytes=1,
            max_metadata_bytes=100,
            max_uncompressed_bytes=10000,
            max_entries=10,
            max_bytes=10000,
            case_sensitive=True,
            **PACK_LIMITS,
        )
    assert list(tmp_path.iterdir()) == []
