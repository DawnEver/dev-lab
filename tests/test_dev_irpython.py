"""The generated Python (docs-src/dev/ir-schema.md, "Python output"), exercised on the fixture repo."""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import json
import shutil
import sys
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dev_lab.dev import irpython
from dev_lab.dev.ircheck import load
from dev_lab.dev.irmodel import IRSchemaError

FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'


def _purge() -> None:
    for name in [n for n in sys.modules if n == 'sample_pkg' or n.startswith('sample_pkg.')]:
        del sys.modules[name]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))
    (root / 'src' / 'sample_pkg').mkdir(parents=True)
    (root / 'src' / 'sample_pkg' / '__init__.py').write_text('', encoding='utf-8')
    return root


@pytest.fixture
def ir(repo: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    irpython.write(load(repo))
    monkeypatch.syspath_prepend(str(repo / 'src'))
    _purge()
    yield SimpleNamespace(
        w=importlib.import_module('sample_pkg._ir_widgets'),
        s=importlib.import_module('sample_pkg._ir_samples'),
        codec=importlib.import_module('sample_pkg._ir_codec'),
        rt=importlib.import_module('sample_pkg._ir_runtime'),
        root=repo,
    )
    _purge()


def _widget(w: object, **change: object) -> object:
    fields = {
        'id': w.WidgetId('w-1'),
        'finish': w.Finish.painted,
        'mass': 0.25,
        'ambient_pressure': 101325.0,
        'seal_pressure': 301325.0,
    }
    return w.Widget(**{**fields, **change})


def _sample(s: object, n: int = 2, **change: object) -> object:
    fields = {
        'widget': 'w-1',
        'label': 'first',
        'calibrated': True,
        'count': 3,
        'gain': 1 + 2j,
        'time': np.linspace(0.0, 1.0, n),
        'position': np.zeros((n, 3)),
        'tags': ['a', 'b'],
    }
    return s.Sample(**{**fields, **change})


def test_every_generated_file_carries_its_fingerprint_and_is_ignored(repo: Path) -> None:
    ir = load(repo)
    written = irpython.write(ir)
    names = {p.name for p in written}
    templates = {'_ir_runtime.py', '_ir_surface.py', '_ir_codec.py'}
    assert names == {*templates, '_ir_ids.py', '_ir_widgets.py', '_ir_samples.py', '.gitignore'}
    first = (repo / 'src' / 'sample_pkg' / '_ir_widgets.py').read_text(encoding='utf-8').splitlines()[0]
    assert first == irpython.FINGERPRINT_PREFIX + irpython.fingerprint(ir, 'widgets')
    assert '_ir_*.py' in (repo / 'src' / 'sample_pkg' / '.gitignore').read_text(encoding='utf-8')
    assert irpython.write(ir) == (), 'an unchanged IR rewrites nothing'


def _imported(source: str) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split('.')[0])
    return names


def test_generated_python_holds_si_only_and_imports_no_unit_library(repo: Path) -> None:
    files = irpython.expected_files(load(repo))
    sources = {path.name: text for path, text in files.items() if path.suffix == '.py'}
    assert all('pint' not in _imported(text) for text in sources.values())
    assert 'import sample_units as _boundary' in sources['_ir_codec.py'], 'the codec delegates to the declared module'


