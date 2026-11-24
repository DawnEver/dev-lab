"""THE IR RUNTIME TEMPLATE, copied verbatim into each consumer package as ``_ir_runtime.py`` (git-ignored).

:mod:`dev_lab.dev.irpython` writes the copy, so this file imports nothing from dev-lab.

The one runtime every generated IR module of this package shares: validation driven by each record's
field table, the canonical JSON, the stored envelope and the import-time freshness check. numpy only.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import math
import tomllib
from pathlib import Path
from typing import NamedTuple, NoReturn

import numpy as np

_I64 = (-(2**63), 2**63 - 1)
_GENERATE = 'python -m dev_lab.dev.irschema generate'
_MIGRATE = 'python -m dev_lab.dev.irschema migrate'


class IRValidationError(ValueError):
    """``<path>: expected <x>, got <y>``; *path* is dotted from the top record."""

    def __init__(self, path: str, expected: str, got: str) -> None:
        super().__init__(f'{path}: expected {expected}, got {got}')
        self.path, self.expected, self.got = path, expected, got

    def under(self, old_head: str, new_head: str) -> IRValidationError:
        """The same error with its path re-rooted from *old_head* to *new_head*."""
        tail = self.path[len(old_head) :] if self.path.startswith(old_head) else '.' + self.path
        return IRValidationError(new_head + tail, self.expected, self.got)


class IRReadError(ValueError):
    """A stored record this reader refuses: the message names the cause and the door."""


class IRStaleError(ImportError):
    """IR-STALE-GENERATED: a generated module whose sources moved since it was written."""


def fail(path: str, expected: str, got: str) -> NoReturn:
    """Raise the :class:`IRValidationError` at *path*."""
    raise IRValidationError(path, expected, got)


def refuse_read(message: str) -> NoReturn:
    """Raise :class:`IRReadError`; *message* names the cause and the door."""
    raise IRReadError(message)


class F(NamedTuple):
    """One field of a record: everything validation, serialization and the codec need."""

    name: str
    kind: str  # bool int float complex str enum id record list array
    optional: bool = False
    target: object = None  # the Enum or record class
    item: F | None = None  # a list's element
    dtype: str = ''
    shape: tuple[int | str, ...] = ()
    unit: str = ''
    unique_by: str = ''
    csr_values: str = ''
    gauge: str = ''
    db: tuple[float, int] | None = None


# -- scalars ------------------------------------------------------------------------------------------------


def _type_name(value: object) -> str:
    return type(value).__name__


def _boolean(_spec: F, value: object, path: str) -> bool:
    if not isinstance(value, bool):
        fail(path, 'bool', _type_name(value))
    return value


def _integer(_spec: F, value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        fail(path, 'int', _type_name(value))
    if not _I64[0] <= int(value) <= _I64[1]:
        fail(path, 'a signed 64-bit int', str(value))
    return int(value)


def _real(_spec: F, value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        fail(path, 'float', _type_name(value))
    if not math.isfinite(value):
        fail(path, 'a finite float (IR-NON-FINITE)', repr(float(value)))
    return float(value)


def _complex(_spec: F, value: object, path: str) -> complex:
    if isinstance(value, bool) or not isinstance(value, (int, float, complex, np.number)):
        fail(path, 'complex', _type_name(value))
    value = complex(value)
    if not (math.isfinite(value.real) and math.isfinite(value.imag)):
        fail(path, 'a finite complex (IR-NON-FINITE)', repr(value))
    return value


def _text(spec: F, value: object, path: str) -> str:
    if not isinstance(value, str):
        fail(path, spec.kind, _type_name(value))
    if spec.kind == 'id' and not value:
        fail(path, 'a non-empty id', "''")
    return value


def _instance(spec: F, value: object, path: str) -> object:
    if not isinstance(value, spec.target):
        fail(path, spec.target.__name__, _type_name(value))
    return value


_SCALARS = {
    'bool': _boolean,
    'int': _integer,
    'float': _real,
    'complex': _complex,
    'str': _text,
    'id': _text,
    'enum': _instance,
    'record': _instance,
}


def _scalar(spec: F, value: object, path: str) -> object:
    return _SCALARS[spec.kind](spec, value, path)


# -- arrays and dims ----------------------------------------------------------------------------------------


def _bind(dims: dict[str, tuple[int, str]], name: str, extent: int, path: str, bounds: dict) -> None:
    low, high = bounds.get(name, (None, None))
    if low is not None and extent < low:
        fail(path, f'{name} >= {low}', str(extent))
    if high is not None and extent > high:
        fail(path, f'{name} <= {high}', str(extent))
    if name in dims and dims[name][0] != extent:
        fail(path, f'{name} = {dims[name][0]} (bound at {dims[name][1]})', str(extent))
    dims.setdefault(name, (extent, path))


def _array(spec: F, value: object, path: str, dims: dict, bounds: dict) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        fail(path, 'ndarray', _type_name(value))
    if value.dtype != np.dtype(spec.dtype):
        fail(f'{path}.dtype', spec.dtype, str(value.dtype))
    if value.ndim != len(spec.shape):
        fail(f'{path}.ndim', str(len(spec.shape)), str(value.ndim))
    for axis, (want, got) in enumerate(zip(spec.shape, value.shape, strict=True)):
        where = f'{path}.shape[{axis}]'
        if isinstance(want, str):
            _bind(dims, want, got, where, bounds)
        elif want != got:
            fail(where, str(want), str(got))
    if value.dtype.kind in 'fc' and not np.isfinite(value).all():
        fail(path, 'finite values (IR-NON-FINITE)', 'NaN or infinity')
    out = np.array(value, copy=True, order='C')
    out.flags.writeable = False
    return out


def _csr(offsets: np.ndarray, values: np.ndarray, path: str) -> None:
    if offsets.size == 0 or offsets[0] != 0:
        fail(f'{path}[0]', '0', 'nothing' if offsets.size == 0 else str(offsets[0]))
    if (np.diff(offsets) < 0).any():
        fail(path, 'non-decreasing offsets', 'a decrease')
    if offsets[-1] != values.shape[0]:
        fail(f'{path}[-1]', str(values.shape[0]), str(offsets[-1]))


# -- records ------------------------------------------------------------------------------------------------


def _merge(dims: dict, child: dict, head: str, child_head: str) -> None:
    for name, (extent, where) in child.items():
        rerooted = head + where[len(child_head) :]
        _bind(dims, name, extent, rerooted, {})


def _rerooted(error: IRValidationError, value: object, path: str) -> IRValidationError:
    return error.under(type(value).__name__, path)


def _item(spec: F, value: object, path: str, dims: dict, bounds: dict) -> object:
    if spec.kind == 'array':
        return _array(spec, value, path, dims, bounds)
    if spec.kind == 'list':
        if isinstance(value, (str, bytes)) or not hasattr(value, '__iter__'):
            fail(path, 'a sequence', _type_name(value))
        items = tuple(_item(spec.item, v, f'{path}[{i}]', dims, bounds) for i, v in enumerate(value))
        if spec.unique_by:
            keys = [getattr(v, spec.unique_by) for v in items]
            seen = {k for k in keys if keys.count(k) > 1}
            if seen:
                fail(path, f'unique {spec.unique_by}', f'duplicate {min(seen)!r}')
            items = tuple(sorted(items, key=lambda v: getattr(v, spec.unique_by)))
        return items
    value = _scalar(spec, value, path)
    if spec.kind == 'record':
        _merge(dims, value._ir_dims, path, type(value).__name__)  # noqa: SLF001 -- the runtime owns the slot
    return value


def post_init(record: object) -> None:
    """Validate and normalize *record* in place; bind its tree's symbolic dims."""
    cls = type(record)
    head = cls.__name__
    dims: dict[str, tuple[int, str]] = {}
    for spec in cls._ir_fields:
        value = getattr(record, spec.name)
        path = f'{head}.{spec.name}'
        if value is None:
            if not spec.optional:
                fail(path, 'a value', 'None')
            continue
        object.__setattr__(record, spec.name, _item(spec, value, path, dims, cls._ir_bounds))
    for spec in cls._ir_fields:
        offsets = getattr(record, spec.name)
        if spec.csr_values and offsets is not None:
            _csr(offsets, getattr(record, spec.csr_values), f'{head}.{spec.name}')
    object.__setattr__(record, '_ir_dims', dims)


