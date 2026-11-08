"""MATERIALIZING A SELECTION -- chosen members of a verified archive into a fresh owned directory.

:func:`materialize_newpack_archive` needs an existing, trusted, non-alias parent and returns a newly
claimed unique directory under it. It runs the one verifier (:func:`dev_lab.dev.artefactscan.verified_archive`),
not a second extractor: every payload is verified, the unselected ones too, and only selected regular
files are opened create-new and written in bounded chunks.

THE BUDGET IS THE WHOLE FOOTPRINT. Before the directory is claimed, ``max_entries`` counts its root,
unique parents, selected files and ONE ``materialization-complete.json`` receipt, and ``max_bytes`` the
selected payloads plus the exact serialized receipt -- so an empty selection still costs two entries and
still verifies the whole archive. Windows device names, forbidden characters, trailing dots or spaces
and a receipt collision are refused rather than renamed.

THE RECEIPT IS WRITTEN LAST. Schema ``lab-commons-materialized-v1``, the archive Ref and the selected
paths, written exclusively after full decoded verification and the final source identity checks, and
after every output's identity is re-checked. A directory without its receipt is incomplete, never done.

FAILURE REMOVES ONLY WHAT IT OWNS. Cleanup deletes the files and empty directories registered in its
ownership ledger that still match; a foreign replacement survives and the failure says cleanup was
incomplete. Not directory-atomic, not power-loss durable; hostile ancestor replacement, every Unicode
alias, permission/timestamp restoration, legacy archives and resume are not handled.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Final, cast

from dev_lab.dev.artefactindex import MemberFact, require_positive, select_members, validate_ref
from dev_lab.dev.artefactpack import file_identity
from dev_lab.dev.artefactscan import check_compressed_budget, validated_facts, verified_archive, write_all
from dev_lab.dev.artefactstores import ArtefactRefused, OutputBudgetRefused, Ref

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ['RECEIPT', 'RECEIPT_SCHEMA', 'materialize_newpack_archive']

RECEIPT: Final = 'materialization-complete.json'
RECEIPT_SCHEMA: Final = 'lab-commons-materialized-v1'
_DEVICES: Final = frozenset(
    {
        'CON',
        'PRN',
        'AUX',
        'NUL',
        'CONIN$',
        'CONOUT$',
        *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10)),
    }
)
_SUPERSCRIPT_DEVICE: Final = re.compile(r'(COM|LPT)[¹²³]')


def _portable(selected: tuple[MemberFact, ...]) -> None:
    for member in selected:
        for component in PurePosixPath(member.path).parts:
            stem = component.split('.', 1)[0].upper()
            if (
                component.endswith(('.', ' '))
                or any(char in '<>"|?*' for char in component)
                or stem in _DEVICES
                or _SUPERSCRIPT_DEVICE.fullmatch(stem)
            ):
                msg = f'materialization target component is not portable: {component!r}'
                raise ArtefactRefused(msg)
        if member.path.split('/', 1)[0].casefold() == RECEIPT.casefold():
            msg = 'materialization selection collides with completion receipt'
            raise ArtefactRefused(msg)


def _kind(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


class _Owned:
    """The fresh root and what this run created under it; its ledger never authorizes a foreign deletion."""

    def __init__(self, root: Path, selected: tuple[MemberFact, ...]) -> None:
        self.root = root
        self.selected = {member.path for member in selected}
        self.created: dict[Path, tuple[int, int, int]] = {root: _kind(root.lstat())}
        self.seals: dict[Path, tuple[int, int, int, int]] = {}

    def _owned(self, path: Path) -> bool:
        try:
            if path.resolve(strict=True) != path:
                return False
            for ancestor in (path, *path.parents):
                if ancestor == self.root.parent:
                    break
                if self.created.get(ancestor) != _kind(ancestor.lstat()):
                    return False
        except OSError:
            return False
        return True

    def _parents(self, path: Path) -> None:
        for parent in reversed(path.parents):
            if not parent.is_relative_to(self.root):
                continue
            if parent not in self.created:
                if not self._owned(parent.parent):
                    msg = 'materialization parent identity changed'
                    raise ArtefactRefused(msg)
                parent.mkdir()
                self.created[parent] = _kind(parent.lstat())
            elif not self._owned(parent):
                msg = 'materialization directory identity changed'
                raise ArtefactRefused(msg)

    @contextmanager
    def member(self, fact: MemberFact) -> Iterator[IO[bytes] | None]:
        """A create-new stream for a selected *fact*, else ``None``."""
        if fact.path not in self.selected:
            yield None
            return
        path = self.root / fact.path
        self._parents(path)
        with path.open('xb') as stream:
            self.created[path] = _kind(os.fstat(stream.fileno()))
            yield stream
            stream.flush()
            self.seals[path] = file_identity(os.fstat(stream.fileno()))
        if not self._owned(path):
            msg = 'materialization output identity changed'
            raise ArtefactRefused(msg)

    def finish(self, receipt: bytes) -> None:
        """Re-check every output, then write the receipt -- last."""
        for path in self.created:
            if not self._owned(path) or (path in self.seals and file_identity(path.lstat()) != self.seals[path]):
                msg = 'materialization output changed before completion'
                raise ArtefactRefused(msg)
        self.selected.add(RECEIPT)
        with self.member(MemberFact(RECEIPT, len(receipt), hashlib.sha256(receipt).hexdigest())) as stream:
            write_all(cast('IO[bytes]', stream), receipt)

    def cleanup(self) -> bool:
        """Remove what is still ours, newest first; whether everything owned is gone."""
        complete = True
        for path in reversed(self.created):
            if not os.path.lexists(path):
                continue
            if not self._owned(path):
                complete = False
                continue
            try:
                path.rmdir() if self.created[path][2] == stat.S_IFDIR else path.unlink()
            except OSError:
                complete = False
        return complete


def _receipt(ref: Ref, selected: tuple[MemberFact, ...], max_entries: int, max_bytes: int) -> bytes:
    receipt = json.dumps(
        {'schema': RECEIPT_SCHEMA, 'archive': ref.manifest(), 'selected_paths': [member.path for member in selected]},
        sort_keys=True,
        ensure_ascii=True,
    ).encode()
    parents = {parent for member in selected for parent in PurePosixPath(member.path).parents if str(parent) != '.'}
    entries = 2 + len(selected) + len(parents)
    if entries > max_entries or sum(member.logical_bytes for member in selected) + len(receipt) > max_bytes:
        msg = 'materialization expanded budget includes root and completion receipt'
        raise OutputBudgetRefused(msg)
    return receipt


def materialize_newpack_archive(
    path: Path,
    ref: Ref,
    complete_expected: tuple[MemberFact, ...],
    explicit_paths: Sequence[str],
    destination_parent: Path,
    *,
    max_compressed_bytes: int,
    max_members: int,
    max_index_bytes: int,
    max_path_bytes: int,
    max_metadata_bytes: int,
    max_uncompressed_bytes: int,
    max_entries: int,
    max_bytes: int,
    case_sensitive: bool,
) -> Path:
    """Restore *explicit_paths* of the archive at *path* into a fresh owned directory; its receipt last."""
    validate_ref(ref)
    require_positive((max_compressed_bytes, max_metadata_bytes, max_uncompressed_bytes))
    facts = validated_facts(complete_expected, max_members, max_index_bytes, max_path_bytes)
    check_compressed_budget(ref, max_compressed_bytes)
    selected = select_members(
        facts,
        explicit_paths,
        max_entries=max_entries,
        max_bytes=max_bytes,
        max_path_bytes=max_path_bytes,
        case_sensitive=case_sensitive,
    )
    _portable(selected)
    receipt = _receipt(ref, selected, max_entries, max_bytes)
    parent = destination_parent.absolute()
    if parent.resolve(strict=True) != parent or not parent.is_dir():
        msg = 'materialization requires an existing trusted nonalias destination parent'
        raise ArtefactRefused(msg)
    root = Path(tempfile.mkdtemp(prefix='materialized-', dir=parent))
    output = _Owned(root, selected)
    try:
        verified_archive(
            path,
            ref,
            facts,
            max_compressed_bytes=max_compressed_bytes,
            max_metadata_bytes=max_metadata_bytes,
            max_uncompressed_bytes=max_uncompressed_bytes,
            output=output,
        )
        output.finish(receipt)
    except BaseException as error:
        if not output.cleanup():
            msg = f'materialization failed; cleanup incomplete for owned root {root}'
            raise ArtefactRefused(msg) from error
        raise
    return root
