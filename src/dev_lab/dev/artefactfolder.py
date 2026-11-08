"""THE FOLDER BACKEND -- a local directory holding ``<repo>/...`` exactly as the remote does.

A writer's ``folder`` store, and a reader's synced mirror of the large store
(:func:`dev_lab.dev.artefacts.reader`).

IDEMPOTENT, ARCHIVE BEFORE MANIFEST. :meth:`FolderStore.put` publishes the archive first, then its
manifest, each through a unique fsynced temporary linked no-replace. A put interrupted between the two
is retried by verifying the existing archive's full sha256 and size before the missing manifest is
committed -- different bytes are never overwritten. An existing manifest is accepted only when its whole
Ref matches AND its archive still verifies. Concurrent identical writers are idempotent; conflicting
writers are refused. A symlink or junction alias of an archive, a manifest or a parent is refused.
Not a power-loss durability guarantee, not a transaction with the run record, and not extended to the
other backends.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.artefactpack import file_identity
from dev_lab.dev.artefactstores import (
    ARCHIVE,
    FOLDER,
    MANIFEST,
    ArtefactRefused,
    Ref,
    check_key,
    object_key,
    ref_of,
    scratch_dir,
    sorted_refs,
    verified_copy,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

__all__ = ['FolderStore']

#: A manifest is four short fields; anything larger is not one.
_MANIFEST_MAX: Final = 1024 * 1024
_MANIFEST_KEYS: Final = frozenset({'backend', 'ref', 'bytes', 'sha256'})


@dataclass(frozen=True)
class FolderStore:
    """A local directory; *root* holds ``<repo>/...`` exactly as the remote does (a reader's synced mirror)."""

    root: Path
    repo: str
    backend: str = FOLDER

    def _guard(self, path: Path) -> None:
        if path.resolve() != self.root.resolve() / path.relative_to(self.root):
            msg = f'{path}: archive/manifest alias refused'
            raise ArtefactRefused(msg)

    def _verify_archive(self, path: Path, expected: Ref) -> None:
        self._guard(path)
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or ref_of(expected.backend, expected.key, path) != expected:
                msg = f'{path}: archive has other content or identity'
                raise ArtefactRefused(msg)
            after = path.lstat()
        except FileNotFoundError as error:
            msg = f'{path}: committed archive is missing'
            raise ArtefactRefused(msg) from error
        self._guard(path)
        if file_identity(before) != file_identity(after):
            msg = f'{path}: archive identity changed during verification'
            raise ArtefactRefused(msg)

    def _publish(self, name: Path, write: Callable[[Path], None]) -> None:
        """*write* a unique temporary and link it to *name* unless one is there; the caller verifies the winner."""
        self._guard(name)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{name.name}.', suffix='.partial', dir=name.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            write(temporary)
            with temporary.open('r+b') as stream:
                os.fsync(stream.fileno())
            self._guard(name)
            with suppress(FileExistsError):
                os.link(temporary, name)
        finally:
            temporary.unlink()

    def _stored(self, key: str) -> Ref | None:
        manifest = self.root / key.removesuffix(ARCHIVE)
        path = manifest.with_name(manifest.name + MANIFEST)
        self._guard(path)
        if not os.path.lexists(path):
            return None
        if not path.is_file():
            msg = f'{path}: manifest is not a regular file'
            raise ArtefactRefused(msg)
        with path.open('rb') as stream:
            data = stream.read(_MANIFEST_MAX + 1)
        if len(data) > _MANIFEST_MAX:
            msg = f'{path}: oversized manifest identity'
            raise ArtefactRefused(msg)
        value = json.loads(data)
        if (
            not isinstance(value, dict)
            or set(value) != _MANIFEST_KEYS
            or type(value['bytes']) is not int
            or value['bytes'] < 0
        ):
            msg = f'{path}: invalid manifest identity'
            raise ArtefactRefused(msg)
        return Ref.of(value)

    def put(self, ident: str, path: Path) -> Ref:
        """Write-once and idempotent: the archive, then its manifest (module docstring)."""
        base = object_key(self.repo, ident)
        new = ref_of(self.backend, base + ARCHIVE, path)
        check_key(base + MANIFEST)
        target = self.root / new.key
        landed = self._stored(new.key)
        if landed is not None:
            if landed != new:
                msg = f'{new.key} already exists with other content or manifest identity: write-once'
                raise ArtefactRefused(msg)
            self._verify_archive(target, new)
            return new
        self._guard(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        def copy_archive(destination: Path) -> None:
            shutil.copyfile(path, destination)
            if ref_of(new.backend, new.key, destination) != new:
                msg = f'{new.key}: copied archive has other content'
                raise ArtefactRefused(msg)

        if not os.path.lexists(target):
            self._publish(target, copy_archive)
        self._verify_archive(target, new)
        manifest = target.with_name(ident + MANIFEST)
        self._publish(manifest, lambda dst: dst.write_text(json.dumps(new.manifest()), encoding='utf-8'))
        if self._stored(new.key) != new:
            msg = f'{new.key}: conflicting committed manifest identity'
            raise ArtefactRefused(msg)
        self._verify_archive(target, new)
        return new

    def get(self, ref: Ref, dest: Path) -> Path:
        """Copy out and verify."""
        scratch = scratch_dir()
        try:
            fetched = scratch / 'fetched'
            shutil.copyfile(self.root / ref.key, fetched)
            return verified_copy(ref, fetched, dest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every manifest under ``<root>/<repo>``."""
        base = self.root / self.repo
        found = [Ref.of(json.loads(p.read_text(encoding='utf-8'))) for p in base.rglob(f'*{MANIFEST}')]
        return sorted_refs(found if base.is_dir() else [], older_than)

    def delete(self, ref: Ref) -> None:
        """Delete both objects, then each emptied parent up to the repo folder."""
        archive = self.root / ref.key
        archive.with_name(ref.run_id + MANIFEST).unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        top = self.root / self.repo
        parent = archive.parent
        while parent != top and top in parent.parents and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
