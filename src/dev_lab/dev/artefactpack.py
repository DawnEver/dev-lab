"""PACKING DECLARED OUTPUTS -- collect what a run declared, bound its footprint, pack it with its member index.

:func:`collect` names the files a run's ``outputs`` declare under its work tree; every declaration must
match a regular file inside the tree (a symlink or junction alias is refused). An optional selected
expanded footprint -- ``max_entries`` (unique files plus their unique parent directories through the
root) and ``max_bytes`` (logical file bytes) -- is checked BEFORE any archive exists; it is a stat
snapshot, not live peak usage, archive size or a runtime quota.

:func:`pack` writes ONE stdlib gzip tar (PAX format, no binary needed) and returns
:class:`~dev_lab.dev.artefactindex.PackedOutputs`: each member's sha256 is hashed on the very stream fed
to ``tar.addfile``, a hard link becomes its own regular member, and a source whose identity changes
while it is read is :class:`~dev_lab.dev.artefactstores.OutputIntegrityRefused`. Index limits, when
given, are all three positive integers and refuse before the archive is published; the archive is
written to an owned temporary and linked into place no-replace, so an existing destination is never
touched. :func:`unpack` is the inverse.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING

from dev_lab.dev.artefactindex import (
    MemberFact,
    PackedOutputs,
    check_index_bytes,
    index_value,
    member_name,
    require_positive,
)
from dev_lab.dev.artefactstores import (
    ArtefactRefused,
    MissingOutput,
    OutputBudgetRefused,
    OutputIntegrityRefused,
    ref_of,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['collect', 'file_identity', 'pack', 'unpack']


def file_identity(item: os.stat_result) -> tuple[int, int, int, int]:
    """Device, inode, size and mtime: what an ordinary change to a file moves."""
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns


def _footprint(tree: Path, files: set[Path]) -> tuple[int, int]:
    """Entries (files plus unique parents through the root) and logical bytes of regular *files*."""
    root = tree.resolve(strict=True)
    size = 0
    directories: set[Path] = set()
    for path in files:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved != root / path.relative_to(tree):
            msg = f'declared output {path} is outside the work tree or traverses a symlink/alias'
            raise ArtefactRefused(msg)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            msg = f'declared output {path} is not a regular file'
            raise ArtefactRefused(msg)
        size += metadata.st_size
        parent = resolved.parent
        while parent != root:
            directories.add(parent)
            parent = parent.parent
        directories.add(root)
    return len(files) + len(directories), size


def collect(
    tree: Path, outputs: Sequence[str], *, max_entries: int | None = None, max_bytes: int | None = None
) -> list[Path]:
    """The files *outputs* name under *tree*, sorted; every declaration must match, within the budget.

    ``None`` declares no budget for that dimension; a bool or a negative number is refused.
    """
    for name, value in (('max_entries', max_entries), ('max_bytes', max_bytes)):
        if value is not None and (type(value) is not int or value < 0):
            msg = f'{name} must be a nonnegative integer or None'
            raise ArtefactRefused(msg)
    found: set[Path] = set()
    missing = []
    for pattern in outputs:
        pure = PurePosixPath(pattern)
        if pure.is_absolute() or '..' in pure.parts or ':' in pattern or '\\' in pattern:
            msg = f'declared output {pattern!r} must be a relative path or glob inside the work tree'
            raise ArtefactRefused(msg)
        matched = [path for path in tree.glob(pattern) if path.is_file()]
        if not matched:
            missing.append(pattern)
        found.update(matched)
    if missing:
        msg = f'{", ".join(missing)} matched nothing in {tree}'  # names first: a status description is short
        raise MissingOutput(msg)
    entries, size = _footprint(tree, found)
    if max_entries is not None and entries > max_entries:
        msg = f'declared outputs require {entries} entries, exceeding max_entries {max_entries}'
        raise OutputBudgetRefused(msg)
    if max_bytes is not None and size > max_bytes:
        msg = f'declared outputs require {size} bytes, exceeding max_bytes {max_bytes}'
        raise OutputBudgetRefused(msg)
    return sorted(found)


class _HashingReader:
    """The stream tar reads, hashed and counted as it is read."""

    def __init__(self, stream: IO[bytes]) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.digest.update(data)
        self.count += len(data)
        return data


def _tar_member(tar: tarfile.TarFile, tree: Path, path: Path, name: str) -> MemberFact:
    before = path.lstat()
    with path.open('rb') as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or file_identity(opened) != file_identity(before):
            msg = 'index source identity changed before tar read'
            raise OutputIntegrityRefused(msg)
        reader = _HashingReader(source)
        info = tarfile.TarInfo(name)
        info.size = opened.st_size
        info.mode = stat.S_IMODE(opened.st_mode)
        info.mtime = int(opened.st_mtime)
        try:
            tar.addfile(info, reader)
        except OSError as error:  # tar read fewer bytes than the size it recorded: the source shrank
            msg = f'index source {name} changed during tar read: {error}'
            raise OutputIntegrityRefused(msg) from error
        if reader.count != info.size or file_identity(os.fstat(source.fileno())) != file_identity(opened):
            msg = 'index source identity/length changed during tar read'
            raise OutputIntegrityRefused(msg)
    _footprint(tree, {path})
    if file_identity(path.lstat()) != file_identity(opened):
        msg = 'index source identity changed after tar read'
        raise OutputIntegrityRefused(msg)
    return MemberFact(name, reader.count, reader.digest.hexdigest())


def _limits(
    max_members: int | None, max_index_bytes: int | None, max_path_bytes: int | None
) -> tuple[int, int, int] | None:
    """The declared index limits, all three positive integers; ``None`` when none is declared."""
    if max_members is None and max_index_bytes is None and max_path_bytes is None:
        return None
    if max_members is None or max_index_bytes is None or max_path_bytes is None:
        msg = 'index budgets must be declared together as explicit positive integers'
        raise OutputBudgetRefused(msg)
    require_positive((max_members, max_index_bytes, max_path_bytes))
    return max_members, max_index_bytes, max_path_bytes


def _envelope() -> int:
    return len(json.dumps(index_value('0' * 64, []), sort_keys=True, ensure_ascii=True).encode())


def _members(
    tar: tarfile.TarFile, tree: Path, files: Sequence[Path], limits: tuple[int, int, int] | None
) -> list[MemberFact]:
    members: list[MemberFact] = []
    names: set[str] = set()
    index_size = _envelope()
    if limits is not None and index_size > limits[1]:
        msg = 'index envelope exceeds its serialized byte budget'
        raise OutputBudgetRefused(msg)
    for path in files:
        _footprint(tree, {path})
        name = member_name(path.relative_to(tree).as_posix(), limits[2] if limits else None)
        if name in names or (limits is not None and len(members) >= limits[0]):
            msg = 'index member count exceeded or duplicate member path'
            raise OutputBudgetRefused(msg)
        pending = MemberFact(name, path.lstat().st_size, '0' * 64)
        added = len(json.dumps(pending.manifest(), sort_keys=True, ensure_ascii=True).encode()) + 2 * bool(members)
        if limits is not None and index_size + added > limits[1]:
            msg = 'index exceeds its serialized byte budget'
            raise OutputBudgetRefused(msg)
        members.append(_tar_member(tar, tree, path, name))
        names.add(name)
        index_size += added
    return members


def pack(
    tree: Path,
    files: Sequence[Path],
    dest: Path,
    *,
    max_members: int | None = None,
    max_index_bytes: int | None = None,
    max_path_bytes: int | None = None,
) -> PackedOutputs:
    """One gzip tar of *files* (named relative to *tree*) at *dest*, which must not exist, and its index.

    The temporary is fsynced and linked no-replace; the check/reopen race on a source is narrowed, not
    eliminated, and directory fsync (power-loss durability) is not promised.
    """
    if os.path.lexists(dest):
        msg = f'{dest} already exists'
        raise FileExistsError(msg)
    limits = _limits(max_members, max_index_bytes, max_path_bytes)
    _footprint(tree, set(files))
    dest.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f'.{dest.name}.', suffix='.partial', dir=dest.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with tarfile.open(temporary, mode='w:gz', format=tarfile.PAX_FORMAT) as tar:
            members = _members(tar, tree, files, limits)
        with temporary.open('r+b') as archive:
            os.fsync(archive.fileno())
        sealed = ref_of('', '', temporary)
        if limits is not None:
            check_index_bytes(sealed.sha256, members, limits[1])
        os.link(temporary, dest)  # fails rather than replace another publisher's archive
    finally:
        temporary.unlink(missing_ok=True)
    return PackedOutputs(dest, tuple(members), sealed.sha256, sealed.bytes)


def unpack(archive: Path, dest: Path) -> Path:
    """The inverse of :func:`pack`: every member of *archive* under *dest* (a member leaving it is refused)."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode='r:gz') as tar:
        tar.extractall(dest, filter='data')
    return dest