def build(cls: type, kwargs: dict, path: str) -> object:
    """``cls(**kwargs)`` whose validation errors read from *path* rather than from ``cls``."""
    try:
        return cls(**kwargs)
    except IRValidationError as error:
        raise error.under(cls.__name__, path) from None


# -- canonical JSON -----------------------------------------------------------------------------------------


def _array_tree(value: np.ndarray) -> dict:
    data = value.astype(value.dtype.newbyteorder('<'), copy=False)
    if data.dtype.kind == 'b':
        data = data.view(np.uint8)
    raw = np.ascontiguousarray(data).tobytes(order='C')
    return {'data': base64.b64encode(raw).decode('ascii'), 'shape': list(value.shape)}


def _tree_of(spec: F, value: object) -> object:
    kind = spec.kind
    if kind == 'array':
        return _array_tree(value)
    if kind == 'list':
        return [_tree_of(spec.item, v) for v in value]
    if kind == 'record':
        return to_tree(value)
    if kind == 'enum':
        return value.value
    if kind == 'complex':
        return [value.real, value.imag]
    return value


def to_tree(record: object) -> dict:
    """The JSON tree of *record*; absent optionals are omitted."""
    return {
        spec.name: _tree_of(spec, getattr(record, spec.name))
        for spec in type(record)._ir_fields  # noqa: SLF001 -- the runtime owns the table it reads
        if getattr(record, spec.name) is not None
    }


