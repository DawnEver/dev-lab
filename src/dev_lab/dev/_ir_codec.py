"""THE IR CODEC TEMPLATE, copied into each consumer package as ``_ir_codec.py`` (git-ignored), boundary rendered.

:mod:`dev_lab.dev.irpython` writes the copy, so this file imports nothing from dev-lab.

The record walk of the boundary, and nothing else. A unit is read or written in ONE place, the consumer's declared
boundary module (``boundary`` in ``[tool.dev_lab.ir_schema]``): its ``to_si(magnitude, unit, si_unit, reference=)``
and ``from_si(magnitude, si_unit, unit, reference=)`` do every conversion -- affine, gauge and dB included. The codec
only passes the reference it reads from the schema (a gauge field's converted absolute reference field, or a dB
quantity's catalogue ``(db_reference, db_scale)``), so it imports no unit library and does no unit arithmetic
(IR-UNIT-LIBRARY). The generated types hold absolute SI only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import _ir_unit_boundary as _boundary  # replaced by the generator with the declared boundary module
import numpy as np

from ._ir_runtime import IRValidationError, build, fail, target

_NUMBER_UNIT = re.compile(r'^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*$')


def _refuse(path: str, expected: str, got: object) -> IRValidationError:
    return IRValidationError(path, f'{expected} (IR-BOUNDARY-UNIT)', repr(got))


def _reference(spec: object, values: Mapping[str, object]) -> object:
    """What the boundary converts against: a gauge field's absolute reference, else the catalogue dB pair."""
    return values.get(spec.gauge) if spec.gauge else spec.db


def _to_si(spec: object, magnitude: object, unit: str, path: str, reference: object) -> object:
    if not unit and not spec.gauge:
        return magnitude
    try:
        return _boundary.to_si(magnitude, unit or spec.unit, spec.unit, reference=reference)
    except Exception:  # noqa: BLE001 -- the boundary's refusals share no base; every one means "does not convert"
        raise _refuse(path, f'a unit convertible to {spec.unit}', unit) from None


def _float_in(spec: object, value: object, path: str, reference: object) -> object:
    if isinstance(value, str):
        match = _NUMBER_UNIT.match(value)
        if match is None:
            raise _refuse(path, f'"<number> <unit of {spec.unit}>"', value)
        return float(_to_si(spec, float(match.group(1)), match.group(2), path, reference))
    if isinstance(value, Mapping) and spec.kind == 'array':
        magnitudes = np.asarray(value['values'], dtype=spec.dtype)
        return np.asarray(_to_si(spec, magnitudes, value.get('unit', ''), path, reference))
    if spec.kind == 'array':
        return np.asarray(_to_si(spec, np.asarray(value, dtype=spec.dtype), '', path, reference))
    return _to_si(spec, value, '', path, reference)


def _value_in(spec: object, value: object, path: str, reference: object = None) -> object:
    kind = spec.kind
    if kind == 'record':
        return from_boundary(target(spec), value, path)
    if kind == 'list':
        return tuple(_value_in(spec.item, v, f'{path}[{i}]', reference) for i, v in enumerate(value))
    if kind == 'enum':
        return target(spec)(value)
    if kind == 'complex' and isinstance(value, Mapping):
        both = complex(value['re'], value['im'])
        return complex(_to_si(spec, both, value.get('unit', ''), path, reference))
    if kind in ('float', 'array'):
        return _float_in(spec, value, path, reference)
    return value


def from_boundary(cls: type, mapping: Mapping[str, Any], path: str | None = None) -> object:
    """Build *cls* from boundary values: numbers are SI, strings carry their unit."""
    path = path or cls.__name__
    known = {s.name: s for s in cls._ir_fields}
    unknown = sorted(set(mapping) - set(known))
    if unknown:
        fail(f'{path}.{unknown[0]}', f'a field of {cls.__name__}', 'an unknown field')
    values: dict[str, object] = {}
    for name in sorted(mapping, key=lambda n: bool(known[n].gauge)):  # a gauge field after its reference
        spec = known[name]
        values[name] = _value_in(spec, mapping[name], f'{path}.{name}', _reference(spec, values))
    return build(cls, values, path)


def _from_si(spec: object, magnitude: object, unit: str, reference: object) -> object:
    return _boundary.from_si(magnitude, spec.unit, unit or spec.unit, reference=reference)


def _value_out(spec: object, value: object, units: Mapping[str, str], prefix: str, reference: object) -> object:  # noqa: PLR0911 -- one return per kind
    kind = spec.kind
    if kind == 'record':
        return to_boundary(value, units, prefix)
    if kind == 'list':
        return [_value_out(spec.item, v, units, prefix, reference) for v in value]
    if kind == 'enum':
        return value.value
    unit = units.get(prefix.rstrip('.'), '')
    converts = bool(unit or spec.gauge)
    if kind == 'array':
        shown = _from_si(spec, value, unit, reference) if converts else value
        return {'values': np.asarray(shown).tolist(), 'unit': unit or spec.unit}
    if kind == 'float' and spec.unit:
        shown = _from_si(spec, value, unit, reference) if converts else value
        return f'{float(shown)!r} {unit or spec.unit}'
    if kind == 'complex':
        return {'re': value.real, 'im': value.imag, 'unit': spec.unit}
    return value


def to_boundary(record: object, units: Mapping[str, str] | None = None, prefix: str = '') -> dict[str, Any]:
    """Render *record* for a reader: *units* maps a dotted field path to its display unit (SI otherwise)."""
    units = units or {}
    out: dict[str, Any] = {}
    fields = type(record)._ir_fields  # noqa: SLF001 -- the generated table is the codec's input
    values = dict(zip((spec.name for spec in fields), record._ir_values(), strict=True))  # noqa: SLF001
    for spec in fields:
        value = values[spec.name]
        if value is None:
            continue
        out[spec.name] = _value_out(spec, value, units, f'{prefix}{spec.name}.', _reference(spec, values))
    return out


__all__ = ['from_boundary', 'to_boundary']
