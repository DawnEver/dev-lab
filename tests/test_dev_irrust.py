"""The generated Rust (docs-src/dev/ir-schema.md, "Rust output"): its shape, and byte equality with the Python.

The equivalence test builds a throwaway crate around the generated ``ir.rs`` OFFLINE, from the local cargo registry.
A host whose registry lacks the crates cannot build it; that is named as an xfail with the reason, never skipped.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path

import lab_commons.launch as _door
import numpy as np
import pytest

from dev_lab.dev import irpython, irrust
from dev_lab.dev.ircheck import load

FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'
CARGO = shutil.which('cargo')
_OFFLINE_MARKERS = ('offline', 'no matching package', 'failed to select a version', 'failed to download')
_MANIFEST = """[package]
name = "ir_equivalence"
version = "0.0.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ndarray = "0.16"
"""
_MAIN = """include!(concat!(env!("CARGO_MANIFEST_DIR"), "/ir.rs"));

fn main() {
    let args: Vec<String> = std::env::args().collect();
    for pair in args[1..].chunks(2) {
        let text = std::fs::read_to_string(&pair[1]).unwrap();
        let out = match pair[0].as_str() {
            "widgets.Widget" => ir_widgets::Widget::from_json(&text).map(|r| r.to_json()),
            "samples.Sample" => ir_samples::Sample::from_json(&text).map(|r| r.to_json()),
            "samples.Batch" => ir_samples::Batch::from_json(&text).map(|r| r.to_json()),
            other => panic!("unknown record {other}"),
        };
        match out {
            Ok(s) => println!("OK {s}"),
            Err(e) => println!("ERR {e}"),
        }
    }
}
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))
    (root / 'src' / 'sample_pkg').mkdir(parents=True)
    (root / 'src' / 'sample_pkg' / '__init__.py').write_text('', encoding='utf-8')
    return root


def test_the_rust_carries_every_record_enum_and_id(repo: Path) -> None:
    text = irrust.render(load(repo))
    assert 'pub mod ir_widgets {' in text
    assert 'pub struct WidgetId(pub String);' in text
    assert '#[serde(rename = "painted")]\n    Painted,' in text
    assert 'pub source: Option<super::ir_widgets::Widget>,' in text
    assert 'pub widgets: Vec<super::ir_widgets::Widget>,' in text
    assert '#[serde(with = "ir_runtime::array")]\n    pub time: ndarray::ArrayD<f64>,' in text
    assert 'pub gain: ir_runtime::Complex,' in text
    assert 'const BOUNDS: &ir_runtime::Bounds = &[("n", Some(1), None)];' in text


def test_write_lands_ir_rs_in_the_build_directory(repo: Path, tmp_path: Path) -> None:
    out = irrust.write(load(repo), tmp_path / 'out')
    assert out == tmp_path / 'out' / 'ir.rs'
    assert out.read_text(encoding='utf-8').startswith('// ir-schema-fingerprint: widgets=')


def _python_cases(repo: Path, work: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path, str]]:
    irpython.write(load(repo))
    monkeypatch.syspath_prepend(str(repo / 'src'))
    for name in [n for n in sys.modules if n.startswith('sample_pkg')]:
        del sys.modules[name]
    w = importlib.import_module('sample_pkg._ir_widgets')
    s = importlib.import_module('sample_pkg._ir_samples')
    widget = w.Widget(
        id='w-2',
        finish=w.Finish.anodized,
        mass=1e-05,
        ambient_pressure=123456.789,
        seal_pressure=1e16,
        operating_temperature=-0.0,
    )
    other = w.Widget(id='w-1', finish=w.Finish.raw, mass=0.1, ambient_pressure=1.0, seal_pressure=2.5)

    def sample(n: int) -> object:
        return s.Sample(
            widget='w-1',
            label='quote " back \\ tab \t é',
            calibrated=True,
            count=-(2**62),
            gain=0.5 - 3j,
            time=np.linspace(0.0, 1.0, n),
            position=np.arange(3.0 * n).reshape(n, 3),
            tags=['b', 'a'],
            level=1e-07,
            source=widget,
        )

    batch = s.Batch(
        widgets=[widget, other],
        samples=[sample(2), sample(2)],
        hit_offsets=np.array([0, 1, 3], dtype=np.int64),
        hit_times=np.array([0.25, 0.5, 0.75]),
    )
    reversed_widgets = json.loads(batch.to_json())
    reversed_widgets['widgets'].reverse()
    bad = json.loads(batch.to_json())
    bad['samples'][1] = json.loads(sample(3).to_json())
    raws = {
        'widget': ('widgets.Widget', widget.to_json()),
        'sample': ('samples.Sample', sample(2).to_json()),
        'batch': ('samples.Batch', batch.to_json()),
        'reversed': ('samples.Batch', json.dumps(reversed_widgets).encode()),
        'bad': ('samples.Batch', json.dumps(bad).encode()),
    }
    cases = []
    for key, (record, raw) in raws.items():
        path = work / f'{key}.json'
        path.write_bytes(raw)
        cls = {'widgets.Widget': w.Widget, 'samples.Sample': s.Sample, 'samples.Batch': s.Batch}[record]
        try:
            expected = 'OK ' + cls.from_json(raw).to_json().decode()
        except ValueError as error:
            expected = f'ERR {error}'
        cases.append((record, path, expected))
    return cases


def test_rust_and_python_agree_byte_for_byte(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if CARGO is None:
        pytest.xfail('no cargo on this host: the Rust half of the equivalence cannot be built here')
    crate = tmp_path / 'crate'
    (crate / 'src').mkdir(parents=True)
    (crate / 'Cargo.toml').write_text(_MANIFEST, encoding='utf-8')
    (crate / 'src' / 'main.rs').write_text(_MAIN, encoding='utf-8')
    irrust.write(load(repo), crate)
    cases = _python_cases(repo, tmp_path, monkeypatch)
    assert any(expected.startswith('ERR Batch.samples[1].time.shape[0]') for *_, expected in cases)
    args = [a for record, path, _ in cases for a in (record, str(path))]
    done = _door.run(
        [CARGO, 'run', '--offline', '-q', '--manifest-path', str(crate / 'Cargo.toml'), '--', *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=900,
        # One rustc at a time: the box holds a test to its memory claim, and parallel rustc processes blew it.
        env={
            **os.environ,
            'CARGO_TARGET_DIR': str(tmp_path / 'target'),
            'CARGO_BUILD_JOBS': '1',
            'CARGO_INCREMENTAL': '0',
        },
    )
    if done.returncode != 0 and any(marker in done.stderr for marker in _OFFLINE_MARKERS):
        pytest.xfail(f'the local cargo registry lacks a crate the equivalence needs: {done.stderr.strip()[-300:]}')
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [expected for *_, expected in cases]
