"""The fixture consumer's ONE unit boundary: the generated codec delegates every unit conversion here.

A consumer declares it as ``boundary = "<module>"`` in ``[tool.dev_lab.ir_schema]``; this is the only module that
reads a unit, so the generated code holds SI values and imports no unit library.
"""

from __future__ import annotations

import pint

UREG = pint.get_application_registry()


def to_si(magnitude: object, unit: str, si_unit: str) -> object:
    """*magnitude* in *unit* as the coherent SI *si_unit* magnitude; raises when *unit* does not convert."""
    return UREG.Quantity(magnitude, unit).to(si_unit).magnitude


def from_si(magnitude: object, si_unit: str, unit: str) -> object:
    """*magnitude* in *si_unit* as a *unit* magnitude, for display."""
    return UREG.Quantity(magnitude, si_unit).to(unit).magnitude
