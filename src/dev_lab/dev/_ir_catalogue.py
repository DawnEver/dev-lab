"""THE IR QUANTITIES CATALOGUE, LOADED: its quantities, port domains and constants, each refused unless coherent SI.

The format is ``docs-src/dev/ir-schema.md`` ("The catalogue", "Constants"); :func:`dev_lab.dev.irmodel.parse`
reads the catalogue through :func:`catalogue`.
"""

from __future__ import annotations

import ast
import math
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from lab_commons.quantity import registry

from dev_lab.dev._ir_errors import refuse

__all__ = ['LOWER', 'Constant', 'Quantity', 'catalogue']

#: Pint's dimension names, in the catalogue's exponent order M L T I Theta N J.
_DIMENSIONS: Final = ('[mass]', '[length]', '[time]', '[current]', '[temperature]', '[substance]', '[luminosity]')
_UNIT_EPS: Final = 1e-12  # a coherent unit's base magnitude is exactly 1
_POWER: Final = (1, 2, -3, 0, 0, 0, 0)
_CONSTANT_KEYS: Final = frozenset({'value', 'unit', 'citation', 'reason'})
_CONSTANT_NAMES: Final = {'pi': math.pi, 'e': math.e}
_BINARY: Final[dict[type[ast.operator], Callable[[float, float], float]]] = {
    ast.Add: float.__add__,
    ast.Sub: float.__sub__,
    ast.Mult: float.__mul__,
    ast.Div: float.__truediv__,
    ast.Pow: float.__pow__,
}
#: A lower_snake name: a constant, a field, an enum value.
LOWER: Final = re.compile(r'^[a-z][a-z0-9_]*$')


@dataclass(frozen=True)
class Quantity:
    """One catalogue quantity: its coherent SI unit, dimension and optional dB reference."""

    name: str
    unit: str
    dimension: tuple[int, ...]
    db: tuple[float, int] | None = None


@dataclass(frozen=True)
class Constant:
    """One catalogue constant: its absolute SI value, its unit, and why it holds that value."""

    name: str
    value: float
    expression: str  # the declared value, as written
    unit: str
    citation: str
    reason: str


def catalogue(source: str) -> tuple[dict[str, Quantity], dict[str, tuple[str, str]], dict[str, Constant]]:
    """The catalogue *source*'s quantities, port domains (effort, flow) and constants, each one checked."""
    data = tomllib.loads(source)
    quantities = {}
    for name, row in data.get('quantity', {}).items():
        where = f'quantity.{name}'
        unit = _coherent_unit(row['unit'], where)
        dimension = tuple(int(x) for x in row['dimension'].split())
        measured = tuple(int(unit.dimensionality.get(d, 0)) for d in _DIMENSIONS)
        if dimension != measured:
            refuse('IR-DIMENSION-MISMATCH', where, f'unit {row["unit"]} has dimension {measured}')
        db = (float(row['db_reference']), int(row['db_scale'])) if 'db_reference' in row else None
        quantities[name] = Quantity(name, row['unit'], dimension, db)
    domains = {}
    for name, row in data.get('port_domain', {}).items():
        effort, flow = quantities[row['effort']], quantities[row['flow']]
        if tuple(a + b for a, b in zip(effort.dimension, flow.dimension, strict=True)) != _POWER:
            refuse('IR-DIMENSION-MISMATCH', f'port_domain.{name}', 'effort x flow is not a power')
        domains[name] = (row['effort'], row['flow'])
    constants = {name: _constant(name, row) for name, row in data.get('constant', {}).items()}
    return quantities, domains, constants


def _coherent_unit(text: str, where: str) -> Any:  # noqa: ANN401 -- a pint Unit
    """The pint unit of *text*, refused (IR-NON-SI-UNIT) unless it is coherent SI."""
    try:
        ureg = registry()
        unit = ureg.Unit(text)
        base = ureg.Quantity(1.0, unit).to_base_units()
    except Exception:  # noqa: BLE001 -- pint's refusals share no base; every one means "not coherent SI"
        refuse('IR-NON-SI-UNIT', where, f'unit {text!r}')
    if abs(base.magnitude - 1.0) > _UNIT_EPS:
        refuse('IR-NON-SI-UNIT', where, f'unit {text!r} is not coherent SI')
    return unit


def _evaluate(node: ast.expr, where: str) -> float:
    """A constant expression's value: numbers, ``pi``, ``e``, unary +/- and + - * / ** only; anything else refused."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in _CONSTANT_NAMES:
        return _CONSTANT_NAMES[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _evaluate(node.operand, where)
        return -operand if isinstance(node.op, ast.USub) else operand
    if not isinstance(node, ast.BinOp) or (operation := _BINARY.get(type(node.op))) is None:
        refuse('IR-CONSTANT-SPEC', where, f'value holds {ast.unparse(node)!r}, not a number, pi, e or + - * / **')
    try:
        value = operation(_evaluate(node.left, where), _evaluate(node.right, where))
    except (ArithmeticError, ValueError) as error:
        refuse('IR-CONSTANT-SPEC', where, f'value does not evaluate: {error}')
    return value


def _text(row: dict[str, object], key: str, where: str) -> str:
    value = row[key]
    if not isinstance(value, str) or not value.strip():
        refuse('IR-CONSTANT-SPEC', where, f'{key} is a non-empty string')
    return value


def _constant(name: str, row: dict[str, object]) -> Constant:
    where = f'constant.{name}'
    if not LOWER.match(name):
        refuse('IR-CONSTANT-SPEC', where, 'a constant name is lower_snake')
    keys = frozenset(row)
    if keys != _CONSTANT_KEYS:
        refuse(
            'IR-CONSTANT-SPEC',
            where,
            f'missing {sorted(_CONSTANT_KEYS - keys)}, unknown {sorted(keys - _CONSTANT_KEYS)}',
        )
    unit, citation, reason = (_text(row, key, where) for key in ('unit', 'citation', 'reason'))
    raw = row['value']
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        refuse('IR-CONSTANT-SPEC', where, f'value {raw!r} is neither a number nor an expression')
    expression = raw if isinstance(raw, str) else repr(raw)
    try:
        tree = ast.parse(expression, mode='eval').body
    except SyntaxError:
        refuse('IR-CONSTANT-SPEC', where, f'value {expression!r} does not parse')
    value = _evaluate(tree, where)
    if not math.isfinite(value):
        refuse('IR-CONSTANT-SPEC', where, f'value {expression!r} is not finite')
    if unit != '1':
        _coherent_unit(unit, where)
    return Constant(name, value, expression, unit, citation, reason)
