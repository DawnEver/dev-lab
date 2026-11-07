"""PACKING DECLARED OUTPUTS: the selected footprint is bounded, and every member is hashed on its tar stream.

Ported from the 2026-10-15 artefact-member-index work. The archive is stdlib gzip, so no compressor is
faked: a fault the old zstd child injected is injected here at the packer's own seam.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from dev_lab.dev import artefactindex, artefactpack
from dev_lab.dev.artefactindex import MemberFact, PackedOutputs, StoredOutputs
from dev_lab.dev.artefactstores import ArtefactRefused, OutputBudgetRefused, OutputIntegrityRefused, Ref

PACK_LIMITS = {'max_members': 100, 'max_index_bytes': 65536, 'max_path_bytes': 4096}


def _alias(alias: Path, target: Path, *, directory: bool) -> None:
    """A directory junction on Windows (no privilege needed), else a symlink; skip where neither exists."""
    if directory and os.name == 'nt':
        cmd = shutil.which('cmd')
        assert cmd is not None
        subprocess.run([cmd, '/c', 'mklink', '/J', str(alias), str(target)], check=True, capture_output=True)
        return
    try:
        alias.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f'symlinks unavailable: {error}')


# --- collect: the selected footprint ------------------------------------------------------------


@pytest.mark.parametrize('parent_alias', [False, True])
@pytest.mark.parametrize('outside', [False, True])
def test_output_leaf_and_parent_aliases_are_refused(tmp_path: Path, *, parent_alias: bool, outside: bool) -> None:
    tree = tmp_path / 'tree'
    tree.mkdir()
    target = (tmp_path if outside else tree) / 'real'
    target.mkdir()
    (target / 'zero.bin').write_bytes(b'')
    _alias(tree / 'alias', target if parent_alias else target / 'zero.bin', directory=parent_alias)
    declared = 'alias/zero.bin' if parent_alias else 'alias'
    with pytest.raises(ArtefactRefused, match=r'alias|symlink|outside'):
        artefactpack.collect(tree, [declared])
    if not outside:  # PLANTED CONTROL: the real path to the same file is collected
        assert artefactpack.collect(tree, ['real/zero.bin']) == [target / 'zero.bin']


def test_collect_budget_counts_unique_files_and_parent_directories(tmp_path: Path) -> None:
    (tmp_path / 'out' / 'nested').mkdir(parents=True)
    (tmp_path / 'out' / 'nested' / 'a.bin').write_bytes(b'ab')
    (tmp_path / 'out' / 'zero.bin').write_bytes(b'')
    outputs = ['out/**/*.bin', 'out/zero.bin']
    expected = [tmp_path / 'out' / 'nested' / 'a.bin', tmp_path / 'out' / 'zero.bin']
    assert artefactpack.collect(tmp_path, outputs, max_entries=5, max_bytes=2) == expected
    with pytest.raises(OutputBudgetRefused, match='entries'):
        artefactpack.collect(tmp_path, outputs, max_entries=4, max_bytes=2)
    with pytest.raises(OutputBudgetRefused, match='bytes'):
        artefactpack.collect(tmp_path, outputs, max_entries=5, max_bytes=1)


def test_collect_empty_and_zero_byte_budgets_are_explicit(tmp_path: Path) -> None:
    assert artefactpack.collect(tmp_path, [], max_entries=0, max_bytes=0) == []
    (tmp_path / 'zero').write_bytes(b'')
    assert artefactpack.collect(tmp_path, ['zero'], max_entries=2, max_bytes=0) == [tmp_path / 'zero']
    with pytest.raises(OutputBudgetRefused, match='entries'):
        artefactpack.collect(tmp_path, ['zero'], max_entries=1)


@pytest.mark.parametrize('name', ['max_entries', 'max_bytes'])
@pytest.mark.parametrize('value', [False, True, -1, 1.0])
def test_collect_refuses_noninteger_or_negative_budgets(tmp_path: Path, name: str, value: object) -> None:
    with pytest.raises(ArtefactRefused, match='nonnegative integer'):
        artefactpack.collect(tmp_path, [], **{name: value})  # type: ignore[arg-type]


# --- pack: the member index ---------------------------------------------------------------------


def test_pack_index_hashes_actual_regular_hardlink_payloads(tmp_path: Path) -> None:
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'a').write_bytes(b'actual tar payload')
    os.link(tree / 'a', tree / 'b')
    packed = artefactpack.pack(tree, [tree / 'a', tree / 'b'], tmp_path / 'archive', **PACK_LIMITS)
    assert isinstance(packed, PackedOutputs)
    assert [(item.path, item.logical_bytes, item.sha256) for item in packed.members] == [
        (name, 18, hashlib.sha256(b'actual tar payload').hexdigest()) for name in ('a', 'b')
    ]
    with tarfile.open(packed.path) as archive:
        assert all(member.isfile() for member in archive.getmembers()), 'a hard link is its own regular member'
        payloads = [archive.extractfile(member).read() for member in archive.getmembers()]  # type: ignore[union-attr]
        assert payloads == [b'actual tar payload'] * 2


def test_pack_without_index_limits_still_indexes(tmp_path: Path) -> None:
    """The review and unit bundles pack with no budget; their archive still carries its member facts."""
    (tmp_path / 'a').write_bytes(b'x')
    packed = artefactpack.pack(tmp_path, [tmp_path / 'a'], tmp_path / 'archive')
    assert packed.members == (MemberFact('a', 1, hashlib.sha256(b'x').hexdigest()),)


@pytest.mark.parametrize(('key', 'value'), [('max_members', 1), ('max_index_bytes', 1), ('max_path_bytes', 1)])
def test_pack_index_limits_refuse_before_final_publication(tmp_path: Path, key: str, value: int) -> None:
    (tmp_path / 'aa').write_bytes(b'x')
    (tmp_path / 'bb').write_bytes(b'y')
    limits = dict(PACK_LIMITS, **{key: value})
    with pytest.raises(OutputBudgetRefused, match='index'):
        artefactpack.pack(tmp_path, [tmp_path / 'aa', tmp_path / 'bb'], tmp_path / 'archive', **limits)
    assert not (tmp_path / 'archive').exists()
    assert not list(tmp_path.glob('*.partial'))


def test_pack_index_exact_serialized_boundary_and_unicode_path(tmp_path: Path) -> None:
    source = tmp_path / 'é'
    source.write_bytes(b'')
    packed = artefactpack.pack(tmp_path, [source], tmp_path / 'first', **PACK_LIMITS)
    assert packed.archive_sha256 == hashlib.sha256(packed.path.read_bytes()).hexdigest()
    assert packed.compressed_bytes == packed.path.stat().st_size
    ref = Ref('folder', 'unused', packed.compressed_bytes, packed.archive_sha256)
    size = len(json.dumps(StoredOutputs(ref, packed.members).index(), sort_keys=True, ensure_ascii=True).encode())
    exact = dict(PACK_LIMITS, max_index_bytes=size, max_path_bytes=2)  # 'é' is two UTF-8 bytes
    artefactpack.pack(tmp_path, [source], tmp_path / 'exact', **exact)
    with pytest.raises(OutputBudgetRefused, match='index'):
        artefactpack.pack(tmp_path, [source], tmp_path / 'short', **dict(exact, max_index_bytes=size - 1))
    assert not (tmp_path / 'short').exists()


@pytest.mark.parametrize('value', [False, True, 0, -1, 1.0, None])
def test_pack_index_requires_positive_integer_limits_declared_together(tmp_path: Path, value: object) -> None:
    with pytest.raises(OutputBudgetRefused, match='positive integers'):
        artefactpack.pack(tmp_path, [], tmp_path / 'archive', **dict(PACK_LIMITS, max_members=value))  # type: ignore[arg-type]


@pytest.mark.parametrize('name', ['a:b', 'bad\\name', 'bad\nname', '../up', ''])
def test_member_names_refuse_unsafe_metadata(name: str) -> None:
    with pytest.raises(OutputBudgetRefused, match='path'):
        artefactindex.member_name(name, 4096)


def test_planted_control_a_unicode_member_name_is_safe() -> None:
    assert artefactindex.member_name('dir/café.bin', 4096) == 'dir/café.bin'


def test_pack_refuses_existing_destination_without_touching_it(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.write_bytes(b'payload')
    destination = tmp_path / 'archive'
    destination.write_bytes(b'prior committed bytes')
    with pytest.raises(FileExistsError):
        artefactpack.pack(tmp_path, [source], destination, **PACK_LIMITS)
    assert destination.read_bytes() == b'prior committed bytes'


def test_pack_refuses_dangling_final_symlink(tmp_path: Path) -> None:
    destination = tmp_path / 'archive'
    try:
        destination.symlink_to(tmp_path / 'absent')
    except (OSError, NotImplementedError) as error:
        pytest.skip(f'symlinks unavailable: {error}')
    with pytest.raises(FileExistsError):
        artefactpack.pack(tmp_path, [], destination, **PACK_LIMITS)
    assert destination.is_symlink()
    assert not (tmp_path / 'absent').exists()


def test_pack_rechecks_collected_source_alias(tmp_path: Path) -> None:
    tree = tmp_path / 'tree'
    tree.mkdir()
    source = tree / 'source'
    source.write_bytes(b'original')
    selected = artefactpack.collect(tree, ['source'])
    external = tmp_path / 'external'
    external.write_bytes(b'foreign')
    source.unlink()
    _alias(source, external, directory=False)
    with pytest.raises(ArtefactRefused, match=r'outside|alias'):
        artefactpack.pack(tree, selected, tmp_path / 'archive', **PACK_LIMITS)
    assert not (tmp_path / 'archive').exists()


def test_pack_source_error_leaves_no_final_or_owned_temporary(tmp_path: Path) -> None:
    """A source gone mid-pack (the old failing-compressor case): nothing is published, nothing is left."""
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'first').write_bytes(b'x' * 1024)
    (tree / 'second').write_bytes(b'second')
    files = [tree / 'first', tree / 'second']
    (tree / 'second').unlink()
    before = set(tmp_path.iterdir())
    with pytest.raises(FileNotFoundError):
        artefactpack.pack(tree, files, tmp_path / 'archive', **PACK_LIMITS)
    assert set(tmp_path.iterdir()) == before


def test_pack_late_publish_collision_preserves_other_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / 'source'
    source.write_bytes(b'payload')
    destination = tmp_path / 'archive'
    member = artefactpack._tar_member

    def and_another_publisher(*args: object) -> MemberFact:
        destination.write_bytes(b'other publisher')
        return member(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(artefactpack, '_tar_member', and_another_publisher)
    before = set(tmp_path.iterdir())
    with pytest.raises(FileExistsError):
        artefactpack.pack(tmp_path, [source], destination, **PACK_LIMITS)
    assert destination.read_bytes() == b'other publisher'
    assert set(tmp_path.iterdir()) == before | {destination}


def test_pack_source_changed_while_tar_reads_it_is_integrity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / 'source'
    source.write_bytes(b'x' * 100000)
    original = artefactpack._HashingReader.read
    changed = []

    def drifting(self: object, size: int = -1) -> bytes:
        if not changed:
            changed.append(True)
            stamp = source.stat()
            with source.open('r+b') as stream:
                stream.write(b'changed-source')
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 10**9))
        return original(self, size)  # type: ignore[arg-type]

    monkeypatch.setattr(artefactpack._HashingReader, 'read', drifting)
    with pytest.raises(OutputIntegrityRefused):
        artefactpack.pack(tmp_path, [source], tmp_path / 'archive', **PACK_LIMITS)
    assert not (tmp_path / 'archive').exists()


@pytest.mark.parametrize('mtime', [-1, 2**34])
def test_pack_emits_the_restricted_pax_format(tmp_path: Path, mtime: int) -> None:
    """Out-of-octal integer timestamps take the PAX path; the archive stays gzip over a POSIX tar."""
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'plain').write_bytes(b'payload')
    try:
        os.utime(tree / 'plain', (mtime, mtime))
    except (OSError, OverflowError, ValueError) as error:
        pytest.skip(f'this filesystem cannot hold mtime {mtime}: {error}')
    packed = artefactpack.pack(tree, [tree / 'plain'], tmp_path / 'archive', **PACK_LIMITS)
    with gzip.open(packed.path) as stream:
        decoded = stream.read()
    assert decoded[257:265] == tarfile.POSIX_MAGIC
    with tarfile.open(fileobj=io.BytesIO(decoded)) as tar:
        assert tar.getnames() == ['plain']
