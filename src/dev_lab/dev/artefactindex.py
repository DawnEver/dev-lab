"""THE MEMBER INDEX -- what a stored archive holds, named in the run record without opening the archive.

A packed archive's members are measured from the bytes fed to tar (:class:`MemberFact`: path, logical
bytes, sha256), so the record can say what an archive holds. The record carries them keyed by the
archive's own sha256 under ``artefact_indexes`` (schema :data:`SCHEMA`) next to its unchanged four-field
``artefacts`` Ref (:meth:`StoredOutputs.index`).

EVERY INDEX IS BOUNDED, AND THE BOUNDS ARE DECLARED. ``max_members``, ``max_index_bytes`` (the exact
record serialization of the ``{archive_sha: index}`` value, ``json.dumps(sort_keys=True,
ensure_ascii=True)``) and ``max_path_bytes`` (UTF-8 bytes of one member path) are explicit positive
integers; there are no numeric defaults. A member path refuses traversal, backslashes, colons and
control characters and allows Unicode (:func:`member_name`).

READ-ONLY QUERIES. :func:`catalogue` validates ONE requested Ref's declaration and its index in an
already-parsed record and returns its member facts; a record without that index is UNINDEXED, refused,
never an empty catalogue. :func:`select_members` picks explicit paths under an expanded entry/byte
budget, refusing unknown and duplicate paths, file/directory prefix collisions and -- when not
case-sensitive -- case-fold aliases. Neither reads, downloads or verifies an archive.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from dev_lab.dev.artefactstores import FOLDER, FORGE, RCLONE, ArtefactRefused, OutputBudgetRefused, Ref

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    'SCHEMA',
    'MemberFact',
    'PackedOutputs',
    'StoredOutputs',
    'catalogue',
    'check_index_bytes',
    'index_value',
    'member_name',
    'require_positive',
    'select_members',
    'validate_ref',
    'validated_member',
]

SCHEMA: Final = 'lab-commons-members-v1'
_SHA256: Final = re.compile('[0-9a-f]{64}')
_CONTROL_LIMIT: Final = 32
_DELETE_CONTROL: Final = 127
_BACKENDS: Final = (FORGE, RCLONE, FOLDER)


@dataclass(frozen=True)
class MemberFact:
    """One regular archive payload, measured from the bytes fed to tar."""

    path: str
    logical_bytes: int
    sha256: str

    def manifest(self) -> dict[str, object]:
        """The regular-file member identity the record carries; no source path, no guessed role."""
        return {'path': self.path, 'logical_bytes': self.logical_bytes, 'sha256': self.sha256, 'type': 'file'}


@dataclass(frozen=True)
class PackedOutputs:
    """A packed local archive, its whole-archive identity, and the member identities measured packing it."""

    path: Path
    members: tuple[MemberFact, ...]
    archive_sha256: str
    compressed_bytes: int


@dataclass(frozen=True)
class StoredOutputs:
    """A stored archive's Ref and the exact member identities it holds."""

    ref: Ref
    members: tuple[MemberFact, ...]

    def index(self) -> dict[str, object]:
        """The record's ``artefact_indexes`` value, keyed by the stored archive's sha256."""
        return index_value(self.ref.sha256, self.members)


def index_value(digest: str, members: Sequence[MemberFact]) -> dict[str, object]:
    """``{digest: {schema, members}}`` -- the one shape the record carries and every byte budget measures."""
    return {digest: {'schema': SCHEMA, 'members': [member.manifest() for member in members]}}


def check_index_bytes(digest: str, members: Sequence[MemberFact], maximum: int) -> None:
    """Refuse an index whose record serialization is over *maximum* bytes."""
    if len(json.dumps(index_value(digest, members), sort_keys=True, ensure_ascii=True).encode()) > maximum:
        msg = 'index exceeds its serialized byte budget'
        raise OutputBudgetRefused(msg)


def require_positive(limits: Sequence[object]) -> None:
    """Every limit is an explicit positive integer (a bool is not one)."""
    if any(type(value) is not int or value < 1 for value in limits):
        msg = 'index budgets must be explicit positive integers'
        raise OutputBudgetRefused(msg)


def member_name(name: str, maximum: int | None) -> str:
    """*name* when it is a safe relative POSIX member path within *maximum* UTF-8 bytes (``None``: unbounded)."""
    relative = PurePosixPath(name)
    try:
        encoded = len(name.encode('utf-8'))
    except UnicodeError as error:
        msg = 'index member path is not valid UTF-8'
        raise OutputBudgetRefused(msg) from error
    if (
        not name
        or name == '.'
        or str(relative) != name
        or relative.is_absolute()
        or '..' in relative.parts
        or '\\' in name
        or ':' in name
        or any(ord(char) < _CONTROL_LIMIT or ord(char) == _DELETE_CONTROL for char in name)
        or (maximum is not None and encoded > maximum)
    ):
        msg = f'index member path is unsafe or exceeds its path budget: {name!r}'
        raise OutputBudgetRefused(msg)
    return name


def validated_member(value: object, maximum: int) -> MemberFact:
    """The :class:`MemberFact` a record's member entry *value* declares, or a refusal naming the catalogue."""
    if (
        not isinstance(value, dict)
        or set(value) != {'path', 'logical_bytes', 'sha256', 'type'}
        or value['type'] != 'file'
        or type(value['path']) is not str
        or type(value['logical_bytes']) is not int
        or value['logical_bytes'] < 0
        or type(value['sha256']) is not str
        or _SHA256.fullmatch(value['sha256']) is None
    ):
        msg = 'catalogue has an invalid regular member identity'
        raise ArtefactRefused(msg)
    try:
        name = member_name(value['path'], maximum)
    except OutputBudgetRefused as error:
        msg = f'catalogue member path refused: {error}'
        raise ArtefactRefused(msg) from error
    return MemberFact(name, value['logical_bytes'], value['sha256'])


