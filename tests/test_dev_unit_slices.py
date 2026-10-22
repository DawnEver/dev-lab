"""Every slice of the unseen unit-in-name gap is measured as a NAMED SET, and a declared non-unit is never counted.

Each test PLANTS a source, drives the REAL :func:`~dev_lab.dev.unit_slices.measure` over it, and asserts the exact
set of ``path:line:name`` keys -- a set, not a count, because a count is blind to a swap (``NAMED-SETS-NOT-COUNTS``).
The opposite direction rides along in the same plant: the site the slice must NOT count is written next to the one it
must, and the exceptions control asserts each declared row moves its site to ``exempt`` rather than dropping it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import unit_slices
from dev_lab.dev.unit_slices import DECLARED_EXCEPTIONS, SLICES, measure


def _plant(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


def _keys(tmp_path: Path, name: str, text: str, slice_name: str) -> tuple[set[str], set[str]]:
    report = measure([_plant(tmp_path, name, text)], root=tmp_path)
    part = report.slices[slice_name]
    return {s.key() for s in part.sites}, {s.key() for s in part.exempt}


_LOCAL = """
GAP = 1.0
def f():
    elapsed_sec = 0.0
    span_mm = 2.0
    width_mm = Q_(2.0, 'mm')
    gap = 3.0
    return elapsed_sec, span_mm, width_mm, gap
"""


def test_a_function_local_spelling_a_unit_is_counted_and_a_quantity_local_is_exempt(tmp_path: Path) -> None:
    sites, exempt = _keys(tmp_path, 'a.py', _LOCAL, 'python_local')
    assert sites == {'a.py:5:span_mm'}
    assert exempt == {'a.py:6:width_mm'}


def test_an_attribute_target_is_counted_at_any_scope(tmp_path: Path) -> None:
    text = 'class C:\n    def __init__(self):\n        self.gap_mm = 1.0\n        self.gap = 1.0\nobj.depth_deg = 2\n'
    sites, _ = _keys(tmp_path, 'a.py', text, 'python_attribute')
    assert sites == {'a.py:3:gap_mm', 'a.py:5:depth_deg'}


def test_a_function_name_spelling_a_unit_is_counted(tmp_path: Path) -> None:
    text = 'def width_mm():\n    return 1.0\ndef width():\n    return 1.0\n'
    sites, _ = _keys(tmp_path, 'a.py', text, 'function_name')
    assert sites == {'a.py:1:width_mm'}


def test_the_excluded_si_letters_are_sized_on_the_declared_surface_only(tmp_path: Path) -> None:
    text = (
        'DEAD_TIME_S = 1e-6\n'
        'BUS_V = 400.0\n'
        'def f(depth_m, power_w, size_gb, mesh_kw, x):\n'
        '    local_s = 1.0\n'
        '    return local_s\n'
        'STEP = Q_(1.0, "s")\n'
    )
    sites, _ = _keys(tmp_path, 'a.py', text, 'si_letter')
    assert sites == {
        'a.py:1:DEAD_TIME_S',
        'a.py:2:BUS_V',
        'a.py:3:depth_m',
        'a.py:3:power_w',
        'a.py:3:size_gb',
        'a.py:3:mesh_kw',
    }


def test_a_string_key_a_source_writes_is_counted(tmp_path: Path) -> None:
    text = "row = {'speed_rpm': 1, 'name': 'x'}\nrow['torque_nm'] = 2.0\nvalue = row['speed_rpm']\n"
    sites, _ = _keys(tmp_path, 'a.py', text, 'output_key')
    assert sites == {'a.py:1:speed_rpm', 'a.py:2:torque_nm'}


_RUST = """use crate::geom;
// a comment naming gap_mm is not code
fn interior(gap_mm: f64) -> f64 {
    let label = "depth_mm";
    gap_mm * 2.0
}

#[pyfunction]
#[pyo3(signature = (min_angle_deg = 20.0))]
fn mesh(min_angle_deg: f64) -> f64 {
    let inner_mm = min_angle_deg;
    inner_mm
}

