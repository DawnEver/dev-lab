"""THE IR RUNTIME TEMPLATE, copied verbatim into each consumer package as ``_ir_runtime.py`` (git-ignored).

:mod:`dev_lab.dev.irpython` writes the copy, so this file imports nothing from dev-lab.

The one runtime every generated IR module of this package shares: validation driven by each record's
field table and the import-time freshness check; the canonical JSON tree is its sibling template
``_ir_tree.py``, the stored envelope and the record surface ``_ir_surface.py``. numpy only.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Callable, Iterable
from enum import Enum
from pathlib import Path
from typing import NamedTuple, NoReturn, Protocol, cast

import numpy as np

_I64 = (-(2**63), 2**63 - 1)
_GENERATE = 'python -m dev_lab.dev.irschema generate'


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


#: Every generated record and enum class by its qualified name. A field names its target as text and is resolved
#: here at use, so two modules may reference each other without an import cycle at definition time.
REGISTRY: dict[str, type] = {}


def target(spec: F) -> type:
    """The class *spec* names."""
    return REGISTRY[spec.target]


def register(name: str, cls: type) -> type:
    """Record *cls* in :data:`REGISTRY` under *name*."""
    REGISTRY[name] = cls
    return cls


class F(NamedTuple):
    """One field of a record: everything validation, serialization and the codec need."""

    name: str
    kind: str  # bool int float complex str enum id record list array foreign rest
    optional: bool = False
    target: str = ''  # 'module.Name' of the Enum or record class (REGISTRY); a foreign's '<package>.<name>'
    item: F | None = None  # a list's element
    dtype: str = ''
    shape: tuple[int | str, ...] = ()
    unit: str = ''
    unique_by: str = ''
    key: Callable[[object], object] | None = None  # reads unique_by off one listed record
    csr_values: str = ''
    gauge: str = ''
    db: tuple[float, int] | None = None
    attr: str = ''  # the Python attribute when the wire name is a keyword (``from`` -> ``from_``)


# -- scalars ------------------------------------------------------------------------------------------------


def type_name(value: object) -> str:
    return type(value).__name__


def _boolean(_spec: F, value: object, path: str) -> bool:
    if not isinstance(value, bool):
        fail(path, 'bool', type_name(value))
    return value


def _integer(_spec: F, value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        fail(path, 'int', type_name(value))
    if not _I64[0] <= int(value) <= _I64[1]:
        fail(path, 'a signed 64-bit int', str(value))
    return int(value)


def _real(_spec: F, value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        fail(path, 'float', type_name(value))
    if not math.isfinite(value):
        fail(path, 'a finite float (IR-NON-FINITE)', repr(float(value)))
    return float(value)


def _complex(_spec: F, value: object, path: str) -> complex:
    if isinstance(value, bool) or not isinstance(value, (int, float, complex, np.number)):
        fail(path, 'complex', type_name(value))
    value = complex(value)
    if not (math.isfinite(value.real) and math.isfinite(value.imag)):
        fail(path, 'a finite complex (IR-NON-FINITE)', repr(value))
    return value


def _text(spec: F, value: object, path: str) -> str:
    if not isinstance(value, str):
        fail(path, spec.kind, type_name(value))
    if spec.kind == 'id' and not value:
        fail(path, 'a non-empty id', "''")
    return value


def _instance(spec: F, value: object, path: str) -> object:
    cls = target(spec)
    if not isinstance(value, cls):
        fail(path, cls.__name__, type_name(value))
    return value


def _foreign(_spec: F, value: object, _path: str) -> object:
    return value  # another package's value, kept as written: its owner validates it


def _rest(spec: F, value: object, path: str) -> dict[str, object]:
    table = cast('dict[object, object]', value) if isinstance(value, dict) else None
    if table is None or not all(isinstance(k, str) for k in table):
        fail(path, f'a table of foreign:{spec.target}', type_name(value))
    return {str(k): v for k, v in table.items()}


_SCALARS = {
    'foreign': _foreign,
    'rest': _rest,
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


#: Each dim name's declared (low, high), either side open.
type _Bounds = dict[str, tuple[int | None, int | None]]


def _bind(dims: dict[str, tuple[int, str]], name: str, extent: int, path: str, bounds: _Bounds) -> None:
    low, high = bounds.get(name, (None, None))
    if low is not None and extent < low:
        fail(path, f'{name} >= {low}', str(extent))
    if high is not None and extent > high:
        fail(path, f'{name} <= {high}', str(extent))
    if name in dims and dims[name][0] != extent:
        fail(path, f'{name} = {dims[name][0]} (bound at {dims[name][1]})', str(extent))
    dims.setdefault(name, (extent, path))


def _array(spec: F, value: object, path: str, dims: dict[str, tuple[int, str]], bounds: _Bounds) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        fail(path, 'ndarray', type_name(value))
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
        if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
            fail(path, 'a sequence', type_name(value))
        items = tuple(_item(spec.item, v, f'{path}[{i}]', dims, bounds) for i, v in enumerate(value))
        if spec.unique_by:
            items = _unique(spec, items, path)
        return items
    value = _scalar(spec, value, path)
    if spec.kind == 'record':
        _merge(dims, value._ir_dims, path, type(value).__name__)  # noqa: SLF001 -- the runtime owns the slot
    return value


def _unique(spec: F, items: tuple[object, ...], path: str) -> tuple[object, ...]:
    """*items* in key order, refusing a duplicate key; a key is its canonical JSON, as the generated Rust's."""
    read = cast('Callable[[object], object]', spec.key)
    keys = [_plain(read(item)) for item in items]
    tokens = [json.dumps(k, separators=(',', ':'), ensure_ascii=False) for k in keys]
    if seen := {t for t in tokens if tokens.count(t) > 1}:
        fail(path, f'unique {spec.unique_by}', f'duplicate {min(seen)}')
    order = [_order(k) for k in keys]
    return tuple(items[i] for i in sorted(range(len(items)), key=order.__getitem__))


