"""THE IR SCHEMA, LOADED: a repo's ``[tool.dev_lab.ir_schema]``, its schema files and its quantities catalogue.

The format is ``docs-src/dev/ir-schema.md``; this module reads it into frozen values and refuses every malformed
declaration by its code (``IR-UNKNOWN-TYPE`` ...) with the door that fixes it. Cross-module checks are
:mod:`dev_lab.dev.ircheck`; generation :mod:`dev_lab.dev.irpython` and :mod:`dev_lab.dev.irrust`; versioning
:mod:`dev_lab.dev.irversion`.
"""

from __future__ import annotations

import importlib
import keyword
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, NoReturn

from lab_commons.units import ureg

__all__ = [
    'DTYPES',
    'IR',
    'Declaration',
    'Enum',
    'Field',
    'IRSchemaError',
    'Module',
    'Quantity',
    'Reader',
    'Record',
    'TypeRef',
    'load_module',
    'parse',
    'refuse',
]

#: Reads one repo-relative path to its text.
type Reader = Callable[[str], str]

SCALARS: Final = frozenset({'bool', 'int', 'float', 'complex', 'str'})
DTYPES: Final = ('bool', 'int32', 'int64', 'float32', 'float64', 'complex128')
#: Pint's dimension names, in the catalogue's exponent order M L T I Theta N J.
_DIMENSIONS: Final = ('[mass]', '[length]', '[time]', '[current]', '[temperature]', '[substance]', '[luminosity]')
_UNIT_EPS: Final = 1e-12  # a coherent unit's base magnitude is exactly 1
_POWER: Final = (1, 2, -3, 0, 0, 0, 0)
_FIELD_KEYS: Final = frozenset(
    {'type', 'optional', 'quantity', 'doc', 'dtype', 'shape', 'unique_by', 'csr_values', 'gauge_reference'}
)
_UPPER: Final = re.compile(r'^[A-Z][A-Za-z0-9]*$')
_LOWER: Final = re.compile(r'^[a-z][a-z0-9_]*$')
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


@dataclass(frozen=True)
class TypeRef:
    """A field type: a kind, its qualified target, and a list's element type."""

    kind: str  # bool int float complex str enum id record list array
    target: str = ''  # 'module.Name' for enum/id/record
    item: TypeRef | None = None


@dataclass(frozen=True)
class Field:
    """One declared field of a record."""

    name: str
    type: TypeRef
    optional: bool = False
    quantity: str = ''
    doc: str = ''
    dtype: str = ''
    shape: tuple[int | str, ...] = ()
    unique_by: str = ''
    csr_values: str = ''
    gauge_reference: str = ''


@dataclass(frozen=True)
class Record:
    """One declared record: its module, name and fields in file order."""

    module: str
    name: str
    fields: tuple[Field, ...]
    doc: str = ''

    def field(self, name: str) -> Field:
        """The field called *name*."""
        return next(f for f in self.fields if f.name == name)


@dataclass(frozen=True)
class Enum:
    """One declared enum and its values."""

    module: str
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Quantity:
    """One catalogue quantity: its coherent SI unit, dimension and optional dB reference."""

    name: str
    unit: str
    dimension: tuple[int, ...]
    db: tuple[float, int] | None = None


@dataclass(frozen=True)
class Module:
    """One schema file: its records, enums and dim bounds."""

    name: str
    source: str  # the schema text, as read
    records: dict[str, Record]
    enums: dict[str, Enum]
    dims: dict[str, tuple[int | None, int | None]]
    python: str = ''  # the importable module holding its generated Python


@dataclass(frozen=True)
class Declaration:
    """The repo's ``[tool.dev_lab.ir_schema]`` table."""

    root: Path
    version: tuple[int, int, int]
    package: str
    package_dir: str
    quantities: str
    migrations: str
    modules: dict[str, str]
    external: dict[str, str] = field(default_factory=dict)
    external_rust: dict[str, str] = field(default_factory=dict)

    @property
    def version_text(self) -> str:
        """``MAJOR.MINOR.PATCH``."""
        return '.'.join(map(str, self.version))


@dataclass(frozen=True)
class IR:
    """A repo's whole IR: its modules, its catalogue and the external modules it references."""

    declaration: Declaration
    modules: dict[str, Module]
    quantities: dict[str, Quantity]
    catalogue_source: str
    port_domains: dict[str, tuple[str, str]]
    external: dict[str, Module]

    def record(self, qualified: str) -> Record:
        """The record named ``module.Name``."""
        module, name = qualified.split('.')
        return {**self.external, **self.modules}[module].records[name]


def _declaration(root: Path, read: Reader) -> Declaration | None:
    table = tomllib.loads(read('pyproject.toml')).get('tool', {})
    table = table.get('dev_lab', {}).get('ir_schema')
    if table is None:
        return None
    major, minor, patch = (int(part) for part in table['version'].split('.'))
    return Declaration(
        root=root,
        version=(major, minor, patch),
        package=table['package'],
        package_dir=table['package_dir'],
        quantities=table['quantities'],
        migrations=table.get('migrations', ''),
        modules=dict(table['modules']),
        external=dict(table.get('external', {})),
        external_rust=dict(table.get('external_rust', {})),
    )


