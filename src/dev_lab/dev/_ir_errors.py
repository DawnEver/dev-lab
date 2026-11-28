"""An IR declaration refused by its code, naming the door that fixes it (:class:`IRSchemaError`).

Every IR reader (:mod:`dev_lab.dev.irmodel`, :mod:`dev_lab.dev._ir_catalogue`, :mod:`dev_lab.dev.ircheck`) and
generator (:mod:`dev_lab.dev.irpython`, :mod:`dev_lab.dev.irrust`) refuses through :func:`refuse`; the codes and
their doors are one table here.
"""

from __future__ import annotations

from typing import Final, NoReturn

__all__ = ['IRSchemaError', 'refuse']

_DOORS: Final = {
    'IR-UNKNOWN-TYPE': 'fix the name or declare the target',
    'IR-RECORD-CYCLE': 'break the cycle with an id: reference',
    'IR-ID-WITHOUT-ID-FIELD': 'give the target record a field `id` of type id:<Record>',
    'IR-UNIT-IN-SCHEMA': 'name a catalogue quantity; units live only in the catalogue',
    'IR-UNKNOWN-QUANTITY': 'add the quantity to the catalogue',
    'IR-QUANTITY-ON-NON-FLOAT': 'remove the quantity; only float and complex values carry one',
    'IR-NON-SI-UNIT': 'use the coherent SI unit (no prefix, offset, gauge or dB)',
    'IR-DIMENSION-MISMATCH': 'correct the catalogue row',
    'IR-FIELD-SPEC': 'see docs-src/dev/ir-schema.md, "A schema file"',
    'IR-NO-BOUNDARY': (
        'declare `boundary = "<module>"` in [tool.dev_lab.ir_schema]: the consumer module whose to_si/from_si is its '
        'one unit boundary (docs-src/dev/ir-schema.md, "Units cross once, at the boundary")'
    ),
    'IR-CONSTANT-SPEC': (
        'a [constant.<lower_snake>] row holds exactly value (a finite number, or an expression over numbers, pi and '
        'e with + - * / **), unit (coherent SI, "1" when dimensionless), citation and reason, all non-empty; no '
        'schema module is named `constants` (docs-src/dev/ir-schema.md, "Constants")'
    ),
    'IR-UNIT-LIBRARY': (
        'generated code holds SI only and reads no unit; units cross at the declared `boundary` module, so fix the '
        'generator template that names it'
    ),
}


class IRSchemaError(ValueError):
    """A refused IR declaration: ``<code>: <where>: <what> -- <door>``."""

    def __init__(self, code: str, where: str, what: str) -> None:
        """Refuse *what* at *where* under *code*, naming the code's door."""
        super().__init__(f'{code}: {where}: {what} -- {_DOORS[code]}')
        self.code = code


def refuse(code: str, where: str, what: str) -> NoReturn:
    """Raise the :class:`IRSchemaError` *code* at *where*."""
    raise IRSchemaError(code, where, what)
