"""THE RUST <-> PYTHON CONVERSION of the generated IR, field by field, behind the crate feature ``pyo3``.

The FFI path never touches the canonical bytes (user ruling D49): those exist for content hashing, persistence and
the byte-equality test only. Each record gets a borrowed ``<Record>View<'py>`` whose arrays are
``numpy::PyReadonlyArrayDyn`` -- a ZERO-COPY read of the Python record's buffers -- and ``into_owned()`` makes the
owned record with at most one copy per array. ``FromPyObject`` for the owned record goes through its view;
``IntoPyObject`` builds the Python dataclass by keyword, moving each array into numpy without a copy
(``PyArrayDyn::from_owned_array``). Enums convert by value, ids as ``str``. Targets pyo3 0.29 / numpy 0.29.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from dev_lab.dev.irmodel import IR, Enum, Field, Module, Record, TypeRef

#: Maps a qualified target (``module.Name``) to its Rust path.
type Path = Callable[[str], str]
#: A field's owned Rust type.
type Owned = Callable[['Field', 'TypeRef'], str]

__all__ = ['PY_RUNTIME_RS', 'enum_py', 'id_py', 'record_py']

_CFG: Final = '#[cfg(feature = "pyo3")]'
_NUMPY: Final = {
    'bool': 'bool',
    'int32': 'i32',
    'int64': 'i64',
    'float32': 'f32',
    'float64': 'f64',
    'complex128': 'numpy::Complex64',
}
_ANY: Final = "pyo3::Bound<'py, pyo3::PyAny>"

#: Appended inside ``mod ir_runtime``.
PY_RUNTIME_RS: Final = r"""
    #[cfg(feature = "pyo3")]
    pub mod py {
        use pyo3::prelude::*;

        pub fn complex(ob: &Bound<'_, PyAny>) -> PyResult<super::Complex> {
            Ok(super::Complex { re: ob.getattr("real")?.extract()?, im: ob.getattr("imag")?.extract()? })
        }

        pub fn class<'py>(py: Python<'py>, module: &str, name: &str) -> PyResult<Bound<'py, PyAny>> {
            pyo3::types::PyModule::import(py, module)?.getattr(name)
        }
    }
