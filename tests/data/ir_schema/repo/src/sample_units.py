"""The fixture consumer's ONE unit boundary: the generated codec delegates every unit conversion here.

A consumer declares it as ``boundary = "<module>"`` in ``[tool.dev_lab.ir_schema]``. This is the only module that
reads a unit -- affine (degC), gauge and logarithmic (dB) included -- so the generated code holds SI values and does
no unit arithmetic. *reference* is what the codec reads from the schema: for ``dB`` the catalogue's
``(db_reference, db_scale)``; for a gauge field the absolute SI value of its ``gauge_reference`` field.
"""

from __future__ import annotations

import numpy as np
import pint

UREG = pint.get_application_registry()
_LOGARITHMIC = 'dB'


def to_si(magnitude: object, unit: str, si_unit: str, reference: object = None) -> object:
    """*magnitude* in *unit* as an absolute *si_unit* magnitude; raises when *unit* does not convert."""
    if unit == _LOGARITHMIC:
        if not isinstance(reference, tuple):
            msg = f'{si_unit} declares no dB reference'
            raise ValueError(msg)
        level, scale = reference
        return level * np.power(10.0, np.asarray(magnitude) / scale)
    absolute = UREG.Quantity(magnitude, unit).to(si_unit).magnitude
    return absolute + reference if isinstance(reference, float) else absolute


def from_si(magnitude: object, si_unit: str, unit: str, reference: object = None) -> object:
    """An absolute *si_unit* *magnitude* in the display *unit* (gauge above *reference*, or dB against it)."""
    if unit == _LOGARITHMIC:
        level, scale = reference
        return scale * np.log10(np.asarray(magnitude) / level)
    gauge = magnitude - reference if isinstance(reference, float) else magnitude
    return UREG.Quantity(gauge, si_unit).to(unit).magnitude