def test_a_generated_module_importing_pint_is_refused(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = tmp_path / '_ir_codec.py'
    planted.write_text('import pint\n', encoding='utf-8')
    monkeypatch.setitem(irpython._TEMPLATES, '_ir_codec.py', planted)
    with pytest.raises(IRSchemaError, match=r'IR-UNIT-LIBRARY: .*_ir_codec\.py.*pint'):
        irpython.write(load(repo))
    assert not (repo / 'src' / 'sample_pkg' / '_ir_codec.py').exists(), 'a refused generation writes nothing'


def test_a_declaration_without_a_unit_boundary_is_refused(repo: Path) -> None:
    pyproject = repo / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8')
    pyproject.write_text(text.replace('boundary = "sample_units"\n', ''), encoding='utf-8')
    with pytest.raises(IRSchemaError, match='IR-NO-BOUNDARY'):
        load(repo)


def test_a_record_is_frozen_and_equal_by_content(ir: SimpleNamespace) -> None:
    widget = _widget(ir.w)
    with pytest.raises(FrozenInstanceError):
        widget.mass = 1.0
    assert widget == _widget(ir.w)
    assert widget != _widget(ir.w, mass=0.5)


def test_the_canonical_bytes_are_exact_and_omit_absent_optionals(ir: SimpleNamespace) -> None:
    widget = _widget(ir.w)
    expected = b'{"ambient_pressure":101325.0,"finish":"painted","id":"w-1","mass":0.25,"seal_pressure":301325.0}'
    assert widget.to_json() == expected
    assert widget.content_hash() == hashlib.sha256(expected).hexdigest()
    hot = _widget(ir.w, operating_temperature=1e-05)
    assert b'"operating_temperature":1e-05' in hot.to_json()


def test_the_content_hash_never_includes_the_version(ir: SimpleNamespace, tmp_path: Path) -> None:
    widget = _widget(ir.w)
    widget.dump(tmp_path / 'w.json')
    stored = json.loads((tmp_path / 'w.json').read_bytes())
    assert stored['schema_version'] == '1.0.0'
    assert stored['record'] == 'widgets.Widget'
    assert ir.rt.canonical(stored['value']) == widget.to_json()


def test_arrays_serialize_as_little_endian_base64_and_round_trip(ir: SimpleNamespace) -> None:
    sample = _sample(ir.s)
    tree = json.loads(sample.to_json())
    raw = base64.b64decode(tree['time']['data'])
    assert np.frombuffer(raw, dtype='<f8').tolist() == [0.0, 1.0]
    assert tree['position']['shape'] == [2, 3]
    assert tree['gain'] == [1.0, 2.0]
    again = ir.s.Sample.from_json(sample.to_json())
    assert again == sample
    assert not again.time.flags.writeable


def test_a_shape_error_names_its_path_and_both_sides(ir: SimpleNamespace) -> None:
    with pytest.raises(ir.rt.IRValidationError, match=r'^Sample\.position\.shape\[1\]: expected 3, got 2$'):
        _sample(ir.s, position=np.zeros((2, 2)))
    with pytest.raises(ir.rt.IRValidationError, match=r'Sample\.position\.shape\[0\]: expected n = 2'):
        _sample(ir.s, position=np.zeros((3, 3)))
    with pytest.raises(ir.rt.IRValidationError, match=r'Sample\.time\.dtype: expected float64, got float32'):
        _sample(ir.s, time=np.zeros(2, dtype=np.float32))
    with pytest.raises(ir.rt.IRValidationError, match=r'Sample\.time\.shape\[0\]: expected n >= 1, got 0'):
        _sample(ir.s, n=0)


def test_symbolic_dims_bind_across_the_whole_record_tree(ir: SimpleNamespace) -> None:
    batch = {'widgets': [], 'hit_offsets': np.array([0], dtype=np.int64), 'hit_times': np.zeros(0)}
    ir.s.Batch(samples=[_sample(ir.s, 2), _sample(ir.s, 2)], **batch)
    with pytest.raises(ir.rt.IRValidationError, match=r'^Batch\.samples\[1\]\.time\.shape\[0\]: expected n = 2'):
        ir.s.Batch(samples=[_sample(ir.s, 2), _sample(ir.s, 3)], **batch)


def test_a_unique_by_list_is_sorted_by_key_and_refuses_a_duplicate(ir: SimpleNamespace) -> None:
    rest = {'samples': [], 'hit_offsets': np.array([0], dtype=np.int64), 'hit_times': np.zeros(0)}
    batch = ir.s.Batch(widgets=[_widget(ir.w, id='w-2'), _widget(ir.w, id='w-1')], **rest)
    assert [w.id for w in batch.widgets] == ['w-1', 'w-2']
    with pytest.raises(ir.rt.IRValidationError, match=r"Batch\.widgets: expected unique id, got duplicate 'w-1'"):
        ir.s.Batch(widgets=[_widget(ir.w), _widget(ir.w)], **rest)


def test_csr_offsets_are_checked_against_their_values(ir: SimpleNamespace) -> None:
    good = {'widgets': [], 'samples': [], 'hit_times': np.zeros(3)}
    ir.s.Batch(hit_offsets=np.array([0, 1, 3], dtype=np.int64), **good)
    with pytest.raises(ir.rt.IRValidationError, match=r'Batch\.hit_offsets\[-1\]: expected 3, got 2'):
        ir.s.Batch(hit_offsets=np.array([0, 2], dtype=np.int64), **good)
    with pytest.raises(ir.rt.IRValidationError, match='non-decreasing'):
        ir.s.Batch(hit_offsets=np.array([0, 3, 1, 3], dtype=np.int64), **good)


def test_non_finite_and_wrong_kinds_are_refused(ir: SimpleNamespace) -> None:
    with pytest.raises(ir.rt.IRValidationError, match='IR-NON-FINITE'):
        _widget(ir.w, mass=float('nan'))
    with pytest.raises(ir.rt.IRValidationError, match=r'Widget\.finish: expected Finish, got str'):
        _widget(ir.w, finish='painted')
    with pytest.raises(ir.rt.IRValidationError, match=r'Sample\.count: expected int, got bool'):
        _sample(ir.s, count=True)


def test_a_reader_refuses_an_older_major_and_an_unknown_field_by_name(ir: SimpleNamespace, tmp_path: Path) -> None:
    value = json.loads(_widget(ir.w).to_json())
    old = tmp_path / 'old.json'
    old.write_bytes(ir.rt.canonical({'record': 'widgets.Widget', 'schema_version': '0.9.0', 'value': value}))
    with pytest.raises(ir.rt.IRReadError, match=r'IR-OLD-RECORD: .*old\.json: schema_version 0\.9\.0.*migrate'):
        ir.w.Widget.load(old)
    newer = tmp_path / 'newer.json'
    newer.write_bytes(
        ir.rt.canonical({'record': 'widgets.Widget', 'schema_version': '1.1.0', 'value': {**value, 'color': 'red'}})
    )
    with pytest.raises(ir.rt.IRReadError, match=r'IR-UNKNOWN-FIELD: .*Widget\.color.*generate'):
        ir.w.Widget.load(newer)
    current = tmp_path / 'current.json'
    _widget(ir.w).dump(current)
    assert ir.w.Widget.load(current) == _widget(ir.w)


def test_the_codec_converts_once_at_the_boundary_and_back(ir: SimpleNamespace) -> None:

    mapping = tomllib.loads((ir.root / 'input_widget.toml').read_text(encoding='utf-8'))
    widget = ir.codec.from_boundary(ir.w.Widget, mapping)
    assert widget.mass == pytest.approx(0.25, abs=1e-12)
    assert widget.operating_temperature == pytest.approx(358.15, abs=1e-9)
    assert widget.ambient_pressure == pytest.approx(101325.0, abs=1e-6)
    assert widget.seal_pressure == pytest.approx(301325.0, abs=1e-6)
    shown = ir.codec.to_boundary(widget, {'seal_pressure': 'bar', 'mass': 'g'})
    assert shown['seal_pressure'] == '2.0 bar'
    assert ir.codec.from_boundary(ir.w.Widget, shown) == widget


def test_db_converts_through_the_catalogue_reference(ir: SimpleNamespace) -> None:
    sample = ir.codec.from_boundary(
        ir.s.Sample,
        {
            'widget': 'w-1',
            'label': 'x',
            'calibrated': False,
            'count': 0,
            'gain': 1.0,
            'time': [0.0],
            'position': [[0.0, 0.0, 0.0]],
            'tags': [],
            'level': '94 dB',
        },
    )
    assert sample.level == pytest.approx(2e-5 * 10 ** (94 / 20), abs=1e-9)
    with pytest.raises(ir.rt.IRValidationError, match=r'Widget\.mass: .*IR-BOUNDARY-UNIT'):
        ir.codec.from_boundary(ir.w.Widget, {'mass': '3 m'})


def test_an_edited_schema_makes_the_generated_module_refuse_to_import(ir: SimpleNamespace) -> None:
    schema = ir.root / 'ir' / 'widgets.toml'
    schema.write_text(schema.read_text(encoding='utf-8') + '\n# an edit\n', encoding='utf-8')
    _purge()
    with pytest.raises(ImportError, match='IR-STALE-GENERATED'):
        importlib.import_module('sample_pkg._ir_widgets')


OWNER = """
[record.Owner]
doc = "Planted control: widgets holds a samples record by value and by id, while samples already holds widgets."
[record.Owner.field.id]
type = "id:Owner"
[record.Owner.field.favorite]
type = "id:samples.Tag"
[record.Owner.field.batch]
type = "record:samples.Batch"
"""
TAG = """
[record.Tag]
[record.Tag.field.id]
type = "id:Tag"
[record.Tag.field.owner]
type = "id:widgets.Owner"
"""


def test_two_modules_referencing_each_other_import_without_a_cycle(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with (repo / 'ir' / 'widgets.toml').open('a', encoding='utf-8') as handle:
        handle.write(OWNER)
    with (repo / 'ir' / 'samples.toml').open('a', encoding='utf-8') as handle:
        handle.write(TAG)
    irpython.write(load(repo))
    monkeypatch.syspath_prepend(str(repo / 'src'))
    _purge()
    try:
        w = importlib.import_module('sample_pkg._ir_widgets')
        s = importlib.import_module('sample_pkg._ir_samples')
        batch = s.Batch(widgets=[], samples=[], hit_offsets=np.array([0], dtype=np.int64), hit_times=np.zeros(0))
        owner = w.Owner(id='o-1', favorite='t-1', batch=batch)
        tag = s.Tag(id='t-1', owner='o-1')
        assert w.Owner.from_json(owner.to_json()) == owner
        assert s.Tag.from_json(tag.to_json()) == tag
        with pytest.raises(importlib.import_module('sample_pkg._ir_runtime').IRValidationError, match=r'Owner\.batch'):
            w.Owner(id='o-1', favorite='t-1', batch=tag)
    finally:
        _purge()