"""


def _python_module(ir: IR, target: str) -> str:
    module = target.split('.', maxsplit=1)[0]
    if module in ir.declaration.external:
        return ir.declaration.external[module]
    return f'{ir.declaration.package}._ir_{module}'


def _view_type(f: Field, ref: TypeRef, path: Path, owned: Owned) -> str:
    if ref.kind == 'array':
        return f"numpy::PyReadonlyArrayDyn<'py, {_NUMPY[f.dtype]}>"
    if ref.kind == 'record':
        return f"{path(ref.target)}View<'py>"
    if ref.kind == 'list':
        return f'Vec<{_view_type(f, ref.item, path, owned)}>'
    return owned(f, ref)


def _read(f: Field, ref: TypeRef, var: str, path: Path) -> str:  # noqa: PLR0911 -- one return per kind
    kind = ref.kind
    if kind in ('bool', 'int', 'float', 'str'):
        return f'{var}.extract()?'
    if kind == 'complex':
        return f'ir_runtime::py::complex(&{var})?'
    if kind == 'id':
        return f'{path(ref.target)}Id({var}.extract()?)'
    if kind == 'enum':
        return f'<{path(ref.target)} as pyo3::FromPyObject>::extract({var}.as_borrowed())?'
    if kind == 'record':
        return f'<{path(ref.target)}View as pyo3::FromPyObject>::extract({var}.as_borrowed())?'
    if kind == 'array':
        return f"{var}.extract::<numpy::PyReadonlyArrayDyn<'py, {_NUMPY[f.dtype]}>>()?"
    inner = _read(f, ref.item, 'i', path)
    return (
        f'{var}.try_iter()?.map(|i| -> pyo3::PyResult<_> {{ let i = i?; Ok({inner}) }})'
        '.collect::<pyo3::PyResult<Vec<_>>>()?'
    )


def _owned(f: Field, ref: TypeRef, var: str) -> str:
    if ref.kind == 'array':
        if f.dtype == 'complex128':
            return f'{var}.as_array().mapv(|c| ir_runtime::Complex {{ re: c.re, im: c.im }})'
        return f'{var}.as_array().to_owned()'
    if ref.kind == 'record':
        return f'{var}.into_owned()'
    if ref.kind == 'list':
        return f'{var}.into_iter().map(|x| {_owned(f, ref.item, "x")}).collect()'
    return var


def _write(ir: IR, f: Field, ref: TypeRef, var: str) -> str:
    kind = ref.kind
    if kind in ('bool', 'int', 'float', 'str'):
        return f'pyo3::IntoPyObjectExt::into_bound_py_any({var}, py)?'
    if kind == 'id':
        return f'pyo3::IntoPyObjectExt::into_bound_py_any({var}.0, py)?'
    if kind == 'complex':
        return f'pyo3::types::PyComplex::from_doubles(py, {var}.re, {var}.im).into_any()'
    if kind in ('enum', 'record'):
        return f'pyo3::IntoPyObject::into_pyobject({var}, py)?'
    if kind == 'array':
        moved = f'{var}.mapv(|c| numpy::Complex64::new(c.re, c.im))' if f.dtype == 'complex128' else var
        return f'numpy::PyArrayDyn::from_owned_array(py, {moved}).into_any()'
    inner = _write(ir, f, ref.item, 'x')
    return (
        f'pyo3::types::PyList::new(py, {var}.into_iter().map(|x| -> pyo3::PyResult<_> {{ Ok({inner}) }})'
        '.collect::<pyo3::PyResult<Vec<_>>>()?)?.into_any()'
    )


def record_py(ir: IR, module: Module, record: Record, path: Path, owned: Owned) -> list[str]:
    """The view struct and both conversions of *record*.

    *path* maps a qualified target to its Rust path; *owned* is a field's owned Rust type.
    """
    name = record.name
    lines = ['', _CFG, f"pub struct {name}View<'py> {{"]
    for f in record.fields:
        view = _view_type(f, f.type, path, owned)
        lines.append(f'    pub {f.name}: {f"Option<{view}>" if f.optional else view},')
    lines += ["    _py: std::marker::PhantomData<&'py ()>,", '}', '', _CFG]
    lines += [f"impl<'a, 'py> pyo3::FromPyObject<'a, 'py> for {name}View<'py> {{", '    type Error = pyo3::PyErr;', '']
    lines.append("    fn extract(ob: pyo3::Borrowed<'a, 'py, pyo3::PyAny>) -> pyo3::PyResult<Self> {")
    lines.append('        use pyo3::types::PyAnyMethods;')
    lines.append(f'        Ok({name}View {{')
    for f in record.fields:
        read = _read(f, f.type, 'a', path)
        value = f'if a.is_none() {{ None }} else {{ Some({read}) }}' if f.optional else read
        lines.append(f'            {f.name}: {{ let a = ob.getattr("{f.name}")?; {value} }},')
    lines += ['            _py: std::marker::PhantomData,', '        })', '    }', '}', '', _CFG]
    lines += [f"impl<'py> {name}View<'py> {{", f'    pub fn into_owned(self) -> {name} {{', f'        {name} {{']
    for f in record.fields:
        owned = (
            f'self.{f.name}.map(|x| {_owned(f, f.type, "x")})' if f.optional else _owned(f, f.type, f'self.{f.name}')
        )
        lines.append(f'            {f.name}: {owned},')
    lines += ['        }', '    }', '}', '', _CFG]
    lines += [f"impl<'a, 'py> pyo3::FromPyObject<'a, 'py> for {name} {{", '    type Error = pyo3::PyErr;', '']
    lines.append("    fn extract(ob: pyo3::Borrowed<'a, 'py, pyo3::PyAny>) -> pyo3::PyResult<Self> {")
    lines += [f'        Ok(<{name}View as pyo3::FromPyObject>::extract(ob)?.into_owned())', '    }', '}', '', _CFG]
    lines += [f"impl<'py> pyo3::IntoPyObject<'py> for {name} {{"]
    lines += ['    type Target = pyo3::PyAny;', f'    type Output = {_ANY};', '    type Error = pyo3::PyErr;', '']
    lines.append(f"    fn into_pyobject(self, py: pyo3::Python<'py>) -> pyo3::PyResult<{_ANY}> {{")
    lines += [
        '        use pyo3::types::{PyAnyMethods, PyDictMethods};',
        '        let kwargs = pyo3::types::PyDict::new(py);',
    ]
    for f in record.fields:
        write = _write(ir, f, f.type, 'x')
        if f.optional:
            value = f'match self.{f.name} {{ Some(x) => {write}, None => py.None().into_bound(py) }}'
        else:
            value = _write(ir, f, f.type, f'self.{f.name}')
        lines.append(f'        kwargs.set_item("{f.name}", {value})?;')
    lines.append(f'        ir_runtime::py::class(py, "{_python_module(ir, f"{module.name}.{name}")}", "{name}")?')
    lines += ['            .call((), Some(&kwargs))', '    }', '}']
    return lines


def enum_py(ir: IR, module: Module, enum: Enum, camel: Callable[[str], str]) -> list[str]:
    """``FromPyObject``/``IntoPyObject`` of *enum*, by value."""
    name = enum.name
    arms = ''.join(f' "{v}" => Ok({name}::{camel(v)}),' for v in enum.values)
    back = ''.join(f' {name}::{camel(v)} => "{v}",' for v in enum.values)
    python = _python_module(ir, f'{module.name}.{name}')
    return [
        '',
        _CFG,
        f"impl<'a, 'py> pyo3::FromPyObject<'a, 'py> for {name} {{",
        '    type Error = pyo3::PyErr;',
        "    fn extract(ob: pyo3::Borrowed<'a, 'py, pyo3::PyAny>) -> pyo3::PyResult<Self> {",
        '        use pyo3::types::PyAnyMethods;',
        '        let value: String = ob.getattr("value")?.extract()?;',
        f'        match value.as_str() {{{arms} other => Err(pyo3::exceptions::PyValueError::new_err(',
        f'            format!("{name}: no value {{other}}"))) }}',
        '    }',
        '}',
        '',
        _CFG,
        f"impl<'py> pyo3::IntoPyObject<'py> for {name} {{",
        '    type Target = pyo3::PyAny;',
        f'    type Output = {_ANY};',
        '    type Error = pyo3::PyErr;',
        f"    fn into_pyobject(self, py: pyo3::Python<'py>) -> pyo3::PyResult<{_ANY}> {{",
        '        use pyo3::types::PyAnyMethods;',
        f'        let value = match self {{{back} }};',
        f'        ir_runtime::py::class(py, "{python}", "{name}")?.call1((value,))',
        '    }',
        '}',
    ]


def id_py(name: str) -> list[str]:
    """``FromPyObject``/``IntoPyObject`` of the id type *name* (``WidgetId``): a ``str`` on the Python side."""
    return [
        '',
        _CFG,
        f"impl<'a, 'py> pyo3::FromPyObject<'a, 'py> for {name} {{",
        '    type Error = pyo3::PyErr;',
        "    fn extract(ob: pyo3::Borrowed<'a, 'py, pyo3::PyAny>) -> pyo3::PyResult<Self> {",
        f'        Ok({name}(ob.extract()?))',
        '    }',
        '}',
    ]