def canonical(tree: object) -> bytes:
    """The canonical bytes of a JSON tree: sorted keys, no whitespace, ``repr`` floats, no NaN."""
    return json.dumps(tree, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _from_array(spec: F, tree: object, path: str) -> np.ndarray:
    if not isinstance(tree, dict) or set(tree) != {'data', 'shape'}:
        fail(path, '{"data", "shape"}', _type_name(tree))
    dtype = np.dtype(spec.dtype)
    raw = base64.b64decode(tree['data'], validate=True)
    wire = np.dtype(np.uint8) if dtype.kind == 'b' else dtype.newbyteorder('<')
    flat = np.frombuffer(raw, dtype=wire)
    if dtype.kind == 'b':
        flat = flat.astype(bool)
    shape = tuple(tree['shape'])
    if math.prod(shape) != flat.size:
        fail(f'{path}.shape', f'{flat.size} elements', str(list(shape)))
    return flat.astype(dtype).reshape(shape)


def _from_tree_item(spec: F, tree: object, path: str) -> object:
    kind = spec.kind
    if kind == 'array':
        return _from_array(spec, tree, path)
    if kind == 'list':
        if not isinstance(tree, list):
            fail(path, 'a list', _type_name(tree))
        return tuple(_from_tree_item(spec.item, v, f'{path}[{i}]') for i, v in enumerate(tree))
    if kind == 'record':
        return from_tree(spec.target, tree, path)
    if kind == 'enum':
        try:
            return spec.target(tree)
        except ValueError:
            fail(path, f'one of {[m.value for m in spec.target]}', repr(tree))
    if kind == 'complex':
        if not (isinstance(tree, list) and len(tree) == len('ri')):
            fail(path, '[re, im]', repr(tree))
        return complex(tree[0], tree[1])
    return tree


def from_tree(cls: type, tree: object, path: str | None = None) -> object:
    """Rebuild *cls* from its JSON tree; an unknown key is refused by name (IR-UNKNOWN-FIELD)."""
    path = path or cls.__name__
    if not isinstance(tree, dict):
        fail(path, 'an object', _type_name(tree))
    known = {spec.name: spec for spec in cls._ir_fields}
    unknown = sorted(set(tree) - set(known))
    if unknown:
        fail(f'{path}.{unknown[0]}', f'a field of {cls.__name__}', 'an unknown field (IR-UNKNOWN-FIELD)')
    kwargs = {name: _from_tree_item(known[name], value, f'{path}.{name}') for name, value in tree.items()}
    missing = [s.name for s in cls._ir_fields if not s.optional and s.name not in kwargs]
    if missing:
        fail(f'{path}.{missing[0]}', 'a value', 'nothing')
    return build(cls, kwargs, path)


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


def ir_dims() -> object:
    """The private per-instance slot holding the tree's bound dims."""
    return dataclasses.field(default=None, init=False, repr=False, compare=False)


# -- freshness ----------------------------------------------------------------------------------------------


def sources_hash(version: str, sources: list[bytes]) -> str:
    digest = hashlib.sha256(version.encode())
    for blob in sources:
        digest.update(b'\0' + blob.replace(b'\r\n', b'\n'))
    return digest.hexdigest()


def check_fresh(module_file: str, root_up: int, version_source: str, sources: tuple[str, ...], expected: str) -> None:
    """Raise IR-STALE-GENERATED when this module's sources are present and moved; silent without them."""
    root = Path(module_file).resolve().parents[root_up]
    files = [root / s for s in (version_source, *sources)]
    if not all(f.is_file() for f in files):
        return
    if sources_hash(_declared_version(files[0]), [f.read_bytes() for f in files[1:]]) != expected:
        message = f'IR-STALE-GENERATED: {module_file} predates its schema -- {_GENERATE}'
        raise IRStaleError(message)


def _declared_version(pyproject: Path) -> str:
    return tomllib.loads(pyproject.read_text(encoding='utf-8'))['tool']['dev_lab']['ir_schema']['version']
