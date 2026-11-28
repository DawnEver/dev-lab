"""THE IR TREE TEMPLATE, copied verbatim beside ``_ir_runtime.py`` into each consumer package (git-ignored).

:mod:`dev_lab.dev.irpython` writes the copy, so this file imports nothing from dev-lab.

A record as its JSON tree and back, and the canonical bytes of a tree (sorted keys, no whitespace, ``repr`` floats):
split out of ``_ir_runtime.py`` (2026-11-28, MODULE-SIZE-ALARM), which validates; this converts. numpy only.
"""

from __future__ import annotations

import base64
import json
import math
from typing import cast

import numpy as np

from ._ir_runtime import F, build, fail, target, type_name

__all__ = ['canonical', 'from_tree', 'to_tree']


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


def to_tree(record: object) -> dict[str, object]:
    """The JSON tree of *record*; absent optionals are omitted; a foreign rest's keys sit beside the fields."""
    specs = cast('tuple[F, ...]', getattr(type(record), '_ir_fields'))  # noqa: B009 -- generated
    values = cast('tuple[object, ...]', getattr(record, '_ir_values')())  # noqa: B009 -- generated
    tree: dict[str, object] = {}
    for spec, value in zip(specs, values, strict=True):
        if value is None:
            continue
        if spec.kind == 'rest':
            tree.update(cast('dict[str, object]', value))
        else:
            tree[spec.name] = _tree_of(spec, value)
    return tree


def canonical(tree: object) -> bytes:
    """The canonical bytes of a JSON tree: sorted keys, no whitespace, ``repr`` floats, no NaN."""
    return json.dumps(tree, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _from_array(spec: F, tree: object, path: str) -> np.ndarray:
    if not isinstance(tree, dict) or set(tree) != {'data', 'shape'}:
        fail(path, '{"data", "shape"}', type_name(tree))
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
            fail(path, 'a list', type_name(tree))
        return tuple(_from_tree_item(spec.item, v, f'{path}[{i}]') for i, v in enumerate(tree))
    if kind == 'record':
        return from_tree(target(spec), tree, path)
    if kind == 'enum':
        try:
            return target(spec)(tree)
        except ValueError:
            fail(path, f'one of {[m.value for m in target(spec)]}', repr(tree))
    if kind == 'complex':
        if not (isinstance(tree, list) and len(tree) == len('ri')):
            fail(path, '[re, im]', repr(tree))
        return complex(tree[0], tree[1])
    return tree


def from_tree(cls: type, tree: object, path: str | None = None) -> object:
    """Rebuild *cls* from its JSON tree; an unknown key is refused by name (IR-UNKNOWN-FIELD)."""
    path = path or cls.__name__
    if not isinstance(tree, dict):
        fail(path, 'an object', type_name(tree))
    specs = cast('tuple[F, ...]', getattr(cls, '_ir_fields'))  # noqa: B009 -- generated
    known = {spec.name: spec for spec in specs if spec.kind != 'rest'}
    unknown = sorted(set(tree) - set(known))
    if unknown and not any(spec.kind == 'rest' for spec in specs):
        fail(f'{path}.{unknown[0]}', f'a field of {cls.__name__}', 'an unknown field (IR-UNKNOWN-FIELD)')
    kwargs = {
        name: _from_tree_item(known[name], value, f'{path}.{name}') for name, value in tree.items() if name in known
    }
    if unknown:
        kwargs['rest'] = {name: tree[name] for name in unknown}
    missing = [s.name for s in cls._ir_fields if not s.optional and s.name not in kwargs]
    if missing:
        fail(f'{path}.{missing[0]}', 'a value', 'nothing')
    return build(cls, kwargs, path)
