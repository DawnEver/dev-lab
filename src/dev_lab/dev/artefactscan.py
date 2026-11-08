"""VERIFYING A PACKED ARCHIVE -- every payload against its complete member index, without extracting.

:func:`verify_newpack_stream` reads an already decompressed tar stream and accepts only what
:func:`dev_lab.dev.artefactpack.pack` emits: regular payloads, each optionally preceded by ONE local PAX
header holding only ``path``, ``size`` and an integer ``mtime``. Every payload must match the index's
order, path, length and sha256, the unselected ones too. Header checksums, zero padding, the end
markers and the zero tail are checked inside the uncompressed scan budget; a PAX header's size is
checked before its body is read; payloads are hashed in bounded chunks. Links, GNU and global
extensions, extra members and malformed metadata are refused; there is no legacy fallback.

:func:`verify_newpack_archive` does it for a local gzip archive and its Ref: path aliases and
non-regular sources are refused, the compressed length and sha256 are authenticated in bounded chunks
BEFORE anything is decompressed, the same opened file is rewound and decompressed in process, and the
file's identity must not have moved by the end. Two input passes, not a transport protocol; stat checks
catch ordinary drift, not an adversary restoring every attribute. Malformed or missing bytes never
earn a verified return. The limits do not bound total Python RSS, and nothing is downloaded,
materialized or marked complete here (:mod:`dev_lab.dev.artefactrestore` materializes).
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import stat
import tarfile
import zlib
from contextlib import AbstractContextManager, nullcontext
from typing import IO, TYPE_CHECKING, Final, Protocol

from dev_lab.dev.artefactindex import MemberFact, check_index_bytes, require_positive, validate_ref, validated_member
from dev_lab.dev.artefactpack import file_identity
from dev_lab.dev.artefactstores import ArtefactRefused, OutputBudgetRefused, Ref

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'MemberSink',
    'check_compressed_budget',
    'validated_facts',
    'verified_archive',
    'verify_newpack_archive',
    'verify_newpack_stream',
    'write_all',
]

_PAX_INTEGER_DIGITS: Final = 20  # a signed 64-bit decimal, its sign included
_CHUNK: Final = 65536
_BLOCK: Final = 512


class MemberSink(Protocol):
    """Where a verified payload's bytes go while it is scanned: a stream for a selected member, else None."""

    def member(self, fact: MemberFact) -> AbstractContextManager[IO[bytes] | None]:
        """The open output for *fact*, or ``None`` when it is not written."""
        ...


def write_all(stream: IO[bytes], data: bytes) -> None:
    """Write all of *data*, through short writes; a stream that accepts nothing is an OSError."""
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if type(written) is not int or not 0 < written <= len(view):
            msg = 'materialization output did not accept a bounded write'
            raise OSError(msg)
        view = view[written:]


def _pax_integer(key: str, value: str) -> None:
    pattern = r'0|[1-9][0-9]*' if key == 'size' else r'0|-?[1-9][0-9]*'
    if len(value) > _PAX_INTEGER_DIGITS or re.fullmatch(pattern, value) is None or not -(2**63) <= int(value) < 2**63:
        msg = 'newpack invalid PAX integer'
        raise ArtefactRefused(msg)


