"""THE RUST GENERATOR: one ``ir.rs`` holding the shared runtime and one ``mod ir_<module>`` per schema module.

A crate's ``build.rs`` runs ``python -m dev_lab.dev.irschema rust --out $OUT_DIR`` and ``include!``s the file; nothing
is committed (``docs-src/dev/ir-schema.md``, "Rust output"). Records derive serde with ``deny_unknown_fields``;
``validate()`` reports the same ``<path>: expected <x>, got <y>`` as the Python; ``to_json()`` writes the canonical
bytes the Python writes, so the two languages agree byte for byte on one value.
"""

from __future__ import annotations

import functools
import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev._irrust_runtime import RUNTIME_RS
from dev_lab.dev.irmodel import refuse
from dev_lab.dev.irpython import FINGERPRINT_PREFIX, fingerprint
from dev_lab.dev.irrustpy import PY_RUNTIME_RS, enum_py, id_py, record_py

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.irmodel import IR, Field, Module, Record, TypeRef

__all__ = ['UNIT_CRATES', 'render', 'write']

#: Unit crates generated Rust never names: it carries SI ``f64``s, and a unit is read only at the consumer's boundary.
UNIT_CRATES: Final = frozenset({'uom', 'dimensioned', 'measurements'})
_CRATE_PATH: Final = re.compile(r'\b([a-z_][a-z0-9_]*)::')

_SCALARS: Final = {'bool': 'bool', 'int': 'i64', 'float': 'f64', 'complex': 'ir_runtime::Complex', 'str': 'String'}
_DTYPES: Final = {
    'bool': 'bool',
    'int32': 'i32',
    'int64': 'i64',
    'float32': 'f32',
    'float64': 'f64',
    'complex128': 'ir_runtime::Complex',
}


def _camel(snake: str) -> str:
    return ''.join(part.capitalize() for part in snake.split('_'))


def _path(ir: IR, target: str, here: str = '', suffix: str = '') -> str:
    module, name = target.split('.')
    if module == here:
        return f'{name}{suffix}'
    if module in ir.declaration.external:
        return f'{ir.declaration.external_rust[module]}::{name}{suffix}'
    return f'super::ir_{module}::{name}{suffix}'


def _owned_type(ir: IR, f: Field, ref: TypeRef, *, here: str) -> str:
    return _rust_type(ir, f, ref, here)


def _rust_type(ir: IR, f: Field, ref: TypeRef, here: str) -> str:
    if ref.kind in _SCALARS:
        return _SCALARS[ref.kind]
    if ref.kind == 'array':
        return f'ndarray::ArrayD<{_DTYPES[f.dtype]}>'
    if ref.kind == 'list':
        return f'Vec<{_rust_type(ir, f, ref.item, here)}>'
    return _path(ir, ref.target, here, 'Id' if ref.kind == 'id' else '')


def _check(ir: IR, f: Field, ref: TypeRef, var: str, path: str) -> list[str]:  # noqa: PLR0911 -- one return per kind
    kind = ref.kind
    if kind == 'float':
        return [f'ir_runtime::finite(&{path}, *{var})?;']
    if kind == 'complex':
        return [f'ir_runtime::finite(&{path}, {var}.re)?;', f'ir_runtime::finite(&{path}, {var}.im)?;']
    if kind == 'id':
        return [f'if {var}.0.is_empty() {{ return ir_runtime::fail(&{path}, "a non-empty id", "\'\'"); }}']
    if kind == 'record':
        return [f'{var}.validate_into(&{path}, dims)?;']
    if kind == 'array':
        shape = ', '.join(
            f'(None, {d!r})'.replace("'", '"') if isinstance(d, str) else f'(Some({d}), "")' for d in f.shape
        )
        return [f'ir_runtime::check_array({var}, &{path}, &[{shape}], dims, BOUNDS)?;']
    if kind == 'list':
        body = _check(ir, f, ref.item, 'item', 'p')
        lines = []
        if f.unique_by:
            target = ir.record(ref.item.target)
            key = target.field(f.unique_by)
            access = {'id': '.0.clone()', 'str': '.clone()', 'int': ''}[key.type.kind]
            lines.append(
                f'ir_runtime::check_unique({var}.iter().map(|w| w.{f.unique_by}{access}).collect(), &{path}, '
                f'"{f.unique_by}")?;'
            )
        if body:
            lines += [f'for (i, item) in {var}.iter().enumerate() {{', f'    let p = format!("{{{path}}}[{{i}}]");']
            lines += [f'    {line}' for line in body] + ['}']
        return lines
    return []


def _validate(ir: IR, record: Record) -> list[str]:
    lines = []
    for f in record.fields:
        path = f'p_{f.name}'
        var = f'x_{f.name}'
        body = _check(ir, f, f.type, var, path)
        if not body:
            continue
        lines.append(f'let {path} = format!("{{path}}.{f.name}");')
        if f.optional:
            lines += [f'if let Some({var}) = &self.{f.name} {{', *(f'    {b}' for b in body), '}']
        else:
            lines += [f'let {var} = &self.{f.name};', *body]
    for f in record.fields:
        if f.csr_values:
            lines.append(
                f'ir_runtime::check_csr(&self.{f.name}, self.{f.csr_values}.shape()[0], '
                f'&format!("{{path}}.{f.name}"))?;'
            )
    return lines


