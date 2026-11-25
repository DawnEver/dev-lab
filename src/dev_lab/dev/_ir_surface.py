"""THE IR SURFACE TEMPLATE, copied verbatim beside ``_ir_runtime.py`` into each consumer package (git-ignored).

Split out of the runtime template (2026-11-25, MODULE-SIZE-ALARM) at its own seam: the runtime validates and
writes canonical JSON; this one is the stored envelope and the methods every generated record class carries.
It imports nothing from dev-lab, only its sibling.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ._ir_runtime import _GENERATE, IRValidationError, canonical, from_tree, refuse_read, to_tree

_MIGRATE = 'python -m dev_lab.dev.irschema migrate'


# -- the stored envelope ------------------------------------------------------------------------------------


def _major(version: str) -> int:
    return int(version.split('.', maxsplit=1)[0])


def envelope(record: object) -> bytes:
    cls = type(record)
    return canonical({'record': cls._ir_name, 'schema_version': cls._ir_version, 'value': to_tree(record)})


def read_envelope(cls: type, data: bytes, where: str) -> object:
    """The record stored in *data*, refused by name when its version or shape is not this reader's."""
    try:
        stored = json.loads(data)
        name, version, value = stored['record'], stored['schema_version'], stored['value']
    except (ValueError, KeyError, TypeError) as error:
        refuse_read(f'{where}: not an IR envelope ({error})')
    if name != cls._ir_name:
        refuse_read(f'{where}: holds {name}, not {cls._ir_name}')
    ours = cls._ir_version
    if _major(version) < _major(ours):
        refuse_read(f'IR-OLD-RECORD: {where}: schema_version {version}, current {ours} -- {_MIGRATE} {where}')
    if _major(version) > _major(ours):
        refuse_read(f'IR-STALE-GENERATED: {where}: schema_version {version} is newer than {ours} -- {_GENERATE}')
    try:
        return from_tree(cls, value)
    except IRValidationError as error:
        if 'IR-UNKNOWN-FIELD' in error.got:
            door = _GENERATE if version.split('.')[:2] > ours.split('.')[:2] else f'{_MIGRATE} {where}'
            refuse_read(f'IR-UNKNOWN-FIELD: {where}: {error} -- {door}')
        raise


# -- the record surface -------------------------------------------------------------------------------------


def record_eq(self: object, other: object) -> bool:
    return type(self) is type(other) and canonical(to_tree(self)) == canonical(to_tree(other))


def record_hash(self: object) -> int:
    return hash(canonical(to_tree(self)))


def to_json(self: object) -> bytes:
    return canonical(to_tree(self))


def content_hash(self: object) -> str:
    return hashlib.sha256(to_json(self)).hexdigest()


def dump(self: object, path: str | Path) -> None:
    Path(path).write_bytes(envelope(self))


def surface(cls: type) -> type:
    """Attach the shared methods to a generated record class."""
    cls.__eq__ = record_eq
    cls.__hash__ = record_hash
    cls.to_json = to_json
    cls.content_hash = content_hash
    cls.dump = dump
    cls.from_json = classmethod(lambda c, data: from_tree(c, json.loads(data)))
    cls.load = classmethod(lambda c, path: read_envelope(c, Path(path).read_bytes(), str(path)))
    return cls
