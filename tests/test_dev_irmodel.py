"""The IR schema loader (docs-src/dev/ir-schema.md): the fixture repo loads, and every refusal names its door."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dev_lab.dev.ircheck import load
from dev_lab.dev.irmodel import IRSchemaError

FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))


def test_the_fixture_repo_loads_every_module_record_and_quantity(repo: Path) -> None:
    ir = load(repo)
    assert ir is not None
    assert ir.declaration.version == (1, 0, 0)
    assert set(ir.modules) == {'widgets', 'samples'}
    widget = ir.modules['widgets'].records['Widget']
    assert [f.name for f in widget.fields][:3] == ['id', 'finish', 'mass']
    assert widget.field('seal_pressure').gauge_reference == 'ambient_pressure'
    batch = ir.modules['samples'].records['Batch']
    widgets = batch.field('widgets')
    assert (widgets.type.kind, widgets.type.item.kind, widgets.type.item.target) == ('list', 'record', 'widgets.Widget')
    assert widgets.unique_by == 'id'
    assert ir.modules['samples'].dims == {'n': (1, None)}
    assert ir.quantities['sound_pressure'].db == (2e-5, 20)
    assert ir.quantities['force'].dimension == (1, 1, -2, 0, 0, 0, 0)


def test_a_repo_without_a_declaration_has_no_ir(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    assert load(tmp_path) is None


def _edit(repo: Path, relative: str, old: str, new: str) -> None:
    path = repo / relative
    text = path.read_text(encoding='utf-8')
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


W, S, Q = 'ir/widgets.toml', 'ir/samples.toml', 'ir/quantities.toml'
REFUSALS = [
    ('IR-UNKNOWN-TYPE', W, 'type = "enum:Finish"', 'type = "enum:Paint"'),
    ('IR-UNKNOWN-TYPE', S, 'type = "str"', 'type = "text"'),
    ('IR-UNKNOWN-TYPE', S, 'type = "record:widgets.Widget"', 'type = "record:nowhere.Widget"'),
    ('IR-RECORD-CYCLE', S, 'type = "list:record:Sample"', 'type = "list:record:Batch"'),
    ('IR-ID-WITHOUT-ID-FIELD', W, 'type = "id:Widget"', 'type = "str"'),
    ('IR-UNIT-IN-SCHEMA', W, 'quantity = "mass"', 'quantity = "kg"'),
    ('IR-UNKNOWN-QUANTITY', W, 'quantity = "mass"', 'quantity = "heft"'),
    ('IR-QUANTITY-ON-NON-FLOAT', S, 'type = "int"', 'type = "int"\nquantity = "time"'),
    ('IR-QUANTITY-ON-NON-FLOAT', S, 'csr_values = "hit_times"', 'csr_values = "hit_times"\nquantity = "time"'),
    ('IR-NON-SI-UNIT', Q, 'unit = "kg"', 'unit = "g"'),
    ('IR-NON-SI-UNIT', Q, 'unit = "K"', 'unit = "degC"'),
    ('IR-DIMENSION-MISMATCH', Q, 'unit = "m"\ndimension = "0 1 0 0 0 0 0"', 'unit = "m"\ndimension = "0 2 0 0 0 0 0"'),
    ('IR-DIMENSION-MISMATCH', Q, 'flow = "current"', 'flow = "velocity"'),
    ('IR-FIELD-SPEC', S, 'type = "bool"', 'type = "bool"\ndtype = "float64"'),
    ('IR-FIELD-SPEC', S, 'type = "bool"', 'type = "bool"\ndefault = true'),
    ('IR-FIELD-SPEC', S, 'shape = ["n"]', 'shape = ["n", 2.5]'),
    ('IR-FIELD-SPEC', S, 'unique_by = "id"', 'unique_by = "mass"'),
    ('IR-FIELD-SPEC', S, 'csr_values = "hit_times"', 'csr_values = "nowhere"'),
    ('IR-FIELD-SPEC', W, 'gauge_reference = "ambient_pressure"', 'gauge_reference = "mass"'),
    ('IR-FIELD-SPEC', S, 'type = "list:str"', 'type = "list:array"'),
    ('IR-FIELD-SPEC', W, 'values = ["raw", "painted", "anodized"]', 'values = ["raw", "class"]'),
]


@pytest.mark.parametrize(
    ('code', 'relative', 'old', 'new'), REFUSALS, ids=[f'{r[0]}-{i}' for i, r in enumerate(REFUSALS)]
)
def test_each_refusal_names_its_code_and_a_door(repo: Path, code: str, relative: str, old: str, new: str) -> None:
    _edit(repo, relative, old, new)
    with pytest.raises(IRSchemaError) as caught:
        load(repo)
    assert caught.value.code == code
    assert ' -- ' in str(caught.value), 'a refusal names its door after " -- "'