#[pymethods]
impl Mesher {
    fn refine(&self, size_mm: f64) -> f64 {
        size_mm
    }
}
"""


def test_a_rust_identifier_is_counted_and_the_pyo3_signature_is_exempt(tmp_path: Path) -> None:
    sites, exempt = _keys(tmp_path, 'a.rs', _RUST, 'rust_identifier')
    assert sites == {
        'a.rs:3:gap_mm',
        'a.rs:5:gap_mm',
        'a.rs:11:inner_mm',
        'a.rs:11:min_angle_deg',
        'a.rs:12:inner_mm',
        'a.rs:18:size_mm',
    }
    assert exempt == {'a.rs:9:min_angle_deg', 'a.rs:10:min_angle_deg', 'a.rs:17:size_mm'}


def test_a_unit_only_in_a_comment_is_counted(tmp_path: Path) -> None:
    text = (
        'FACE = 0.8  # mm\n'
        'KM = 0.2  # motor constant [N*m/A]\n'
        'DEPTH = 0.05  # [m]\n'
        'COUNT = 3  # how many slots\n'
        'LABEL = "x"  # mm\n'
        'GAP_MM = 1.0  # mm\n'
    )
    sites, _ = _keys(tmp_path, 'a.py', text, 'comment_unit')
    assert sites == {'a.py:1:FACE', 'a.py:3:DEPTH'}


def test_a_suffix_free_absolute_tolerance_is_counted_and_a_relative_one_is_not(tmp_path: Path) -> None:
    text = (
        'MESH_TOL = 1e-9\n'
        'REL_TOL = 1e-6\n'
        'assert_allclose(a, b, atol=1e-12, rtol=1e-9)\n'
        'isclose(a, b, abs_tol=0.0)\n'
        'assert_allclose(a, b, atol=scale * 1e-9)\n'
    )
    sites, exempt = _keys(tmp_path, 'a.py', text, 'absolute_tolerance')
    assert sites == {'a.py:1:MESH_TOL', 'a.py:3:atol', 'a.py:4:abs_tol'}
    assert not exempt, 'a declared non-unit is a SUFFIX ruling; a bare `atol=` keyword is not a variable named atol'


def test_a_bare_constant_name_with_a_comment_unit_is_not_swallowed_by_the_bare_exception(tmp_path: Path) -> None:
    sites, exempt = _keys(tmp_path, 'a.py', 'FACE = 0.8  # mm\nTOL = 1e-9\n', 'comment_unit')
    assert sites == {'a.py:1:FACE'}
    assert not exempt


@pytest.mark.parametrize(
    'name',
    ['TORQUE_BAR', 'psi_m', 'psi_s', 'temp_c', 'rated_a', 'top_n', 'age_h', 'v_min', 's'],
)
def test_every_declared_exception_is_not_counted_but_is_reported(tmp_path: Path, name: str) -> None:
    """THE CONTROL: each declared non-unit, planted where the SI-letter slice would count it, lands in ``exempt``."""
    text = f'{name} = 1.0\ndef f({name}):\n    return {name}\n'
    report = measure([_plant(tmp_path, 'a.py', text)], root=tmp_path)
    counted = {s.name for part in report.slices.values() for s in part.sites}
    reported = {s.name for part in report.slices.values() for s in part.exempt}
    assert name not in counted
    if name.lower().rsplit('_', 1)[-1] in unit_slices.SI_LETTERS:
        assert name in reported, f'{name} vanished instead of being reported as exempt'


def test_every_declared_exception_carries_a_reason_and_is_exercised() -> None:
    assert all(row.reason.strip() for row in DECLARED_EXCEPTIONS)
    kinds = {(row.kind, row.value) for row in DECLARED_EXCEPTIONS}
    assert kinds == {
        ('suffix', '_bar'),
        ('prefix', 'psi_'),
        ('segment', 'c'),
        ('segment', 'a'),
        ('segment', 'n'),
        ('segment', 'h'),
        ('segment', 'min'),
        ('bare', ''),
    }


def test_every_slice_is_always_present_and_files_are_floored(tmp_path: Path) -> None:
    report = measure(
        [_plant(tmp_path, 'a.py', 'X = 1\n'), _plant(tmp_path, 'b.md', 'x'), _plant(tmp_path, 'c.py', 'def (:\n')],
        root=tmp_path,
    )
    assert tuple(report.slices) == SLICES
    assert report.files_read == 1
    assert report.skipped == ('b.md',)
    assert report.unparsed == ('c.py',)


def test_the_report_cli_prints_counts_and_writes_sorted_named_sets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / 'tree'
    tree.mkdir()
    _plant(tree, 'a.py', _LOCAL)
    _plant(tree, 'b.rs', _RUST)
    monkeypatch.setattr(unit_slices, '_tracked', lambda root: sorted(root.iterdir()))
    out = tmp_path / 'out.json'
    assert unit_slices.main(['report', str(tree), '--out', str(out)]) == 0
    payload = json.loads(out.read_text(encoding='utf-8'))
    assert set(payload['slices']) == set(SLICES)
    for part in payload['slices'].values():
        order = [(path, int(line), name) for path, line, name in (key.split(':') for key in part['sites'])]
        assert order == sorted(order)
        assert part['count'] == len(part['sites'])
    assert payload['slices']['python_local']['sites'] == ['a.py:5:span_mm']
    printed = capsys.readouterr().out
    assert all(name in printed for name in SLICES)
