"""irmodel Part A (a consumer's draft-grammar request): the draft grammar is ADMITTED as metadata.

Defaults of any type, ``default_from``, multi-key ``unique_by``, ``one_of`` / ``requires``, ``foreign:`` / ``rest``,
``string`` / ``array`` / ``fill``, ``nonempty`` and unit-carrying ``minimum`` / ``maximum`` load; every ill-typed or
unknown one is refused by name (PLANTED: each refusal row is one edit of the admitted fixture); ``irschema rust``
generates the types and exposes the metadata, and the generated crate builds and agrees with the Python byte for byte.
Resolving and enforcing the metadata is Part B, not here.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import lab_commons.launch as _door
import pytest
from _cargo_probe import usable_cargo

from dev_lab.dev import irpython, irrust
from dev_lab.dev._ir_errors import IRSchemaError
from dev_lab.dev.ircheck import bounds, default_si, load
from dev_lab.dev.irmodel import IR, DefaultFrom

DATA = Path(__file__).parent / 'data' / 'ir_schema'
D = 'ir/drafts.toml'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = Path(shutil.copytree(DATA / 'repo', tmp_path / 'repo'))
    _edit(root, 'pyproject.toml', 'samples = "ir/samples.toml"', f'samples = "ir/samples.toml"\ndrafts = "{D}"')
    (root / 'src' / 'sample_pkg').mkdir(parents=True)
    (root / 'src' / 'sample_pkg' / '__init__.py').write_text('', encoding='utf-8')
    return root


def _edit(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding='utf-8')
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def _ir(repo: Path) -> IR:
    ir = load(repo)
    assert ir is not None
    return ir


def test_the_draft_grammar_loads_as_declared(repo: Path) -> None:
    ir = load(repo)
    assert ir is not None
    drafts = ir.modules['drafts'].records
    connection = drafts['Connection']
    assert (connection.string, connection.one_of) == ('library', ('library', 'generator', 'paths'))
    assert connection.field('parameters').requires == 'generator'
    assert connection.field('paths').nonempty
    parameters = drafts['Parameters']
    assert parameters.rest == 'coil_pkg.connection'
    assert parameters.field('hidden').default == [16, 16]
    assert drafts['Point'].array == ('x_axis', 'y_axis')
    assert drafts['Flare'].fill == ('start', 'end')
    iga = drafts['Isogeometric']
    assert iga.field('continuity').default_from == DefaultFrom('space.order', 1, -1)
    assert iga.field('flare').default == {'start': 0.25, 'end': 0.5}
    assert (iga.field('lead').default, default_si(ir, iga.field('lead'))) == ('5 mm', 0.005)
    status = drafts['FieldReference'].field('status').type
    assert (status.kind, status.target) == ('foreign', 'lab_commons.outcomes.Status')
    assert drafts['Result'].field('fields').unique_by == ('selection', 'refinement_factor')
    # Bounds cross into absolute SI once: "500 mm" is 0.5 m; a bare bound on a field without a quantity stays.
    assert bounds(ir, drafts['Point'].field('x_axis')) == (-0.5, 0.5)
    assert bounds(ir, drafts['Flare'].field('start')) == (0.0, 1.0)
    assert bounds(ir, drafts['Point'].field('y_axis')) == (None, None)
    # The single-key form is unchanged: one name is a one-tuple.
    assert ir.modules['samples'].records['Batch'].field('widgets').unique_by == ('id',)


def test_a_default_needs_no_consumer(repo: Path) -> None:
    """D213 resolves every default through one resolver: ``default_consumer`` is optional, still refused alone."""
    ir = load(repo)
    assert ir is not None
    assert ir.modules['drafts'].records['Parameters'].field('hidden').default_consumer == ''


_I = '[record.Isogeometric.field.continuity]\ntype = "int"\noptional = true\n'
_H = 'default = [16, 16]'
_X = 'minimum = "-0.5 m"'
REFUSALS = [
    # (code, old, new, what the message names)
    ('IR-FIELD-SPEC', _H, 'default = [16, "a"]', "default [16, 'a']"),  # a list default of the wrong item type
    ('IR-FIELD-SPEC', _H, 'default = 16', 'default 16'),  # a scalar where a list belongs
    ('IR-FIELD-SPEC', 'optional = true\ndefault = { start', 'optional = true\ndefault = { begin', 'default'),
    ('IR-FIELD-SPEC', 'default = { start = 0.25, end = 0.5 }', 'default = { start = 0.25 }', 'default'),
    ('IR-FIELD-SPEC', 'optional = true\nrequires', 'optional = true\ndefault = "spiral"\nrequires', 'default'),
    ('IR-FIELD-SPEC', _H, f'{_H}\ndefault_from = {{ facet = "x" }}', 'exclusive'),
    ('IR-FIELD-SPEC', '"space.order"', '"Space.order"', 'facet'),
    ('IR-FIELD-SPEC', 'offset = -1 }', 'offset = -1, slope = 2 }', "'slope'"),
    ('IR-FIELD-SPEC', 'offset = -1 }', 'offset = -0.5 }', 'offset'),  # an int field's offset is an int
    ('IR-FIELD-SPEC', _I, _I.replace('"int"', '"str"'), 'affine'),
    ('IR-FIELD-SPEC', _I, _I.replace('optional = true\n', ''), 'required field'),
    ('IR-FIELD-SPEC', '"refinement_factor"]', '"nowhere"]', "'nowhere'"),
    ('IR-FIELD-SPEC', '"refinement_factor"]', '"selection"]', 'twice'),
    ('IR-FIELD-SPEC', '"refinement_factor"]', '"status"]', "'status'"),  # a foreign is no key
    ('IR-FIELD-SPEC', 'one_of = ["library", "generator", "paths"]', 'one_of = ["library"]', 'at least two'),
    ('IR-FIELD-SPEC', '"generator", "paths"]', '"generator", "nowhere"]', "'nowhere'"),
    ('IR-FIELD-SPEC', 'one_of = ["library"', 'one_of = ["generator", "parameters"]\nx_one_of = ["library"', 'x_one_of'),
    ('IR-FIELD-SPEC', 'requires = "generator"', 'requires = "nowhere"', "'nowhere'"),
    ('IR-FIELD-SPEC', 'requires = "generator"', 'requires = "parameters"', 'sibling'),
    ('IR-FIELD-SPEC', 'type = "record:Parameters"\noptional = true\n', 'type = "record:Parameters"\n', 'optional'),
    ('IR-FIELD-SPEC', 'rest = "foreign:coil_pkg.connection"', 'rest = "coil_pkg.connection"', 'rest'),
    ('IR-FIELD-SPEC', '[record.Parameters.field.hidden]', '[record.Parameters.field.rest]', 'rest'),
    ('IR-UNKNOWN-TYPE', '"foreign:lab_commons.outcomes.Status"', '"foreign:Status"', 'foreign'),
    ('IR-FIELD-SPEC', 'string = "library"', 'string = "paths"', 'paths'),
    ('IR-FIELD-SPEC', 'string = "library"', 'string = "nowhere"', 'nowhere'),
    ('IR-FIELD-SPEC', 'array = ["x_axis", "y_axis"]', 'array = ["x_axis", "z_axis"]', "'z_axis'"),
    ('IR-FIELD-SPEC', 'array = ["x_axis", "y_axis"]', 'array = []', 'at least one'),
    ('IR-FIELD-SPEC', 'fill = ["start", "end"]', 'fill = ["start", 3]', 'fill'),
    ('IR-FIELD-SPEC', 'type = "str"\noptional = true\n', 'type = "str"\noptional = true\nnonempty = true\n', 'list'),
    ('IR-FIELD-SPEC', 'type = "list:int"\nnonempty = true', 'type = "list:int"\nnonempty = "yes"', 'nonempty'),
    ('IR-FIELD-SPEC', 'type = "str"\noptional = true\n', 'type = "str"\noptional = true\nminimum = 1\n', 'minimum'),
    ('IR-FIELD-SPEC', _X, 'minimum = -0.5', 'carries its unit'),
    ('IR-FIELD-SPEC', 'default = "5 mm"', 'default = 0.005', 'carries its unit'),  # a default too
    ('IR-FIELD-SPEC', 'default = "5 mm"', 'default = "5 s"', 'length'),  # TOLERANCE-CARRIES-A-UNIT
    ('IR-FIELD-SPEC', _X, 'minimum = "-0.5 s"', 'length'),  # the wrong dimension
    ('IR-FIELD-SPEC', _X, 'minimum = "1 m"', 'exceeds'),
    ('IR-FIELD-SPEC', 'minimum = 0\n', 'minimum = "0 m"\n', 'bare'),  # no quantity: a bare number
    ('IR-FIELD-SPEC', 'minimum = 2', 'minimum = 2.5', 'bare int'),
    ('IR-FIELD-SPEC', _H, f'{_H}\nconsumers = ["solve"]', "'consumers'"),  # withdrawn by D215
    ('IR-FIELD-SPEC', 'fill = ["start", "end"]', 'fill = ["start", "end"]\napplies_when = "transient"', 'applies_when'),
]


@pytest.mark.parametrize(('code', 'old', 'new', 'named'), REFUSALS, ids=[f'{r[0]}-{i}' for i, r in enumerate(REFUSALS)])
def test_each_ill_typed_or_unknown_attribute_is_refused_by_name(
    repo: Path, code: str, old: str, new: str, named: str
) -> None:
    _edit(repo, D, old, new)
    with pytest.raises(IRSchemaError) as caught:
        load(repo)
    assert caught.value.code == code
    assert named in str(caught.value), str(caught.value)
    assert ' -- ' in str(caught.value), 'a refusal names its door after " -- "'


def _python(repo: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    irpython.write(_ir(repo))
    monkeypatch.syspath_prepend(str(repo / 'src'))
    for name in [n for n in sys.modules if n.startswith('sample_pkg')]:
        del sys.modules[name]
    return importlib.import_module('sample_pkg._ir_drafts')


def _reference(d: ModuleType, selection: str, factor: int | None) -> object:
    return d.FieldReference(selection=[selection], refinement_factor=factor, status={'state': 'ok'})


def test_a_multi_key_list_refuses_a_duplicate_tuple_only(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v1's own key: a list:str and an optional int; an absent key orders first (null < number < string < array)."""
    d = _python(repo, monkeypatch)
    # Two items sharing one key but not the tuple are admitted, and stored in tuple order.
    result = d.Result(fields=[_reference(d, 'b', 1), _reference(d, 'a', 2), _reference(d, 'a', None)])
    assert [(f.selection, f.refinement_factor) for f in result.fields] == [(('a',), None), (('a',), 2), (('b',), 1)]
    # PLANTED: the same tuple twice is refused, naming both keys and the duplicate as JSON.
    with pytest.raises(ValueError, match=r'unique selection, refinement_factor, got duplicate \[\["a"\],1\]'):
        d.Result(fields=[_reference(d, 'a', 1), _reference(d, 'a', 1)])
    stage = d.StageRetention
    kept = d.Result(fields=[], stages=[stage(stage=d.Generator.wave, days=1), stage(stage=d.Generator.lap, days=2)])
    assert [s.stage for s in kept.stages] == [d.Generator.lap, d.Generator.wave], 'an enum key orders by its value'
    with pytest.raises(ValueError, match='duplicate "lap"'):
        d.Result(fields=[], stages=[stage(stage=d.Generator.lap, days=1), stage(stage=d.Generator.lap, days=2)])


