"""A table's schema dataclass declares which of its fields are QUANTITIES, and one reader parses them.

User ruling 2026-11-25: a config value carries its unit (``lockout = "15 min"``), parsed once by
:func:`lab_commons.quantity.parse`. A dataclass that IS a table's schema (built ``Cls(**table)``) marks each such
field with :func:`quantity` -- its dimension, its default in the base unit (seconds, bytes), and the unit-suffixed key
it replaced -- and builds through :func:`values`, which refuses the retired key with its new line (FORMATS-MIGRATE-ONCE)
and turns each declared quantity into its base-unit number. The field holds that number; the code converts from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any, Final

from lab_commons.quantity import Renamed, parse, refuse_renamed

__all__ = ['QUANTITY', 'Spec', 'quantity', 'values']

#: The field-metadata key a quantity field carries its :class:`Spec` under.
QUANTITY: Final = 'quantity'


@dataclass(frozen=True)
class Spec:
    """A quantity field: its dimension (``duration``, ``size``), whether it must be positive, the key it replaced."""

    dimension: str
    positive: bool = True
    retired: tuple[str, str] | None = None  # (old unit-suffixed key, the unit its number was in)


def quantity(dimension: str, default: float, *, retired: tuple[str, str] | None = None, positive: bool = True) -> Any:  # noqa: ANN401 -- a dataclass field
    """A dataclass field holding a declared quantity in its base unit, *default* when undeclared."""
    return field(default=default, metadata={QUANTITY: Spec(dimension, positive, retired)})


def values(cls: type, table: Mapping[str, Any], where: str) -> dict[str, Any]:
    """*table* with each quantity field of *cls* parsed to its base unit; a retired unit key is refused first.

    Raises:
        lab_commons.quantity.QuantityRefused: a retired key (with its new line), or a value that is not its quantity.

    """
    specs = {f.name: f.metadata[QUANTITY] for f in fields(cls) if QUANTITY in f.metadata}
    renamed = {spec.retired[0]: Renamed(name, spec.retired[1]) for name, spec in specs.items() if spec.retired}
    refuse_renamed(where, table, renamed)
    return {
        key: parse(f'{where} {key}', value, specs[key].dimension, positive=specs[key].positive)
        if key in specs
        else value
        for key, value in table.items()
    }
