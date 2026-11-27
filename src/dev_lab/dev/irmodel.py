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
from typing import Any, Final, cast

from dev_lab.dev._ir_catalogue import LOWER, Constant, Quantity, catalogue
from dev_lab.dev._ir_errors import refuse

__all__ = [
    'CONSTANTS_MODULE',
    'DTYPES',
    'IR',
    'Declaration',
    'Enum',
    'Field',
    'Module',
    'Reader',
    'Record',
    'TypeRef',
    'load_module',
    'parse',
]

#: Reads one repo-relative path to its text.
type Reader = Callable[[str], str]

SCALARS: Final = frozenset({'bool', 'int', 'float', 'complex', 'str'})
DTYPES: Final = ('bool', 'int32', 'int64', 'float32', 'float64', 'complex128')
_FIELD_KEYS: Final = frozenset(
    {
        'type', 'optional', 'quantity', 'doc', 'dtype', 'shape', 'unique_by', 'csr_values', 'gauge_reference',
        'default', 'default_consumer',
    }
)  # fmt: skip
#: Rust's reserved words: a field so spelled is emitted as a raw identifier (``r#use``), its wire name unchanged.
RUST_KEYWORDS: Final = frozenset({
    'as', 'async', 'await', 'break', 'const', 'continue', 'dyn', 'else', 'enum', 'extern', 'false', 'fn', 'for',
    'if', 'impl', 'in', 'let', 'loop', 'match', 'mod', 'move', 'mut', 'pub', 'ref', 'return', 'static', 'struct',
    'trait', 'true', 'type', 'unsafe', 'use', 'where', 'while', 'abstract', 'become', 'box', 'do', 'final', 'gen',
    'macro', 'override', 'priv', 'try', 'typeof', 'unsized', 'virtual', 'yield', 'self', 'super', 'crate',
})  # fmt: skip
#: Keywords a raw identifier cannot spell: such a field becomes ``<name>_`` with a serde rename.
_RUST_UNRAW: Final = frozenset({'self', 'super', 'crate'})
#: A default's Python types per kind: an optional field's ``default`` is carried, never filled on read (D135).
_DEFAULT_TYPES: Final = {'bool': (bool,), 'int': (int,), 'float': (int, float), 'str': (str,), 'enum': (str,)}
#: The generated module holding the catalogue's constants (``_ir_constants.py``, Rust ``mod ir_constants``).
CONSTANTS_MODULE: Final = 'constants'
_UPPER: Final = re.compile(r'^[A-Z][A-Za-z0-9]*$')


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
    #: An optional field's declared default, CARRIED for its named consumer and never filled by the reader (D135).
    default: object = None
    default_consumer: str = ''

    @property
    def py_name(self) -> str:
        """The generated Python attribute: a Python keyword gets a trailing ``_``; the wire name stays :attr:`name`."""
        return f'{self.name}_' if keyword.iskeyword(self.name) else self.name

    @property
    def rust_name(self) -> str:
        """The generated Rust field: a Rust keyword is raw (``r#use``); the wire name stays :attr:`name`."""
        if self.name in _RUST_UNRAW:
            return f'{self.name}_'
        return f'r#{self.name}' if self.name in RUST_KEYWORDS else self.name


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
class Module:
    """One schema file: its records, enums and dim bounds."""

    name: str
    source: str  # the schema text, as read
    records: dict[str, Record]
    enums: dict[str, Enum]
    dims: dict[str, tuple[int | None, int | None]]
    python: str = ''  # the importable module holding its generated Python
    terms: tuple[str, ...] = ()  # the terms files its enums read, repo-relative (a freshness source)


@dataclass(frozen=True)
class Declaration:
    """The repo's ``[tool.dev_lab.ir_schema]`` table."""

    root: Path
    version: tuple[int, int, int]
    package: str
    package_dir: str
    quantities: str
    migrations: str
    boundary: str
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
    constants: dict[str, Constant]

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
    if CONSTANTS_MODULE in table['modules']:
        refuse(
            'IR-CONSTANT-SPEC', 'pyproject.toml [tool.dev_lab.ir_schema.modules]', f'{CONSTANTS_MODULE!r} is reserved'
        )
    if not table.get('boundary'):
        refuse('IR-NO-BOUNDARY', 'pyproject.toml [tool.dev_lab.ir_schema]', 'no `boundary` module is declared')
    return Declaration(
        root=root,
        version=(major, minor, patch),
        package=table['package'],
        package_dir=table['package_dir'],
        quantities=table['quantities'],
        migrations=table.get('migrations', ''),
        boundary=table['boundary'],
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
    if head not in ('enum', 'id', 'record') or not rest:
        refuse('IR-UNKNOWN-TYPE', where, f'type {text!r} is not one of the declared types')
    return TypeRef(head, rest if '.' in rest else f'{module}.{rest}')


def _field(module: str, record: str, name: str, row: dict[str, Any]) -> Field:
    where = f'{module}.{record}.{name}'
    if not LOWER.match(name):
        refuse('IR-FIELD-SPEC', where, 'a field name is lower_snake (a keyword is escaped in generated code)')
    extra = sorted(set(row) - _FIELD_KEYS)
    if extra:
        refuse('IR-FIELD-SPEC', where, f'unknown key {extra[0]!r} (a required field has no default)')
    kind = _type(row['type'], module, where)
    is_array = kind.kind == 'array'
    if is_array != ('dtype' in row) or is_array != ('shape' in row):
        refuse('IR-FIELD-SPEC', where, 'dtype and shape belong to, and complete, an array')
    shape = tuple(row.get('shape', ()))
    _check_default(row, kind, where)
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
        default=cast('object', row.get('default')),
        default_consumer=str(row.get('default_consumer', '')),
    )