def test_a_foreign_rest_keeps_every_undeclared_key(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _python(repo, monkeypatch)
    raw = b'{"n_layer":2,"pole_count":8,"turns":{"per":"cell"}}'
    parameters = d.Parameters.from_json(raw)
    assert (parameters.pole_count, parameters.rest) == (8, {'n_layer': 2, 'turns': {'per': 'cell'}})
    assert parameters.to_json() == raw
    # PLANTED: a record without a rest still refuses an unknown key.
    with pytest.raises(ValueError, match='IR-UNKNOWN-FIELD'):
        d.Path.from_json(b'{"cells":[1],"name":"a","n_layer":2}')
    # A rest may not shadow a declared field.
    with pytest.raises(ValueError, match='declared field'):
        d.Parameters(rest={'pole_count': 4})


def test_the_rust_exposes_the_admitted_metadata(repo: Path) -> None:
    text = irrust.render(_ir(repo))
    module = text[text.index('pub mod ir_drafts {') :]
    for line in (
        'pub const ONE_OF: &\'static [&\'static str] = &["library", "generator", "paths"];',
        'pub const REQUIRES: &\'static [(&\'static str, &\'static str)] = &[("parameters", "generator")];',
        'pub const NONEMPTY: &\'static [&\'static str] = &["paths"];',
        'pub const STRING: Option<&\'static str> = Some("library");',
        'pub const REST: Option<&\'static str> = Some("coil_pkg.connection");',
        'pub const ARRAY: &\'static [&\'static str] = &["x_axis", "y_axis"];',
        'pub const FILL: &\'static [&\'static str] = &["start", "end"];',
        '= &[("x_axis", Some(-0.5), Some(0.5))];',
        '= &[("start", Some(0.0), Some(1.0))];',
        '= &[("hidden", "[16,16]")];',
        '= &[("continuity", "space.order", 1.0, -1.0)];',
        '= &[("axis", "[0.0,0.0,1.0]"), ("lead", "0.005"), ("flare", "{\\"end\\":0.5,\\"start\\":0.25}")];',
        'pub status: serde_json::Value,',
        '#[serde(flatten)]',
        '"selection, refinement_factor"',
        'ir_runtime::sort_by_key(v, "fields", &["selection", "refinement_factor"]);',
    ):
        assert line in module, line
    parameters = module[module.index('pub struct Parameters') - 80 : module.index('pub struct Parameters')]
    assert 'deny_unknown_fields' not in parameters, 'a record with a rest admits unknown keys'
    path = module[module.index('pub struct Path ') - 80 : module.index('pub struct Path ')]
    assert 'deny_unknown_fields' in path, 'PLANTED: a record without a rest still denies them'


_MANIFEST = """[package]
name = "ir_drafts"
version = "0.0.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ndarray = "0.17"
"""
_MAIN = """include!(concat!(env!("CARGO_MANIFEST_DIR"), "/ir.rs"));

fn main() {
    let args: Vec<String> = std::env::args().collect();
    for pair in args[1..].chunks(2) {
        let text = std::fs::read_to_string(&pair[1]).unwrap();
        let out = match pair[0].as_str() {
            "drafts.Result" => ir_drafts::Result::from_json(&text).map(|r| r.to_json()),
            "drafts.Parameters" => ir_drafts::Parameters::from_json(&text).map(|r| r.to_json()),
            other => panic!("unknown record {other}"),
        };
        match out {
            Ok(s) => println!("OK {s}"),
            Err(e) => println!("ERR {e}"),
        }
    }
    println!("BOUNDS {:?}", ir_drafts::Point::FIELD_BOUNDS);
}
"""


def test_the_generated_rust_builds_and_agrees_with_the_python(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cargo, unusable = usable_cargo()
    if cargo is None:
        pytest.xfail(f'no usable cargo on this host ({unusable}): the Rust half cannot build here')
    d = _python(repo, monkeypatch)
    crate = tmp_path / 'crate'
    (crate / 'src').mkdir(parents=True)
    (crate / 'Cargo.toml').write_text(_MANIFEST, encoding='utf-8')
    (crate / 'src' / 'main.rs').write_text(_MAIN, encoding='utf-8')
    irrust.write(_ir(repo), crate)
    result = d.Result(
        fields=[_reference(d, 'b', 1), _reference(d, 'a', 2), _reference(d, 'a', None)],
        stages=[d.StageRetention(stage=d.Generator.wave, days=1), d.StageRetention(stage=d.Generator.lap, days=2)],
        connection=d.Connection(generator=d.Generator.lap, parameters=d.Parameters(pole_count=4, rest={'x': [1.5]})),
    )
    reversed_fields = json.loads(result.to_json())
    reversed_fields['fields'].reverse()
    duplicate = json.loads(result.to_json())
    duplicate['fields'][1] = duplicate['fields'][0]
    stages = json.loads(result.to_json())
    stages['stages'][1]['stage'] = stages['stages'][0]['stage']
    raws = {
        'result': ('drafts.Result', result.to_json()),
        'reversed': ('drafts.Result', json.dumps(reversed_fields).encode()),
        'duplicate': ('drafts.Result', json.dumps(duplicate).encode()),
        'stages': ('drafts.Result', json.dumps(stages).encode()),
        'rest': ('drafts.Parameters', b'{"pole_count":8,"n_layer":2,"turns":{"per":"cell"}}'),
    }
    cases = []
    for key, (record, raw) in raws.items():
        path = tmp_path / f'{key}.json'
        path.write_bytes(raw)
        cls = {'drafts.Result': d.Result, 'drafts.Parameters': d.Parameters}[record]
        try:
            expected = 'OK ' + cls.from_json(raw).to_json().decode()
        except ValueError as error:
            expected = f'ERR {error}'
        cases.append((record, path, expected))
    assert cases[2][2] == 'ERR Result.fields: expected unique selection, refinement_factor, got duplicate [["a"],null]'
    assert cases[3][2] == 'ERR Result.stages: expected unique stage, got duplicate "lap"'
    done = _door.run(
        [cargo, 'run', '--offline', '-q', '--manifest-path', str(crate / 'Cargo.toml'), '--']
        + [a for record, path, _ in cases for a in (record, str(path))],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=900,
        env={**os.environ, 'CARGO_TARGET_DIR': str(tmp_path / 'target'), 'CARGO_BUILD_JOBS': '1'},
    )
    if done.returncode != 0 and 'offline' in done.stderr:
        pytest.xfail(f'the local cargo registry lacks a crate this build needs: {done.stderr.strip()[-300:]}')
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[:-1] == [expected for *_, expected in cases]
    assert lines[-1] == 'BOUNDS [("x_axis", Some(-0.5), Some(0.5))]'
