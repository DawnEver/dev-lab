"""THE IR SCHEMA, CHECKED ACROSS MODULES: references, quantities, field keys and record cycles.

:func:`load` is the one way a generator or a check obtains a repo's IR: :func:`dev_lab.dev.irmodel.parse` reads each
file; this module refuses what only the whole set can show (a dangling ``record:widgets.Widget``, a quantity the
catalogue lacks, a ``unique_by`` naming a float, a ``default`` that does not fit its field, a bound in the wrong
dimension). Each refusal is an :class:`~dev_lab.dev._ir_errors.IRSchemaError`.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Final, cast

from lab_commons.quantity import registry

from dev_lab.dev._ir_errors import refuse
from dev_lab.dev._ir_metadata import number
from dev_lab.dev.irmodel import IR, Field, Record, TypeRef, parse

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['bounds', 'check', 'default_si', 'load', 'records_reached']

#: The kinds a ``unique_by`` key may be, alone or as a list's item; an optional key is absent as ``null``.
_KEYED: Final = frozenset({'id', 'str', 'int', 'enum'})


def _resolve(ir: IR, ref: TypeRef, where: str) -> None:
    if ref.kind == 'list':
        _resolve(ir, ref.item, where)
        return
    if not ref.target or ref.kind == 'foreign':  # a foreign type is its owner's to resolve
        return
    module_name, name = ref.target.split('.')
    module = {**ir.external, **ir.modules}.get(module_name)
    table = None if module is None else module.enums if ref.kind == 'enum' else module.records
    if table is None or name not in table:
        refuse('IR-UNKNOWN-TYPE', where, f'{ref.kind}:{ref.target} names nothing declared')
    if ref.kind == 'id':
        target = table[name]
        id_field = next((f for f in target.fields if f.name == 'id'), None)
        if id_field is None or id_field.type != TypeRef('id', ref.target):
            refuse('IR-ID-WITHOUT-ID-FIELD', where, f'{ref.target} has no field id of type id:{name}')


def _floating(f: Field) -> bool:
    kind = f.type.kind
    return kind in ('float', 'complex') or (kind == 'array' and f.dtype in ('float32', 'float64', 'complex128'))


def _quantity(ir: IR, f: Field, where: str) -> None:
    if not f.quantity:
        return
    if not _floating(f):
        refuse('IR-QUANTITY-ON-NON-FLOAT', where, f'quantity {f.quantity!r} on a {f.type.kind}')
    if f.quantity in ir.quantities:
        return
    try:
        registry().Unit(f.quantity)
    except Exception:  # noqa: BLE001 -- any pint refusal means "not a unit", which is the answer wanted here
        refuse('IR-UNKNOWN-QUANTITY', where, f'quantity {f.quantity!r}')
    refuse('IR-UNIT-IN-SCHEMA', where, f'{f.quantity!r} is a unit, not a quantity name')


def _keys(ir: IR, record: Record, f: Field, where: str) -> None:
    fields = {g.name: g for g in record.fields}
    if f.unique_by:
        item = f.type.item
        target = ir.record(item.target) if f.type.kind == 'list' and item.kind == 'record' else None
        for name in f.unique_by:
            key = None if target is None else next((g for g in target.fields if g.name == name), None)
            kind = None if key is None else key.type.item if key.type.kind == 'list' else key.type
            if kind is None or kind.kind not in _KEYED:
                refuse('IR-FIELD-SPEC', where, f'unique_by {name!r}: an id/str/int/enum field (or list of) of the item')
    if f.csr_values:
        values = fields.get(f.csr_values)
        if f.dtype != 'int64' or len(f.shape) != 1 or values is None or values.type.kind != 'array':
            refuse('IR-FIELD-SPEC', where, 'csr_values: a 1-d int64 array naming an array field')
    if f.gauge_reference:
        ref = fields.get(f.gauge_reference)
        if f.type.kind != 'float' or ref is None or ref.type.kind != 'float' or ref.quantity != f.quantity:
            refuse('IR-FIELD-SPEC', where, 'gauge_reference names a float field of the same quantity')
        if ref.gauge_reference or ref.optional:
            refuse('IR-FIELD-SPEC', where, 'a gauge reference is itself required and absolute')


def _fits(ir: IR, ref: TypeRef, value: object) -> bool:  # noqa: PLR0911 -- one return per kind
    """*value* (as TOML wrote it) is a value of *ref*: the type a ``default`` of any type is checked against."""
    kind = ref.kind
    if kind == 'bool':
        return isinstance(value, bool)
    if kind == 'int':
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == 'float':
        return number(value)
    if kind == 'complex':
        parts = cast('list[object]', value) if isinstance(value, list) else []
        return len(parts) == len('ri') and all(number(v) for v in parts)
    if kind in ('str', 'id'):
        return isinstance(value, str) and (kind == 'str' or bool(value))
    if kind == 'enum':
        module, name = ref.target.split('.')
        return value in {**ir.external, **ir.modules}[module].enums[name].values
    if kind == 'list':
        item = ref.item
        items = cast('list[object]', value) if isinstance(value, list) else None
        return items is not None and item is not None and all(_fits(ir, item, v) for v in items)
    if kind == 'record':
        record = ir.record(ref.target)
        fields = {f.name: f for f in record.fields}
        table = cast('dict[str, object]', value) if isinstance(value, dict) else None
        if table is None or not (record.rest or set(table) <= set(fields)):
            return False  # an undeclared key fits only a record with a foreign rest
        return _fits_declared(ir, fields, table)
    return kind == 'foreign'  # a foreign value is its owner's to check; an array has no TOML spelling


def _fits_declared(ir: IR, fields: dict[str, Field], value: dict[str, object]) -> bool:
    """Every declared key of a record value fits its field, and every required field is present."""
    present = all(_fits(ir, fields[k].type, v) for k, v in value.items() if k in fields)
    return present and all(name in value for name, f in fields.items() if not f.optional)


def _default(ir: IR, f: Field, where: str) -> None:
    if f.default is not None and f.type.kind == 'float' and f.quantity:
        _si(ir, f, f.default, 'default', where)
    elif f.default is not None and not _fits(ir, f.type, f.default):
        target = f.type.target or (f.type.item.target if f.type.item else '')
        refuse('IR-FIELD-SPEC', where, f'default {f.default!r} is not a {f.type.kind}{f":{target}" if target else ""}')


def _si(ir: IR, f: Field, written: object, which: str, where: str) -> float | None:
    """A bound or default in absolute SI: a bare number without a quantity, ``"<number> <unit>"`` with one."""
    if written is None:
        return None
    if not f.quantity:
        exact = isinstance(written, int) if f.type.kind == 'int' else True
        if not number(written) or not exact:
            refuse('IR-FIELD-SPEC', where, f'`{which}` {written!r}: a bare {f.type.kind} on a field without a quantity')
        return float(cast('float', written))
    unit = ir.quantities[f.quantity].unit
    if not isinstance(written, str):
        refuse('IR-FIELD-SPEC', where, f'`{which}` {written!r} carries its unit: "<number> <unit>" of {f.quantity}')
    try:
        units: Any = registry()
        value: object = units.Quantity(written).to(unit).magnitude
    except Exception:  # noqa: BLE001 -- any pint refusal (unparsable, wrong dimension) is the answer wanted here
        refuse('IR-FIELD-SPEC', where, f'`{which}` {written!r} is not a {f.quantity} (convertible to {unit})')
    if not number(value) or not math.isfinite(cast('float', value)):
        refuse('IR-FIELD-SPEC', where, f'`{which}` {written!r} is not a finite number of {unit}')
    return float(cast('float', value))


def bounds(ir: IR, f: Field) -> tuple[float | None, float | None]:
    """A field's ``(minimum, maximum)`` in absolute SI (its quantity's catalogue unit), either side open."""
    where = f'{f.name}'
    return _si(ir, f, f.minimum, 'minimum', where), _si(ir, f, f.maximum, 'maximum', where)


def default_si(ir: IR, f: Field) -> object:
    """A field's constant default as the numerics hold it: a float with a quantity in absolute SI, else as written."""
    return _si(ir, f, f.default, 'default', f.name) if f.type.kind == 'float' and f.quantity else f.default


