"""THE FOLDER BACKEND: archive before manifest, idempotent retry, write-once under concurrency, no aliases.

Ported from the 2026-10-15 artefact-member-index work.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dev_lab.dev import artefactfolder
from dev_lab.dev.artefactfolder import FolderStore
from dev_lab.dev.artefactstores import ARCHIVE, MANIFEST, ArtefactRefused, Ref, object_key, run_id

RUN = run_id('a' * 40, 'linux', 'alice', datetime(2026, 10, 11, 9, 30, 5, tzinfo=UTC))


def test_folder_orphan_archive_recovers_only_matching_bytes(tmp_path: Path) -> None:
    source = tmp_path / 'input'
    source.write_bytes(b'archive bytes')
    store = FolderStore(tmp_path / 'store', 'lab')
    target = store.root / (object_key('lab', RUN) + ARCHIVE)
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    ref = store.put(RUN, source)
    assert ref.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert target.read_bytes() == b'archive bytes'
    assert store.list(None) == (ref,)


@pytest.mark.parametrize('fault', ['orphan', 'missing', 'changed', 'backend', 'key', 'bytes', 'bool_bytes'])
def test_folder_refuses_inconsistent_archive_or_manifest(tmp_path: Path, fault: str) -> None:
    source = tmp_path / 'input'
    source.write_bytes(b'archive bytes')
    store = FolderStore(tmp_path / 'store', 'lab')
    ref = store.put(RUN, source)
    assert store.put(RUN, source) == ref, 'PLANTED CONTROL: the same bytes again is the object already landed'
    target = store.root / ref.key
    manifest = target.with_name(RUN + MANIFEST)
    if fault == 'orphan':
        manifest.unlink()
        target.write_bytes(b'different bytes')
    elif fault == 'missing':
        target.unlink()
    elif fault == 'changed':
        target.write_bytes(b'different bytes')
    else:
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value[{'key': 'ref', 'bool_bytes': 'bytes'}.get(fault, fault)] = {
            'backend': 'forge',
            'key': 'foreign/path',
            'bytes': 999,
            'bool_bytes': True,
        }[fault]
        manifest.write_text(json.dumps(value), encoding='utf-8')
    before = {path: path.read_bytes() for path in store.root.rglob('*') if path.is_file()}
    with pytest.raises(ArtefactRefused, match=r'content|archive|manifest|identity'):
        store.put(RUN, source)
    assert {path: path.read_bytes() for path in store.root.rglob('*') if path.is_file()} == before


@pytest.mark.parametrize('same', [True, False])
def test_folder_concurrent_publishers_are_write_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, same: bool
) -> None:
    sources = [tmp_path / 'a', tmp_path / 'b']
    sources[0].write_bytes(b'first archive')
    sources[1].write_bytes(b'first archive' if same else b'other archive')
    store = FolderStore(tmp_path / 'store', 'lab')
    barrier = threading.Barrier(2)
    link = os.link

    def competing_link(source: Path, destination: Path) -> None:
        if str(destination).endswith(ARCHIVE):
            barrier.wait(timeout=5)
        link(source, destination)

    monkeypatch.setattr(artefactfolder.os, 'link', competing_link)

    def publish(source: Path) -> Ref | Exception:
        try:
            return store.put(RUN, source)
        except (ArtefactRefused, OSError) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, sources))
    refs = [value for value in results if isinstance(value, Ref)]
    failures = [value for value in results if isinstance(value, Exception)]
    assert len(refs) == (2 if same else 1)
    assert len(failures) == (0 if same else 1)
    assert all(isinstance(value, ArtefactRefused) for value in failures)
    assert store.list(None) == (refs[0],)
    assert not list(store.root.rglob('*.partial'))


@pytest.mark.parametrize('role', ['archive', 'manifest', 'parent'])
def test_folder_refuses_leaf_and_parent_aliases(tmp_path: Path, role: str) -> None:
    source = tmp_path / 'input'
    source.write_bytes(b'archive bytes')
    store = FolderStore(tmp_path / 'store', 'lab')
    external = tmp_path / 'external'
    if role == 'parent':
        external.mkdir()
        store.root.mkdir()
        alias = store.root / 'lab'
    else:
        ref = store.put(RUN, source)
        alias = store.root / ref.key
        if role == 'manifest':
            alias = alias.with_name(RUN + MANIFEST)
        external.write_bytes(alias.read_bytes())
        alias.unlink()
    try:
        alias.symlink_to(external, target_is_directory=role == 'parent')
    except (OSError, NotImplementedError) as error:
        pytest.xfail(f'symlinks unavailable: {error}')
    with pytest.raises(ArtefactRefused, match='alias'):
        store.put(RUN, source)


def test_folder_copied_payload_must_match_reference_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / 'input'
    source.write_bytes(b'original archive')
    store = FolderStore(tmp_path / 'store', 'lab')
    copyfile = shutil.copyfile

    def altered_copy(original: Path, destination: Path) -> None:
        copyfile(original, destination)
        destination.write_bytes(b'changed during copy')

    monkeypatch.setattr(artefactfolder.shutil, 'copyfile', altered_copy)
    with pytest.raises(ArtefactRefused, match='copied archive'):
        store.put(RUN, source)
    assert not [path for path in store.root.rglob('*') if path.is_file()]


def test_folder_manifest_link_failure_retains_recoverable_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / 'input'
    source.write_bytes(b'original archive')
    store = FolderStore(tmp_path / 'store', 'lab')
    target = store.root / (object_key('lab', RUN) + ARCHIVE)
    manifest = target.with_name(RUN + MANIFEST)
    link = os.link
    failed = False

    def interrupted_link(original: Path, destination: Path) -> None:
        nonlocal failed
        if Path(destination) == manifest and not failed:
            failed = True
            msg = 'injected manifest link interruption'
            raise OSError(msg)
        link(original, destination)

    monkeypatch.setattr(artefactfolder.os, 'link', interrupted_link)
    with pytest.raises(OSError, match='manifest link interruption'):
        store.put(RUN, source)
    assert target.read_bytes() == b'original archive'
    assert not manifest.exists()
    assert not list(store.root.rglob('*.partial'))
    source.write_bytes(b'other archive')
    with pytest.raises(ArtefactRefused, match='other content'):
        store.put(RUN, source)
    assert not manifest.exists()
    assert target.read_bytes() == b'original archive'
    source.write_bytes(b'original archive')
    ref = store.put(RUN, source)
    assert store.list(None) == (ref,)
    assert not list(store.root.rglob('*.partial'))
