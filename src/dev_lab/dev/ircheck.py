"""THE IR SCHEMA, CHECKED ACROSS MODULES: references, quantities, field keys and record cycles.

:func:`load` is the one way a generator or a check obtains a repo's IR: :func:`dev_lab.dev.irmodel.parse` reads each
file; this module refuses what only the whole set can show (a dangling ``record:widgets.Widget``, a quantity the
catalogue lacks, a ``unique_by`` naming a float). Each refusal is an :class:`~dev_lab.dev.irmodel.IRSchemaError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from lab_commons.units import ureg

from dev_lab.dev.irmodel import IR, Field, Record, TypeRef, parse, refuse

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['check', 'load', 'records_reached']

_KEYED: Final = frozenset({'id', 'str', 'int'})


def _resolve(ir: IR, ref: TypeRef, where: str) -> None:
    if ref.kind == 'list':
        _resolve(ir, ref.item, where)
        return
    if not ref.target:
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
        ureg.Unit(f.quantity)
    except Exception:  # noqa: BLE001 -- any pint refusal means "not a unit", which is the answer wanted here
        refuse('IR-UNKNOWN-QUANTITY', where, f'quantity {f.quantity!r}')
    refuse('IR-UNIT-IN-SCHEMA', where, f'{f.quantity!r} is a unit, not a quantity name')


def _keys(ir: IR, record: Record, f: Field, where: str) -> None:
    fields = {g.name: g for g in record.fields}
    if f.unique_by:
        item = f.type.item
        target = ir.record(item.target) if f.type.kind == 'list' and item.kind == 'record' else None
        key = None if target is None else next((g for g in target.fields if g.name == f.unique_by), None)
        if key is None or key.type.kind not in _KEYED or key.optional:
            refuse('IR-FIELD-SPEC', where, 'unique_by names a required id/str/int field of the listed record')
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
    _cycles(ir)


def load(root: Path) -> IR | None:
    """The repo's IR, read and checked; ``None`` when it declares none."""
    ir = parse(root)
    if ir is not None:
        check(ir)
    return ir