def _bounds(ir: IR, f: Field, where: str) -> None:
    low = _si(ir, f, f.minimum, 'minimum', where)
    high = _si(ir, f, f.maximum, 'maximum', where)
    if low is not None and high is not None and low > high:
        refuse('IR-FIELD-SPEC', where, f'`minimum` {f.minimum!r} exceeds `maximum` {f.maximum!r}')


def _cycles(ir: IR) -> None:
    def walk(qualified: str, stack: tuple[str, ...]) -> None:
        if qualified in stack:
            refuse('IR-RECORD-CYCLE', ' -> '.join((*stack, qualified)), 'a record contains itself')
        for target in records_reached(ir.record(qualified)):
            walk(target, (*stack, qualified))

    for module in ir.modules.values():
        for name in module.records:
            walk(f'{module.name}.{name}', ())


def records_reached(record: Record) -> tuple[str, ...]:
    """The records *record* holds by value (``record:`` and ``list:record:``), qualified."""
    out = []
    for f in record.fields:
        ref = f.type.item if f.type.kind == 'list' else f.type
        if ref.kind == 'record':
            out.append(ref.target)
    return tuple(out)


def check(ir: IR) -> None:
    """Refuse what only the whole IR can show; silent when it holds."""
    for module in ir.modules.values():
        for record in module.records.values():
            for f in record.fields:
                where = f'{module.name}.{record.name}.{f.name}'
                _resolve(ir, f.type, where)
                _quantity(ir, f, where)
                _keys(ir, record, f, where)
                _default(ir, f, where)
                _bounds(ir, f, where)
    _cycles(ir)


def load(root: Path) -> IR | None:
    """The repo's IR, read and checked; ``None`` when it declares none."""
    ir = parse(root)
    if ir is not None:
        check(ir)
    return ir
