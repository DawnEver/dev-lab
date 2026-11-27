"""FAM-08 IR asks: optional-field defaults carried, keyword field names escaped, enum values from a terms table.

Each carries its planted control.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from dev_lab.dev import irpython, irrust
from dev_lab.dev._ir_errors import IRSchemaError
from dev_lab.dev.ircheck import load

FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'
W = 'ir/widgets.toml'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))
    (root / 'src' / 'sample_pkg').mkdir(parents=True, exist_ok=True)
    (root / 'src' / 'sample_pkg' / '__init__.py').write_text('', encoding='utf-8')
    return root


def _edit(repo: Path, old: str, new: str, relative: str = W) -> None:
    path = repo / relative
    text = path.read_text(encoding='utf-8')
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def _purge() -> None:
    for name in [n for n in sys.modules if n == 'sample_pkg' or n.startswith('sample_pkg.')]:
        del sys.modules[name]


@pytest.fixture
def imported(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    def go() -> object:
        ir = load(repo)
        assert ir is not None
        irpython.write(ir)
        monkeypatch.syspath_prepend(str(repo / 'src'))
        _purge()
        return importlib.import_module('sample_pkg._ir_widgets')

    yield go
    _purge()


_DEFAULT = 'doc = "Absent when the widget has no rated temperature."'


def test_an_optional_field_carries_its_default_and_consumer(repo: Path) -> None:
    _edit(repo, _DEFAULT, f'{_DEFAULT}\ndefault = 293.15\ndefault_consumer = "compile"')
    ir = load(repo)
    assert ir is not None
    f = ir.modules['widgets'].records['Widget'].field('operating_temperature')
    assert (f.default, f.default_consumer) == (293.15, 'compile')


@pytest.mark.parametrize(
    ('field', 'extra'),
    [
        ('mass', 'default = 1.0\ndefault_consumer = "compile"'),  # PLANTED: a required field never has one
        ('operating_temperature', 'default = 1.0'),  # a default names who fills it
        ('operating_temperature', 'default = "hot"\ndefault_consumer = "compile"'),  # of the field's type
        ('finish', 'optional = true\ndefault = "chrome"\ndefault_consumer = "compile"'),  # an enum value
    ],
)
def test_a_default_is_refused_where_it_cannot_hold(repo: Path, field: str, extra: str) -> None:
    anchor = f'[record.Widget.field.{field}]\n'
    _edit(repo, anchor, f'{anchor}{extra}\n')
    with pytest.raises(IRSchemaError, match='IR-FIELD-SPEC'):
        load(repo)


def test_a_default_never_fills_on_read(repo: Path, imported) -> None:
    """The codec validates only (D135): the named consumer fills it, so an absent optional stays None."""
    _edit(repo, _DEFAULT, f'{_DEFAULT}\ndefault = 293.15\ndefault_consumer = "compile"')
    widgets = imported()
    assert widgets.Widget.__dataclass_fields__['operating_temperature'].default is None


def test_keyword_field_names_stay_in_the_toml_and_are_escaped_in_generated_code(repo: Path, imported) -> None:
    _edit(
        repo,
        '[record.Widget.field.mass]',
        '[record.Widget.field.from]\ntype = "str"\noptional = true\n'
        '[record.Widget.field.use]\ntype = "str"\noptional = true\n[record.Widget.field.mass]',
    )
    widgets = imported()
    w = widgets.Widget(
        id='w1', finish=widgets.Finish.raw, mass=1.0, ambient_pressure=1e5, seal_pressure=1e5, from_='a', use='b'
    )
    tree = w.to_json().decode()
    assert '"from":"a"' in tree.replace(' ', '')
    assert '"from_"' not in tree
    back = type(w).from_json(w.to_json())
    assert back.from_ == 'a'
    loaded = load(repo)
    assert loaded is not None
    rust = irrust.render(loaded)
    assert 'pub r#use: Option<String>' in rust
    assert 'pub r#from' not in rust  # PLANTED: `from` is not a Rust keyword, so it stays bare
    assert 'pub from: Option<String>' in rust


def test_a_bad_field_name_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: the keyword door widens nothing else -- an UpperCamel field is refused."""
    _edit(repo, '[record.Widget.field.mass]', '[record.Widget.field.Mass]')
    with pytest.raises(IRSchemaError, match='IR-FIELD-SPEC'):
        load(repo)


def test_enum_values_come_from_a_terms_table(repo: Path, imported) -> None:
    (repo / 'terms.toml').write_text(
        '[finish.raw]\nzh = "a"\n[finish.painted]\nzh = "b"\n[finish.chromed]\nzh = "c"\n', encoding='utf-8'
    )
    _edit(repo, 'values = ["raw", "painted", "anodized"]', 'terms = "terms.toml"\ntable = "finish"')
    ir = load(repo)
    assert ir is not None
    assert ir.modules['widgets'].enums['Finish'].values == ('raw', 'painted', 'chromed')
    widgets = imported()
    assert [m.value for m in widgets.Finish] == ['raw', 'painted', 'chromed']


@pytest.mark.parametrize(
    'spec',
    [
        'values = ["raw"]\nterms = "terms.toml"\ntable = "finish"',  # exactly one source
        'terms = "terms.toml"\ntable = "nowhere"',  # the table exists
        'terms = "terms.toml"',  # names its table
    ],
)
def test_a_terms_enum_is_refused_where_it_cannot_be_read(repo: Path, spec: str) -> None:
    (repo / 'terms.toml').write_text('[finish.raw]\n', encoding='utf-8')
    _edit(repo, 'values = ["raw", "painted", "anodized"]', spec)
    with pytest.raises(IRSchemaError, match='IR-FIELD-SPEC'):
        load(repo)