def _canonicalize(ir: IR, record: Record, here: str) -> list[str]:
    lines = []
    for f in record.fields:
        ref = f.type.item if f.type.kind == 'list' else f.type
        if ref.kind != 'record':
            continue
        child = _path(ir, ref.target, here)
        if f.type.kind == 'list':
            lines.append(f'if let Some(serde_json::Value::Array(items)) = v.get_mut("{f.name}") {{')
            lines.append(f'    for item in items {{ {child}::canonicalize(item); }}')
            lines.append('}')
        else:
            lines.append(f'if let Some(x) = v.get_mut("{f.name}") {{ {child}::canonicalize(x); }}')
        if f.unique_by:
            lines.append(f'ir_runtime::sort_by_key(v, "{f.name}", "{f.unique_by}");')
    return lines


def _field_line(ir: IR, f: Field, here: str) -> list[str]:
    rust = _rust_type(ir, f, f.type, here)
    attributes = []
    if f.type.kind == 'array':
        module = 'opt_array' if f.optional else 'array'
        attributes.append(f'with = "ir_runtime::{module}"')
    if f.optional:
        attributes += ['default', 'skip_serializing_if = "Option::is_none"']
        rust = f'Option<{rust}>'
    lines = [f'    /// {f.doc}'] if f.doc else []
    if attributes:
        lines.append(f'    #[serde({", ".join(attributes)})]')
    return [*lines, f'    pub {f.name}: {rust},']


def _record(ir: IR, module: Module, record: Record) -> list[str]:
    name = record.name
    lines = ['', f'/// {record.doc or name}', '#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]']
    lines += ['#[serde(deny_unknown_fields)]', f'pub struct {name} {{']
    for f in record.fields:
        lines += _field_line(ir, f, module.name)
    lines += ['}', '', f'impl {name} {{', f'    pub const NAME: &\'static str = "{module.name}.{name}";']
    lines += [
        '    pub fn validate(&self) -> ir_runtime::Res {',
        '        let mut dims = ir_runtime::Dims::new();',
        f'        self.validate_into("{name}", &mut dims)',
        '    }',
        '',
        '    pub fn validate_into(&self, path: &str, dims: &mut ir_runtime::Dims) -> ir_runtime::Res {',
        '        let _ = (&path, &dims);',
        *(f'        {line}' for line in _validate(ir, record)),
        '        Ok(())',
        '    }',
        '',
        '    pub fn canonicalize(v: &mut serde_json::Value) {',
        '        let _ = &v;',
        *(f'        {line}' for line in _canonicalize(ir, record, module.name)),
        '    }',
        '',
        '    pub fn to_json(&self) -> String {',
        '        let mut v = serde_json::to_value(self).expect("an IR record serializes");',
        '        Self::canonicalize(&mut v);',
        '        let mut out = String::new();',
        '        ir_runtime::canonical(&v, &mut out);',
        '        out',
        '    }',
        '',
        '    pub fn from_json(text: &str) -> Result<Self, String> {',
        '        let record: Self = serde_json::from_str(text).map_err(|e| e.to_string())?;',
        '        record.validate().map_err(|e| e.to_string())?;',
        '        Ok(record)',
        '    }',
        '',
        '}',
    ]
    return lines


def _module(ir: IR, module: Module) -> list[str]:
    bounds = ', '.join(
        f'("{d}", {"None" if lo is None else f"Some({lo})"}, {"None" if hi is None else f"Some({hi})"})'
        for d, (lo, hi) in module.dims.items()
    )
    lines = [
        '',
        f'/// GENERATED from {ir.declaration.modules[module.name]}; version {ir.declaration.version_text}.',
        '#[allow(dead_code, unused_imports, clippy::all)]',
        f'pub mod ir_{module.name} {{',
        'use super::ir_runtime;',
        'use serde::{Deserialize, Serialize};',
        '',
        f'pub const VERSION: &str = "{ir.declaration.version_text}";',
        f'const BOUNDS: &ir_runtime::Bounds = &[{bounds}];',
    ]
    for record in module.records.values():
        if any(f.name == 'id' and f.type.kind == 'id' for f in record.fields):
            lines += [
                '',
                '#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]',
                '#[serde(transparent)]',
                f'pub struct {record.name}Id(pub String);',
                *id_py(f'{record.name}Id'),
            ]
    for enum in module.enums.values():
        lines += ['', '#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]']
        lines.append(f'pub enum {enum.name} {{')
        lines += [f'    #[serde(rename = "{v}")]\n    {_camel(v)},' for v in enum.values]
        lines.append('}')
        lines += enum_py(ir, module, enum, _camel)
    path = functools.partial(_path, ir, here=module.name)
    owned = functools.partial(_owned_type, ir, here=module.name)
    for record in module.records.values():
        lines += _record(ir, module, record)
        lines += record_py(ir, module, record, path, owned)
    return [*lines, '}']


def render(ir: IR) -> str:
    """The text of ``ir.rs``."""
    prints = ' '.join(f'{name}={fingerprint(ir, name)}' for name in ir.modules)
    runtime = RUNTIME_RS.rstrip().removesuffix('}') + PY_RUNTIME_RS + '}' + chr(10)
    lines = [f'// {FINGERPRINT_PREFIX[2:]}{prints}', '// GENERATED by dev_lab.dev.irschema; do not edit.', runtime]
    for module in ir.modules.values():
        lines += _module(ir, module)
    text = '\n'.join(lines) + '\n'
    if named := sorted(UNIT_CRATES.intersection(_CRATE_PATH.findall(text))):
        refuse('IR-UNIT-LIBRARY', 'ir.rs', f'names the unit crate(s) {", ".join(named)}')
    return text


def write(ir: IR, out: Path) -> Path:
    """Write ``ir.rs`` into *out* (a build's ``OUT_DIR``) when its content differs; its path."""
    target = out / 'ir.rs'
    text = render(ir)
    if not target.is_file() or target.read_text(encoding='utf-8') != text:
        out.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
    return target