def validate_ref(ref: Ref) -> None:
    """Refuse a Ref that is not a well-typed identity on a known backend."""
    if (
        not isinstance(ref, Ref)
        or type(ref.bytes) is not int
        or ref.bytes < 0
        or ref.backend not in _BACKENDS
        or type(ref.key) is not str
        or not ref.key
        or type(ref.sha256) is not str
        or _SHA256.fullmatch(ref.sha256) is None
    ):
        msg = 'requested Ref identity is invalid'
        raise ArtefactRefused(msg)


def _declared_index(record: dict[str, object], ref: Ref, max_members: int) -> list[object]:
    declarations = record.get('artefacts', [])
    if not isinstance(declarations, list):
        msg = 'catalogue archive declarations must be a list'
        raise ArtefactRefused(msg)
    matches = [
        entry
        for entry in declarations
        if isinstance(entry, dict) and entry.get('backend') == ref.backend and entry.get('ref') == ref.key
    ]
    if len(matches) != 1 or matches[0] != ref.manifest() or type(matches[0]['bytes']) is not int:
        msg = 'catalogue requested exact Ref must occur once'
        raise ArtefactRefused(msg)
    indexes = record.get('artefact_indexes', {})
    if not isinstance(indexes, dict) or ref.sha256 not in indexes:
        msg = 'catalogue is unindexed for the requested archive'
        raise ArtefactRefused(msg)
    index = indexes[ref.sha256]
    if (
        not isinstance(index, dict)
        or set(index) != {'schema', 'members'}
        or index['schema'] != SCHEMA
        or not isinstance(index['members'], list)
        or len(index['members']) > max_members
    ):
        msg = 'catalogue index schema/member budget differs'
        raise ArtefactRefused(msg)
    return index['members']


def catalogue(
    record: dict[str, object], ref: Ref, *, max_members: int, max_index_bytes: int, max_path_bytes: int
) -> tuple[MemberFact, ...]:
    """The member facts *record* declares for *ref*, validated; the archive itself is never read.

    Only the queried declaration and its index are validated -- other archives, other record fields and
    the JSON load that produced *record* are not.
    """
    try:
        require_positive((max_members, max_index_bytes, max_path_bytes))
        validate_ref(ref)
        members = tuple(validated_member(value, max_path_bytes) for value in _declared_index(record, ref, max_members))
        if len({member.path for member in members}) != len(members):
            msg = 'catalogue contains duplicate member paths'
            raise ArtefactRefused(msg)
        check_index_bytes(ref.sha256, members, max_index_bytes)
    except OutputBudgetRefused as error:
        msg = f'catalogue budget refused: {error}'
        raise ArtefactRefused(msg) from error
    return members


def _validate_selection(members: tuple[MemberFact, ...], maximum: int) -> None:
    if type(maximum) is not int or maximum < 1:
        msg = 'selection requires a positive integer path byte budget'
        raise ArtefactRefused(msg)
    for member in members:
        if not isinstance(member, MemberFact):
            msg = 'selection requires complete MemberFact values'
            raise ArtefactRefused(msg)
        try:
            validated_member(member.manifest(), maximum)
        except ArtefactRefused as error:
            msg = f'selection member identity refused: {error}'
            raise ArtefactRefused(msg) from error


def select_members(
    members: tuple[MemberFact, ...],
    paths: Sequence[str],
    *,
    max_entries: int,
    max_bytes: int,
    max_path_bytes: int,
    case_sensitive: bool,
) -> tuple[MemberFact, ...]:
    """The members *paths* name, within an expanded entry and logical-byte budget.

    Entries count the fresh root, unique parents and files -- zero for an empty selection; bytes count
    each selected file once. Every supplied fact is revalidated, a constructed one too. The case-fold
    check is not Windows reserved-name, Unicode-normalization or long-path validation.
    """
    if type(case_sensitive) is not bool or any(
        type(value) is not int or value < 0 for value in (max_entries, max_bytes)
    ):
        msg = 'selection requires boolean case policy and nonnegative integer budgets'
        raise ArtefactRefused(msg)
    _validate_selection(members, max_path_bytes)
    by_path = {member.path: member for member in members}
    if len(by_path) != len(members) or len(set(paths)) != len(paths) or any(path not in by_path for path in paths):
        msg = 'selection has duplicate/unknown paths or invalid catalogue'
        raise ArtefactRefused(msg)
    selected = tuple(by_path[path] for path in paths)
    entries: dict[str, tuple[str, str]] = {}
    for member in selected:
        components = PurePosixPath(member.path).parts
        for depth in range(len(components) + 1):
            name = '/'.join(components[:depth])
            kind = 'file' if depth == len(components) else 'directory'
            key = name if case_sensitive else name.casefold()
            if key in entries and entries[key] != (name, kind):
                msg = 'selection has case or file/directory collisions'
                raise ArtefactRefused(msg)
            if key not in entries and len(entries) >= max_entries:
                msg = 'selection exceeds expanded entry budget'
                raise ArtefactRefused(msg)
            entries[key] = (name, kind)
    if sum(member.logical_bytes for member in selected) > max_bytes:
        msg = 'selection exceeds expanded byte budget'
        raise ArtefactRefused(msg)
    return selected
