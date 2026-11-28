"""THE IR SCHEMA'S METADATA GRAMMAR: a field's defaults, bounds and requirements, and a record's ``rest``/``string``.

Split out of :mod:`dev_lab.dev.irmodel` (2026-11-28, MODULE-SIZE-ALARM): that module loads the schema's types,
records and enums; this one validates the draft-grammar metadata they carry (docs-src/dev/ir-schema.md) and refuses
every malformed key by its code. Enforcing or resolving it is the generators'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from dev_lab.dev._ir_catalogue import LOWER
from dev_lab.dev._ir_errors import refuse

if TYPE_CHECKING:
    from dev_lab.dev.irmodel import Field, TypeRef

__all__ = [
    'NUMERIC', 'DefaultFrom', 'check_default', 'check_metadata', 'default_from', 'foreign', 'number', 'rest', 'string',
]  # fmt: skip

_DEFAULT_FROM_KEYS: Final = frozenset({'facet', 'scale', 'offset'})
_FOREIGN: Final = re.compile(r'^[a-z_][a-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$')
_FACET: Final = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$')
#: The scalar kinds a bound (``minimum``/``maximum``), a ``fill`` or a ``default_from`` applies to.
NUMERIC: Final = frozenset({'int', 'float'})


@dataclass(frozen=True)
class DefaultFrom:
    """A derived default: ``scale * <facet> + offset``, the facet a dotted path in the same record tree (D213)."""

    facet: str
    scale: int | float = 1
    offset: int | float = 0


def foreign(text: str, where: str) -> str:
    """The ``<package>.<name>`` of ``foreign:<package>.<name>``: another package's type, validated by its owner."""
    target = text.removeprefix('foreign:')
    if not _FOREIGN.match(target):
        refuse('IR-UNKNOWN-TYPE', where, f'{text!r}: a foreign type is `foreign:<package>.<name>`')
    return target


def check_default(row: dict[str, Any], where: str) -> None:
    """A ``default`` (constant) or ``default_from`` (derived) belongs to an OPTIONAL field; never both.

    Whether a constant fits the field's type is :func:`dev_lab.dev.ircheck.check`'s: any type may carry one (D213).
    """
    if 'default' not in row and 'default_consumer' in row:
        refuse('IR-FIELD-SPEC', where, '`default_consumer` names who fills a `default`, and there is none')
    if 'default' in row and 'default_from' in row:
        refuse('IR-FIELD-SPEC', where, '`default` and `default_from` are exclusive: a default is constant or derived')
    if ('default' in row or 'default_from' in row) and not row.get('optional', False):
        refuse('IR-FIELD-SPEC', where, 'a required field has no default; only an optional field carries one')


def number(value: object) -> bool:
    """*value* is an int or float, never a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def default_from(row: dict[str, Any], kind: TypeRef, where: str) -> DefaultFrom | None:
    """``default_from = {facet, scale, offset}``: an affine function of one facet, on an int or float field."""
    if 'default_from' not in row:
        return None
    spec = row['default_from']
    if not isinstance(spec, dict):
        refuse('IR-FIELD-SPEC', where, '`default_from` is a table {facet, scale, offset}')
    spec = cast('dict[str, Any]', spec)
    if extra := sorted(set(spec) - _DEFAULT_FROM_KEYS):
        refuse('IR-FIELD-SPEC', where, f'`default_from` has unknown key {extra[0]!r} (facet, scale, offset)')
    facet = spec.get('facet')
    if not isinstance(facet, str) or not _FACET.match(facet):
        refuse('IR-FIELD-SPEC', where, f'`default_from.facet` is a dotted lower_snake path, got {facet!r}')
    if kind.kind not in NUMERIC:
        refuse('IR-FIELD-SPEC', where, f'`default_from` is affine: an int or float field, not a {kind.kind}')
    scale, offset = spec.get('scale', 1), spec.get('offset', 0)
    exact = int if kind.kind == 'int' else (int, float)
    for name, value in (('scale', scale), ('offset', offset)):
        if not number(value) or not isinstance(value, exact):
            refuse('IR-FIELD-SPEC', where, f'`default_from.{name}` {value!r} is not a number of the {kind.kind} field')
    return DefaultFrom(facet, scale, offset)


def check_metadata(row: dict[str, Any], kind: TypeRef, where: str) -> None:
    """``nonempty`` on a list; ``requires`` on an optional field; ``minimum``/``maximum`` on an int or float."""
    if 'nonempty' in row and (not isinstance(row['nonempty'], bool) or kind.kind != 'list'):
        refuse('IR-FIELD-SPEC', where, '`nonempty = true` belongs to a list field')
    if 'requires' in row:
        if not isinstance(row['requires'], str) or not LOWER.match(row['requires']):
            refuse('IR-FIELD-SPEC', where, '`requires` names one sibling field')
        if not row.get('optional', False):
            refuse('IR-FIELD-SPEC', where, '`requires`: only an optional field is written beside another')
    for bound in ('minimum', 'maximum'):
        if bound in row and kind.kind not in NUMERIC:
            refuse('IR-FIELD-SPEC', where, f'`{bound}` bounds an int or float field, not a {kind.kind}')


def rest(row: dict[str, Any], by_name: dict[str, Field], where: str) -> str:
    """``rest = "foreign:<package>.<name>"``: the foreign type of every undeclared key; ``''`` when closed."""
    if 'rest' not in row:
        return ''
    text = row['rest']
    if not isinstance(text, str) or not text.startswith('foreign:'):
        refuse('IR-FIELD-SPEC', where, '`rest = "foreign:<package>.<name>"` types the undeclared keys')
    if 'rest' in by_name:
        refuse('IR-FIELD-SPEC', where, 'a record with `rest` declares no field named rest (generated code uses it)')
    return foreign(text, where)


def string(row: dict[str, Any], by_name: dict[str, Field], where: str) -> str:
    """``string = "<field>"``: the str, enum or id field a bare string written for the record is."""
    string = row.get('string', '')
    if string and (not isinstance(string, str) or string not in by_name):
        refuse('IR-FIELD-SPEC', where, f'`string` names a field of the record, got {string!r}')
    if string and (kind := by_name[string].type.kind) not in ('str', 'enum', 'id'):
        refuse('IR-FIELD-SPEC', where, f'`string` names a str, enum or id field; {string} is a {kind}')
    return string
