"""THE IR CODEC TEMPLATE, copied verbatim into each consumer package as ``_ir_codec.py`` (git-ignored).

:mod:`dev_lab.dev.irpython` writes the copy, so this file imports nothing from dev-lab.

The boundary: the one place a unit is read or written. A value crosses ONCE, through Pint, into the
catalogue's coherent SI unit (affine temperatures as absolute, gauge pressure relative to its declared
reference field, dB through the quantity's catalogue reference); the generated types hold SI only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import numpy as np
import pint

from ._ir_runtime import IRValidationError, build, fail

UREG = pint.UnitRegistry()
_NUMBER_UNIT = re.compile(r'^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*$')


def _refuse(path: str, expected: str, got: object) -> IRValidationError:
    return IRValidationError(path, f'{expected} (IR-BOUNDARY-UNIT)', repr(got))


def _to_si(spec: object, magnitude: object, unit: str, path: str) -> object:
    if not unit:
        return magnitude
    if unit == 'dB':
        if spec.db is None:
            raise _refuse(path, f'a unit of {spec.unit}; this quantity declares no dB reference', unit)
        reference, scale = spec.db
        return reference * np.power(10.0, np.asarray(magnitude) / scale)
    try:
        quantity = UREG.Quantity(magnitude, unit)
        return quantity.to(spec.unit).magnitude
    except (pint.UndefinedUnitError, pint.DimensionalityError, AttributeError, ValueError):
        raise _refuse(path, f'a unit convertible to {spec.unit}', unit) from None


def _float_in(spec: object, value: object, path: str) -> object:
    if isinstance(value, str):
        match = _NUMBER_UNIT.match(value)
        if match is None:
            raise _refuse(path, f'"<number> <unit of {spec.unit}>"', value)
        return float(_to_si(spec, float(match.group(1)), match.group(2), path))
    if isinstance(value, Mapping) and spec.kind == 'array':
        return np.asarray(_to_si(spec, np.asarray(value['values'], dtype=spec.dtype), value.get('unit', ''), path))
    if spec.kind == 'array':
        return np.asarray(value, dtype=spec.dtype)
    return value


def _value_in(spec: object, value: object, path: str) -> object:
    kind = spec.kind
    if kind == 'record':
        return from_boundary(spec.target, value, path)
    if kind == 'list':
        return tuple(_value_in(spec.item, v, f'{path}[{i}]') for i, v in enumerate(value))
    if kind == 'enum':
        return spec.target(value)
    if kind == 'complex' and isinstance(value, Mapping):
        both = complex(value['re'], value['im'])
        return complex(_to_si(spec, both, value.get('unit', ''), path))
    if kind in ('float', 'array'):
        return _float_in(spec, value, path)
    return value


def from_boundary(cls: type, mapping: Mapping[str, Any], path: str | None = None) -> object:
    """Build *cls* from boundary values: numbers are SI, strings carry their unit."""
    path = path or cls.__name__
    known = {s.name: s for s in cls._ir_fields}
    unknown = sorted(set(mapping) - set(known))
    if unknown:
        fail(f'{path}.{unknown[0]}', f'a field of {cls.__name__}', 'an unknown field')
    values = {name: _value_in(known[name], v, f'{path}.{name}') for name, v in mapping.items()}
    for name, spec in known.items():
        if spec.gauge and values.get(name) is not None:
            values[name] = values[name] + values[spec.gauge]
    return build(cls, values, path)


def _from_si(spec: object, magnitude: object, unit: str) -> object:
    if unit == 'dB':
        reference, scale = spec.db
        return scale * np.log10(np.asarray(magnitude) / reference)
    return UREG.Quantity(magnitude, spec.unit).to(unit).magnitude


def _value_out(spec: object, value: object, units: Mapping[str, str], prefix: str) -> object:  # noqa: PLR0911 -- one return per kind
    kind = spec.kind
    if kind == 'record':
        return to_boundary(value, units, prefix)
    if kind == 'list':
        return [_value_out(spec.item, v, units, prefix) for v in value]
    if kind == 'enum':
        return value.value
    unit = units.get(prefix.rstrip('.'), '')
    if kind == 'array':
        return {'values': _from_si(spec, value, unit).tolist() if unit else value.tolist(), 'unit': unit or spec.unit}
    if kind == 'float' and spec.unit:
        shown = _from_si(spec, value, unit) if unit else value
        return f'{float(shown)!r} {unit or spec.unit}'
    if kind == 'complex':
        return {'re': value.real, 'im': value.imag, 'unit': spec.unit}
    return value


def to_boundary(record: object, units: Mapping[str, str] | None = None, prefix: str = '') -> dict[str, Any]:
    """Render *record* for a reader: *units* maps a dotted field path to its display unit (SI otherwise)."""
    units = units or {}
    out: dict[str, Any] = {}
    for spec in type(record)._ir_fields:  # noqa: SLF001 -- the generated table is the codec's input
        value = getattr(record, spec.name)
        if value is None:
            continue
        if spec.gauge:
            value = value - getattr(record, spec.gauge)
        out[spec.name] = _value_out(spec, value, units, f'{prefix}{spec.name}.')
    return out


__all__ = ['UREG', 'from_boundary', 'to_boundary']
