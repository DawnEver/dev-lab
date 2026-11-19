"""LARGE OBJECTS -- a content-addressed object store on an rclone remote (:class:`RcloneObjects`).

The run-archive backends and the key rules it reuses live in :mod:`dev_lab.dev.artefactstores`; this module is the
one store a result too large for its record travels through, by :class:`~lab_commons.compute.store.Ref`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lab_commons.compute.store import ArrivalMismatch, Ref

from dev_lab.dev.artefactstores import RCLONE, ArtefactRefused, RcloneStore, check_key, file_sha256

__all__ = ['RcloneObjects']


@dataclass(frozen=True)
class RcloneObjects:
    """A lab-commons :class:`~lab_commons.compute.store.LargeObjects` on an rclone remote, content-addressed.

    A file is stored once under ``<remote>/<prefix>/<sha[:2]>/<sha>`` (``--immutable``); the same bytes again is the
    object already there. :meth:`get` re-hashes what arrived and raises the store's own
    :class:`~lab_commons.compute.store.ArrivalMismatch` on a mismatch, so a tampered or truncated object is a miss,
    never a value. *prefix* is durable: a first segment ``scratch`` is refused (a bucket may age that prefix out).
    """

    remote: str
    prefix: str
    rclone: Sequence[str] = ()  # empty: the installed rclone (toolrelease.resolve)
    backend: str = RCLONE

    def __post_init__(self) -> None:
        """Refuse a prefix a remote cannot hold or a bucket ages out."""
        check_key(self.prefix)
        if self.prefix.split('/', 1)[0] == 'scratch':
            msg = (
                f'large-object prefix {self.prefix!r} refused: scratch/ is aged out, a durable object never lives there'
            )
            raise ArtefactRefused(msg)

    def _store(self) -> RcloneStore:
        return RcloneStore(self.remote, self.prefix, self.rclone, self.backend)

    def _key(self, sha256: str) -> str:
        return f'{self.prefix}/{sha256[:2]}/{sha256}'

    def put(self, path: Path) -> Ref:
        """Upload *path* unless an object of its sha256 and size is there; its Ref."""
        store = self._store()
        ref = Ref(self.backend, self._key(file_sha256(path)), path.stat().st_size, file_sha256(path))
        folder, _, name = ref.ref.rpartition('/')
        there = [item for item in store.files(folder) if item['Path'] == name]
        if there and int(there[0]['Size']) == ref.bytes:
            return ref
        store.run('copyto', '--immutable', str(path), store.at(ref.ref))
        return ref

    def get(self, ref: Ref, dest: Path) -> Path:
        """Download *ref*'s bytes to the file *dest*, re-hashed: a mismatch deletes them and is a miss."""
        store = self._store()
        dest.parent.mkdir(parents=True, exist_ok=True)
        store.run('copyto', store.at(ref.ref), str(dest))
        got = file_sha256(dest)
        if got != ref.sha256:
            dest.unlink()
            msg = f'{ref.backend}:{ref.ref}: arrived hashing {got[:16]}, the Ref says {ref.sha256[:16]}; discarded'
            raise ArrivalMismatch(msg)
        return dest
