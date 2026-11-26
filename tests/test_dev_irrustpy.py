"""The generated pyo3 conversion (user ruling D49): field by field, never through the canonical bytes.

A throwaway extension module is built OFFLINE around the generated ``ir.rs`` with the ``pyo3`` feature on (one rustc
at a time). Three facts are measured:

* a record round-tripped Python -> Rust -> Python equals the original while ``to_json``/``from_json`` RAISE, so the
  path cannot be the canonical bytes;
* a ``<Record>View`` reads an array ZERO-COPY: its buffer pointer is the numpy array's own;
* PLANTED CONTROL: the owned record's array is a copy -- its pointer differs -- so the pointer check can say no.

A host without cargo or the cached crates cannot build it; that is an xfail naming the reason, never a skip.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import sysconfig
from pathlib import Path

import lab_commons.launch as _door
import numpy as np
import pytest

from dev_lab.dev import irpython, irrust, irrustpy
from dev_lab.dev.ircheck import load

FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'
CARGO = shutil.which('cargo')
_OFFLINE = ('offline', 'no matching package', 'failed to select a version', 'failed to download')
_MANIFEST = f"""[package]
name = "ir_ext"
version = "0.0.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[features]
default = ["pyo3"]
pyo3 = ["dep:pyo3", "dep:numpy"]

[dependencies]
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
ndarray = "0.17"
pyo3 = {{ version = "{irrustpy.PYO3_VERSION}", optional = true, features = ["extension-module"] }}
numpy = {{ version = "{irrustpy.NUMPY_VERSION}", optional = true }}
"""
_LIB = """include!(concat!(env!("CARGO_MANIFEST_DIR"), "/ir.rs"));

use pyo3::prelude::*;

fn invalid(e: ir_runtime::IrValidationError) -> PyErr {
    pyo3::exceptions::PyValueError::new_err(e.to_string())
}

#[pyfunction]
fn roundtrip<'py>(py: Python<'py>, name: &str, ob: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    match name {
        "Widget" => { let r: ir_widgets::Widget = ob.extract()?; r.validate().map_err(invalid)?; r.into_pyobject(py) }
        "Sample" => { let r: ir_samples::Sample = ob.extract()?; r.validate().map_err(invalid)?; r.into_pyobject(py) }
        "Batch" => { let r: ir_samples::Batch = ob.extract()?; r.validate().map_err(invalid)?; r.into_pyobject(py) }
        other => Err(pyo3::exceptions::PyKeyError::new_err(other.to_string())),
    }
}

#[pyfunction]
fn view_time_ptr(ob: Bound<'_, PyAny>) -> PyResult<usize> {
    let view: ir_samples::SampleView = ob.extract()?;
    Ok(view.time.as_array().as_ptr() as usize)
}

#[pyfunction]
fn owned_time_ptr(ob: Bound<'_, PyAny>) -> PyResult<usize> {
    let owned: ir_samples::Sample = ob.extract()?;
    Ok(owned.time.as_ptr() as usize)
}

#[pymodule]
fn ir_ext(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(view_time_ptr, m)?)?;
    m.add_function(wrap_pyfunction!(owned_time_ptr, m)?)?;
    Ok(())
}
"""


def _purge() -> None:
    for name in [n for n in sys.modules if n.startswith(('sample_pkg', 'ir_ext'))]:
        del sys.modules[name]


def _build(crate: Path, target: Path) -> Path:
    env = {
        **os.environ,
        'CARGO_TARGET_DIR': str(target),
        'CARGO_BUILD_JOBS': '1',  # one rustc at a time: the box holds a test to its memory claim
        'CARGO_INCREMENTAL': '0',
        'PYO3_PYTHON': sys.executable,
    }
    done = _door.run(
        [CARGO, 'build', '--offline', '-q', '--manifest-path', str(crate / 'Cargo.toml')],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=1500,
        env=env,
    )
    if done.returncode != 0 and any(marker in done.stderr for marker in _OFFLINE):
        pytest.xfail(f'the local cargo registry lacks a crate the pyo3 build needs: {done.stderr.strip()[-300:]}')
    assert done.returncode == 0, done.stderr
    built = next(
        p
        for p in (target / 'debug').iterdir()
        if p.stem in ('ir_ext', 'libir_ext') and p.suffix in ('.dll', '.so', '.dylib')
    )
    extension = crate / f'ir_ext{sysconfig.get_config_var("EXT_SUFFIX")}'
    shutil.copyfile(built, extension)
    return crate


def test_pyo3_converts_field_by_field_and_reads_arrays_zero_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if CARGO is None:
        pytest.xfail('no cargo on this host: the pyo3 half cannot be built here')
    repo = Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))
    (repo / 'src' / 'sample_pkg').mkdir(parents=True)
    (repo / 'src' / 'sample_pkg' / '__init__.py').write_text('', encoding='utf-8')
    ir = load(repo)
    irpython.write(ir)
    crate = tmp_path / 'crate'
    (crate / 'src').mkdir(parents=True)
    (crate / 'Cargo.toml').write_text(_MANIFEST, encoding='utf-8')
    (crate / 'src' / 'lib.rs').write_text(_LIB, encoding='utf-8')
    irrust.write(ir, crate)
    _build(crate, tmp_path / 'target')
    monkeypatch.syspath_prepend(str(repo / 'src'))
    monkeypatch.syspath_prepend(str(crate))
    _purge()
    try:
        w = importlib.import_module('sample_pkg._ir_widgets')
        s = importlib.import_module('sample_pkg._ir_samples')
        ext = importlib.import_module('ir_ext')
        widget = w.Widget(id='w-1', finish=w.Finish.raw, mass=0.5, ambient_pressure=1.0, seal_pressure=2.0)
        sample = s.Sample(
            widget='w-1',
            label='x',
            calibrated=True,
            count=7,
            gain=1 - 2j,
            time=np.linspace(0.0, 1.0, 4),
            position=np.ones((4, 3)),
            tags=['a'],
            source=widget,
        )
        batch = s.Batch(
            widgets=[widget],
            samples=[sample],
            hit_offsets=np.array([0, 2], dtype=np.int64),
            hit_times=np.array([0.1, 0.2]),
        )

        def refuse(*_args: object) -> bytes:
            message = 'the FFI path touched the canonical bytes'
            raise AssertionError(message)

        for cls in (w.Widget, s.Sample, s.Batch):
            monkeypatch.setattr(cls, 'to_json', refuse)
            monkeypatch.setattr(cls, 'from_json', classmethod(refuse))
        for name, record in (('Widget', widget), ('Sample', sample), ('Batch', batch)):
            back = ext.roundtrip(name, record)
            assert type(back) is type(record)
            assert back == record
        pointer = sample.time.ctypes.data
        assert ext.view_time_ptr(sample) == pointer, 'a view reads the numpy buffer itself'
        assert ext.owned_time_ptr(sample) != pointer, 'PLANTED CONTROL: the owned record holds a copy'
    finally:
        _purge()