def _type(text: str, module: str, where: str) -> TypeRef:
    if text in SCALARS or text == 'array':
        return TypeRef(text)
    head, _, rest = text.partition(':')
    if head == 'list' and rest:
        item = _type(rest, module, where)
        if item.kind in ('list', 'array'):
            refuse('IR-FIELD-SPEC', where, f'a list holds no {item.kind}; wrap it in a record')
        return TypeRef('list', item=item)
    if head in ('enum', 'id', 'record') and rest:
        return TypeRef(head, rest if '.' in rest else f'{module}.{rest}')
    refuse('IR-UNKNOWN-TYPE', where, f'type {text!r} is not one of the declared types')


def _field(module: str, record: str, name: str, row: dict) -> Field:
    where = f'{module}.{record}.{name}'
    if not _LOWER.match(name) or keyword.iskeyword(name):
        refuse('IR-FIELD-SPEC', where, 'a field name is lower_snake and not a Python keyword')
    extra = sorted(set(row) - _FIELD_KEYS)
    if extra:
        refuse('IR-FIELD-SPEC', where, f'unknown key {extra[0]!r} (a required field has no default)')
    kind = _type(row['type'], module, where)
    is_array = kind.kind == 'array'
    if is_array != ('dtype' in row) or is_array != ('shape' in row):
        refuse('IR-FIELD-SPEC', where, 'dtype and shape belong to, and complete, an array')
    shape = tuple(row.get('shape', ()))
    if is_array and (row['dtype'] not in DTYPES or not all(isinstance(d, (int, str)) for d in shape)):
        refuse('IR-FIELD-SPEC', where, f'dtype one of {DTYPES}, shape of ints and dim names')
    return Field(
        name=name,
        type=kind,
        optional=bool(row.get('optional', False)),
        quantity=row.get('quantity', ''),
        doc=row.get('doc', ''),
        dtype=row.get('dtype', ''),
        shape=shape,
        unique_by=row.get('unique_by', ''),
        csr_values=row.get('csr_values', ''),
        gauge_reference=row.get('gauge_reference', ''),
    )


def load_module(name: str, source: str, python: str = '') -> Module:
    """One schema file, parsed but not yet resolved against its neighbors."""
    data = tomllib.loads(source)
    enums = {}
    for enum_name, row in data.get('enum', {}).items():
        values = tuple(row['values'])
        bad = [v for v in values if not _LOWER.match(v) or keyword.iskeyword(v)]
        if not values or bad or len(set(values)) != len(values) or not _UPPER.match(enum_name):
            refuse('IR-FIELD-SPEC', f'{name}.{enum_name}', 'values: non-empty, unique, lower_snake')
        enums[enum_name] = Enum(name, enum_name, values)
    records = {}
    for record_name, row in data.get('record', {}).items():
        if not _UPPER.match(record_name):
            refuse('IR-FIELD-SPEC', f'{name}.{record_name}', 'a record name is UpperCamel')
        fields = tuple(_field(name, record_name, f, r) for f, r in row.get('field', {}).items())
        records[record_name] = Record(name, record_name, fields, row.get('doc', ''))
    dims = {d: (row.get('min'), row.get('max')) for d, row in data.get('dim', {}).items()}
    return Module(name, source, records, enums, dims, python)


def _catalogue(source: str) -> tuple[dict[str, Quantity], dict[str, tuple[str, str]]]:
    data = tomllib.loads(source)
    quantities = {}
    for name, row in data.get('quantity', {}).items():
        where = f'quantity.{name}'
        try:
            unit = ureg.Unit(row['unit'])
            base = ureg.Quantity(1.0, unit).to_base_units()
        except Exception:  # noqa: BLE001 -- pint's refusals share no base; every one means "not coherent SI"
            refuse('IR-NON-SI-UNIT', where, f'unit {row["unit"]!r}')
        if abs(base.magnitude - 1.0) > _UNIT_EPS:
            refuse('IR-NON-SI-UNIT', where, f'unit {row["unit"]!r} is not coherent SI')
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
    return quantities, domains


def _external(alias: str, module_name: str) -> Module:
    generated = importlib.import_module(module_name)
    return load_module(alias, generated.SCHEMA_TOML, module_name)


def parse(root: Path, read: Reader | None = None) -> IR | None:
    """The repo's IR as declared, NOT yet checked across modules; ``None`` when the repo declares none.

    :func:`dev_lab.dev.ircheck.load` is the checked read. *read* maps a repo-relative path to its text (default:
    the working tree), so :mod:`dev_lab.dev.irversion` can read the same IR at a git revision.
    """
    read = read or (lambda relative: (root / relative).read_text(encoding='utf-8'))
    declaration = _declaration(root, read)
    if declaration is None:
        return None
    modules = {
        name: load_module(name, read(path), f'{declaration.package}._ir_{name}')
        for name, path in declaration.modules.items()
    }
    external = {alias: _external(alias, target) for alias, target in declaration.external.items()}
    catalogue = read(declaration.quantities)
    quantities, domains = _catalogue(catalogue)
    return IR(declaration, modules, quantities, catalogue, domains, external)