def _check_default(row: dict[str, Any], kind: TypeRef, where: str) -> None:
    """A ``default`` belongs to an OPTIONAL scalar or enum field, is of its type, and names its consumer."""
    if 'default' not in row:
        if 'default_consumer' in row:
            refuse('IR-FIELD-SPEC', where, '`default_consumer` names who fills a `default`, and there is none')
        return
    value: object = row['default']
    if not row.get('optional', False):
        refuse('IR-FIELD-SPEC', where, 'a required field has no default; only an optional field carries one')
    if not row.get('default_consumer'):
        refuse('IR-FIELD-SPEC', where, 'a `default` names its consumer (`default_consumer`): the reader never fills it')
    types = _DEFAULT_TYPES.get(kind.kind)
    if types is None or isinstance(value, bool) is not (kind.kind == 'bool') or not isinstance(value, types):
        refuse('IR-FIELD-SPEC', where, f'default {value!r} is not a {kind.kind} (a default is a scalar or enum value)')


def _enum_values(where: str, row: dict[str, Any], read: Reader | None) -> tuple[str, ...]:
    """An enum's values: listed (``values``), or the keys of a terms table (``terms`` file + dotted ``table``)."""
    if ('values' in row) == ('terms' in row):
        refuse('IR-FIELD-SPEC', where, 'an enum declares exactly one of `values` or `terms` + `table`')
    if 'values' in row:
        return tuple(str(v) for v in row['values'])
    if not row.get('table') or read is None:
        refuse('IR-FIELD-SPEC', where, '`terms = "<repo-relative toml>"` names its `table = "<dotted key>"`')
    terms, table = str(row['terms']), str(row['table'])
    node: Any = tomllib.loads(read(terms))
    for key in table.split('.'):
        node = cast('dict[str, Any]', node).get(key) if isinstance(node, dict) else None
    if not isinstance(node, dict):
        refuse('IR-FIELD-SPEC', where, f'{terms} has no table [{table}] to read the values from')
    return tuple(str(key) for key in cast('dict[str, Any]', node))


def load_module(
    name: str, source: str, python: str = '', read: Reader | None = None, resolved: dict[str, list[str]] | None = None
) -> Module:
    """One schema file, parsed but not yet resolved against its neighbors.

    *read* resolves a terms-table enum (``terms``); *resolved* gives an EXTERNAL module's enums as its generated
    ``ENUM_VALUES`` holds them, since the owner's terms file is not in this tree.
    """
    data = tomllib.loads(source)
    enums: dict[str, Enum] = {}
    for enum_name, row in data.get('enum', {}).items():
        if resolved is not None and enum_name in resolved:
            values = tuple(resolved[enum_name])
        else:
            values = _enum_values(f'{name}.{enum_name}', row, read)
        bad = [v for v in values if not LOWER.match(v) or keyword.iskeyword(v)]
        if not values or bad or len(set(values)) != len(values) or not _UPPER.match(enum_name):
            refuse('IR-FIELD-SPEC', f'{name}.{enum_name}', 'values: non-empty, unique, lower_snake')
        enums[enum_name] = Enum(name, enum_name, values)
    records: dict[str, Record] = {}
    for record_name, row in data.get('record', {}).items():
        if not _UPPER.match(record_name):
            refuse('IR-FIELD-SPEC', f'{name}.{record_name}', 'a record name is UpperCamel')
        fields = tuple(_field(name, record_name, f, r) for f, r in row.get('field', {}).items())
        records[record_name] = Record(name, record_name, fields, row.get('doc', ''))
        for f in fields:
            owner, _, enum = f.type.target.partition('.')
            local = f.type.kind == 'enum' and owner == name and enum in enums
            if local and f.default is not None and f.default not in enums[enum].values:
                where = f'{name}.{record_name}.{f.name}'
                refuse('IR-FIELD-SPEC', where, f'default {f.default!r} is not a value of {enum}')
    dims = {d: (row.get('min'), row.get('max')) for d, row in data.get('dim', {}).items()}
    terms = tuple(sorted({row['terms'] for row in data.get('enum', {}).values() if 'terms' in row}))
    return Module(name, source, records, enums, dims, python, terms)


def _external(alias: str, module_name: str) -> Module:
    generated = importlib.import_module(module_name)
    return load_module(alias, generated.SCHEMA_TOML, module_name, resolved=generated.ENUM_VALUES)


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
        name: load_module(name, read(path), f'{declaration.package}._ir_{name}', read)
        for name, path in declaration.modules.items()
    }
    external = {alias: _external(alias, target) for alias, target in declaration.external.items()}
    source = read(declaration.quantities)
    quantities, domains, constants = catalogue(source)
    return IR(declaration, modules, quantities, source, domains, external, constants)