def _pax(data: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    offset = 0
    while offset < len(data):
        space = data.find(b' ', offset)
        token = data[offset:space] if space >= 0 else b''
        if not token.isdigit() or token.startswith(b'0') or len(token) > _PAX_INTEGER_DIGITS:
            msg = 'newpack invalid PAX record length'
            raise ArtefactRefused(msg)
        end = offset + int(token)
        if end > len(data) or end <= space + 1 or data[end - 1 : end] != b'\n':
            msg = 'newpack truncated PAX record'
            raise ArtefactRefused(msg)
        try:
            key, value = data[space + 1 : end - 1].decode('utf-8', 'strict').split('=', 1)
        except (ValueError, UnicodeError) as error:
            msg = 'newpack invalid PAX UTF-8/field'
            raise ArtefactRefused(msg) from error
        if key not in ('path', 'size', 'mtime') or key in fields:
            msg = 'newpack unsupported or duplicate PAX key'
            raise ArtefactRefused(msg)
        if key != 'path':
            _pax_integer(key, value)
        fields[key] = value
        offset = end
    if not fields:
        msg = 'newpack empty PAX header'
        raise ArtefactRefused(msg)
    return fields


def validated_facts(
    expected: tuple[MemberFact, ...], max_members: int, max_index_bytes: int, max_path_bytes: int
) -> tuple[MemberFact, ...]:
    """*expected* revalidated as a complete index within its three limits."""
    require_positive((max_members, max_index_bytes, max_path_bytes))
    if len(expected) > max_members:
        msg = 'newpack member budget exceeded'
        raise OutputBudgetRefused(msg)
    facts = []
    for fact in expected:
        if not isinstance(fact, MemberFact):
            msg = 'newpack expected an indexed member'
            raise ArtefactRefused(msg)
        facts.append(validated_member(fact.manifest(), max_path_bytes))
    if len({fact.path for fact in facts}) != len(facts):
        msg = 'newpack duplicate expected member'
        raise ArtefactRefused(msg)
    check_index_bytes('0' * 64, facts, max_index_bytes)
    return tuple(facts)


class _Scan:
    """One bounded sequential read of a decompressed newpack stream."""

    def __init__(self, stream: IO[bytes], max_metadata_bytes: int, max_uncompressed_bytes: int) -> None:
        require_positive((max_metadata_bytes, max_uncompressed_bytes))
        self.stream, self.metadata, self.budget, self.consumed = stream, max_metadata_bytes, max_uncompressed_bytes, 0

    def read(self, size: int) -> bytes:
        if size > self.budget - self.consumed:
            msg = 'newpack uncompressed scan budget exceeded'
            raise OutputBudgetRefused(msg)
        result = bytearray()
        while len(result) < size:
            chunk = self.stream.read(size - len(result))
            if not chunk:
                msg = 'newpack truncated stream'
                raise ArtefactRefused(msg)
            if len(chunk) > size - len(result):
                msg = 'newpack stream violated bounded read'
                raise ArtefactRefused(msg)
            result.extend(chunk)
        self.consumed += size
        return bytes(result)

    def header(self) -> tarfile.TarInfo:
        block = self.read(_BLOCK)
        if block[257:265] != tarfile.POSIX_MAGIC:
            msg = 'newpack requires POSIX headers, not legacy/GNU format'
            raise ArtefactRefused(msg)
        try:
            return tarfile.TarInfo.frombuf(block, 'utf-8', 'strict')
        except (tarfile.HeaderError, ValueError, UnicodeError) as error:
            msg = 'newpack invalid tar header'
            raise ArtefactRefused(msg) from error

    def padding(self, size: int) -> None:
        if any(self.read((-size) % _BLOCK)):
            msg = 'newpack nonzero payload padding'
            raise ArtefactRefused(msg)

    def described(self, fact: MemberFact) -> int:
        """The next member's header(s), checked against *fact*; its payload size."""
        info = self.header()
        pax: dict[str, str] = {}
        if info.type == tarfile.XHDTYPE:
            if not 0 < info.size <= self.metadata:
                msg = 'newpack PAX metadata budget exceeded'
                raise OutputBudgetRefused(msg)
            pax = _pax(self.read(info.size))
            self.padding(info.size)
            info = self.header()
        if info.type != tarfile.REGTYPE or info.linkname or info.uid != 0 or info.gid != 0:
            msg = 'newpack requires regular payloads with default ownership'
            raise ArtefactRefused(msg)
        size = int(pax['size']) if 'size' in pax else info.size
        if pax.get('path', info.name) != fact.path or size != fact.logical_bytes or size < 0:
            msg = 'newpack member order/path/size differs from index'
            raise ArtefactRefused(msg)
        if size + (-size) % _BLOCK > self.budget - self.consumed:  # refused before any of the body is read
            msg = 'newpack payload exceeds uncompressed scan budget'
            raise OutputBudgetRefused(msg)
        return size

    def tail(self) -> None:
        if any(self.read(2 * _BLOCK)):
            msg = 'newpack missing end markers or extra member'
            raise ArtefactRefused(msg)
        while chunk := self.stream.read(min(_CHUNK, self.budget - self.consumed + 1)):
            if len(chunk) > self.budget - self.consumed:
                msg = 'newpack trailing scan budget exceeded'
                raise OutputBudgetRefused(msg)
            self.consumed += len(chunk)
            if any(chunk):
                msg = 'newpack nonzero trailing bytes'
                raise ArtefactRefused(msg)
        if self.consumed % _BLOCK:
            msg = 'newpack incomplete trailing block'
            raise ArtefactRefused(msg)


def _scan(
    stream: IO[bytes],
    facts: tuple[MemberFact, ...],
    max_metadata_bytes: int,
    max_uncompressed_bytes: int,
    output: MemberSink | None,
) -> tuple[MemberFact, ...]:
    scan = _Scan(stream, max_metadata_bytes, max_uncompressed_bytes)
    for fact in facts:
        remaining = scan.described(fact)
        size = remaining
        digest = hashlib.sha256()
        with output.member(fact) if output is not None else nullcontext(None) as sink:
            while remaining:
                chunk = scan.read(min(remaining, _CHUNK))
                digest.update(chunk)
                if sink is not None:
                    write_all(sink, chunk)
                remaining -= len(chunk)
        if digest.hexdigest() != fact.sha256:
            msg = 'newpack payload digest differs from index'
            raise ArtefactRefused(msg)
        scan.padding(size)
    scan.tail()
    return facts


def verify_newpack_stream(
    stream: IO[bytes],
    expected: tuple[MemberFact, ...],
    *,
    max_members: int,
    max_index_bytes: int,
    max_path_bytes: int,
    max_metadata_bytes: int,
    max_uncompressed_bytes: int,
) -> tuple[MemberFact, ...]:
    """Verify an already decompressed newpack stream against its complete index, writing nothing."""
    facts = validated_facts(expected, max_members, max_index_bytes, max_path_bytes)
    return _scan(stream, facts, max_metadata_bytes, max_uncompressed_bytes, None)


def check_compressed_budget(ref: Ref, maximum: int) -> None:
    """Refuse a Ref whose archive is over *maximum* compressed bytes."""
    if ref.bytes > maximum:
        msg = 'newpack compressed byte budget exceeded'
        raise OutputBudgetRefused(msg)


def _authenticate(source: IO[bytes], ref: Ref, opened: os.stat_result) -> None:
    digest = hashlib.sha256()
    count = 0
    while chunk := source.read(min(_CHUNK, ref.bytes - count + 1)):
        count += len(chunk)
        if count > ref.bytes:
            msg = 'newpack compressed source grew during authentication'
            raise ArtefactRefused(msg)
        digest.update(chunk)
    if (
        count != ref.bytes
        or digest.hexdigest() != ref.sha256
        or file_identity(os.fstat(source.fileno())) != file_identity(opened)
    ):
        msg = 'newpack compressed authentication failed'
        raise ArtefactRefused(msg)


def _regular(absolute: Path) -> os.stat_result:
    if absolute.resolve(strict=True) != absolute:
        msg = 'newpack archive alias refused'
        raise ArtefactRefused(msg)
    metadata = absolute.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        msg = 'newpack archive must be a regular file'
        raise ArtefactRefused(msg)
    return metadata


def verified_archive(
    path: Path,
    ref: Ref,
    facts: tuple[MemberFact, ...],
    *,
    max_compressed_bytes: int,
    max_metadata_bytes: int,
    max_uncompressed_bytes: int,
    output: MemberSink | None,
) -> tuple[MemberFact, ...]:
    """Authenticate *path* against *ref*, then scan its decompressed stream into *output* (validated *facts*)."""
    validate_ref(ref)
    require_positive((max_compressed_bytes, max_metadata_bytes, max_uncompressed_bytes))
    check_compressed_budget(ref, max_compressed_bytes)
    absolute = path.absolute()
    before = _regular(absolute)
    with absolute.open('rb') as source:
        opened = os.fstat(source.fileno())
        if file_identity(before) != file_identity(opened) or opened.st_size != ref.bytes:
            msg = 'newpack compressed identity/length differs from Ref'
            raise ArtefactRefused(msg)
        _authenticate(source, ref, opened)
        source.seek(0)
        try:
            with gzip.GzipFile(fileobj=source, mode='rb') as stream:
                verified = _scan(stream, facts, max_metadata_bytes, max_uncompressed_bytes, output)
        except (gzip.BadGzipFile, EOFError, zlib.error) as error:
            msg = f'newpack decompression failed: {error}'
            raise ArtefactRefused(msg) from error
        if file_identity(os.fstat(source.fileno())) != file_identity(opened) or file_identity(
            _regular(absolute)
        ) != file_identity(opened):
            msg = 'newpack compressed source identity changed during verification'
            raise ArtefactRefused(msg)
    return verified


def verify_newpack_archive(
    path: Path,
    ref: Ref,
    expected: tuple[MemberFact, ...],
    *,
    max_compressed_bytes: int,
    max_members: int,
    max_index_bytes: int,
    max_path_bytes: int,
    max_metadata_bytes: int,
    max_uncompressed_bytes: int,
) -> tuple[MemberFact, ...]:
    """Authenticate one local archive against *ref* and verify it against its COMPLETE index, read-only."""
    facts = validated_facts(expected, max_members, max_index_bytes, max_path_bytes)
    return verified_archive(
        path,
        ref,
        facts,
        max_compressed_bytes=max_compressed_bytes,
        max_metadata_bytes=max_metadata_bytes,
        max_uncompressed_bytes=max_uncompressed_bytes,
        output=None,
    )