def _plain(key: object) -> object:
    """A ``unique_by`` key as its JSON tree: an enum its value, a tuple a list, an absent optional ``None``."""
    if isinstance(key, tuple):
        return [_plain(k) for k in cast('tuple[object, ...]', key)]
    return cast('Enum', key).value if isinstance(key, Enum) else key


def _order(key: object) -> tuple[object, ...]:
    """The sort order of a key tree, the generated Rust's ``cmp_key``: null < number < string < array."""
    if key is None:
        return (0,)
    if isinstance(key, list):
        return (3, tuple(_order(k) for k in cast('list[object]', key)))
    return (2, key) if isinstance(key, str) else (1, key)


def _shadowed(cls: type, rest: dict[str, object], path: str) -> None:
    """Refuse a foreign rest that holds a declared field's key: it is set as the field."""
    names = {spec.name for spec in cast('tuple[F, ...]', getattr(cls, '_ir_fields'))}  # noqa: B009 -- generated
    if declared := sorted(names & set(rest)):
        fail(f'{path}.{declared[0]}', 'an undeclared key', 'a declared field (set it as the field)')


def post_init(record: object) -> None:
    """Validate and normalize *record* through its generated ``_ir_values``/``_ir_set``; bind its tree's dims."""
    cls = type(record)
    head = cls.__name__
    dims: dict[str, tuple[int, str]] = {}
    values = {}
    for spec, value in zip(cls._ir_fields, record._ir_values(), strict=True):  # noqa: SLF001 -- generated
        path = f'{head}.{spec.name}'
        if value is None:
            if not spec.optional:
                fail(path, 'a value', 'None')
            values[spec.name] = None
            continue
        values[spec.name] = _item(spec, value, path, dims, cls._ir_bounds)
        if spec.kind == 'rest':
            _shadowed(cls, values[spec.name], path)
    for spec in cls._ir_fields:
        if spec.csr_values and values[spec.name] is not None:
            _csr(values[spec.name], values[spec.csr_values], f'{head}.{spec.name}')
    record._ir_set(tuple(values.values()), dims)  # noqa: SLF001 -- generated


class _Fielded(Protocol):
    """A generated record class, as :func:`build` reads it: its field table."""

    _ir_fields: tuple[F, ...]


def build(cls: type, kwargs: dict[str, object], path: str) -> object:
    """``cls(**kwargs)`` (keyed by WIRE name) whose validation errors read from *path* rather than from ``cls``."""
    specs = cast('type[_Fielded]', cls)._ir_fields  # noqa: SLF001 -- generated
    attrs: dict[str, str] = {spec.name: spec.attr for spec in specs if spec.attr}
    named: dict[str, object] = {attrs.get(str(name), str(name)): value for name, value in kwargs.items()}
    try:
        return cls(**named)
    except IRValidationError as error:
        raise error.under(cls.__name__, path) from None


def ir_dims() -> object:
    """The private per-instance slot holding the tree's bound dims."""
    return dataclasses.field(default=None, init=False, repr=False, compare=False)


# -- freshness ----------------------------------------------------------------------------------------------


def sources_hash(version: str, sources: list[bytes]) -> str:
    digest = hashlib.sha256(version.encode())
    for blob in sources:
        digest.update(b'\0' + blob.replace(b'\r\n', b'\n'))
    return digest.hexdigest()


def check_fresh(module_file: str, root_up: int, version: str, sources: tuple[str, ...], expected: str) -> None:
    """Raise IR-STALE-GENERATED when this module's sources are present and moved; silent without them.

    *version* is the declared IR version the module was generated under, EMBEDDED in it: the runtime reads no
    manifest. A version bump in ``pyproject.toml`` alone is refused by ``irschema check`` (and ``verify``), not here.
    """
    root = Path(module_file).resolve().parents[root_up]
    files = [root / s for s in sources]
    if not all(f.is_file() for f in files):
        return
    if sources_hash(version, [f.read_bytes() for f in files]) != expected:
        message = f'IR-STALE-GENERATED: {module_file} predates its schema -- {_GENERATE}'
        raise IRStaleError(message)
