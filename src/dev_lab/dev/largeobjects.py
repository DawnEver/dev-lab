"""LARGE OBJECTS -- a content-addressed object store on an rclone remote (:class:`RcloneObjects`).

The run-archive backends and the key rules it reuses live in :mod:`dev_lab.dev.artefactstores`; this module is the
one store a result too large for its record travels through, by :class:`~lab_commons.compute.store.Ref`.

WHICH store a run uses is the family's fact (``[storage] runs = "<remote>:<path>"``, :mod:`lab_commons.storage`),
never a flag or a value here: :func:`run_objects` derives it, proves this machine reaches it, and returns the store;
undeclared, it returns ``None`` and an oversize result stays local
(:class:`~lab_commons.compute.store.TooLarge`). Declared but not reached is refused by name with its door
(:class:`StoreUnreached`), never a silent local fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons import launch as _door
from lab_commons import storage as _storage
from lab_commons.compute.store import ArrivalMismatch, Ref

from dev_lab.dev.artefactstores import RCLONE, ArtefactRefused, RcloneStore, check_key, file_sha256
from dev_lab.dev.storage import DEFAULT_RCLONE, Run, check, rclone_exe

__all__ = ['OBJECTS_PREFIX', 'RcloneObjects', 'StoreUnreached', 'run_objects']

#: The durable key prefix every run's large objects live under on the declared store.
OBJECTS_PREFIX: Final = 'results'


class StoreUnreached(_storage.StorageError):
    """The family declares a run store this machine does not reach: the message names the store and its door."""


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


def run_objects(
    repo: Path,
    *,
    declared: _storage.Storage | None = None,
    rclone: Sequence[str] = (),
    run: Run = _door.run,
    to: Path = DEFAULT_RCLONE,
) -> RcloneObjects | None:
    """The large-object store every run on this machine uses: the family's ``[storage] runs``, proven reached.

    THE ONE CALL A CONSUMER NEEDS: a downstream repo hands it its checkout (*repo*, which the rendered rclone config
    stays outside) and never reads hosts-config. ``None`` when the family declares no run store.

    Raises:
        StoreUnreached: the store is declared but this machine does not reach it -- no reach, no placed secret, or
            the listing refused -- naming the store and the door that places its secret.

    """
    declared = _storage.declared() if declared is None else declared
    if declared.runs is None or declared.runs_remote is None:
        return None
    name = declared.runs_remote
    try:
        check(name, repo=repo, to=to, declared=declared, run=run, rclone=rclone)
    except _storage.StorageError as cause:
        msg = (
            f'the family declares run store {declared.runs!r} and this machine does not reach {name!r}: {cause} -- '
            f'on a workstation `python -m dev_lab.ops.secretplace enter --remote {name}`, for an HPC account '
            f'`python -m dev_lab.ops.secretplace distribute --remote {name}`; then '
            f'`python -m dev_lab.dev.storage check {name}`'
        )
        raise StoreUnreached(msg) from cause
    exe = tuple(rclone) or (rclone_exe(),)
    return RcloneObjects(declared.runs, OBJECTS_PREFIX, (*exe, f'--config={to.expanduser()}'))
