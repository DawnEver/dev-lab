"""A coverage tool's JSON report read into per-file counts: coverage.py's and ``cargo llvm-cov``'s.

``_coverage_fixtures/coverage_py.json`` is a RECORDING: coverage.py 7.17.4, ``--branch``, run on a three-module
sample package (re-indented, nothing else changed). ``_coverage_fixtures/llvm_cov_schema.json`` is NOT a recording:
``cargo llvm-cov`` is not installed on the box this was written on, so it is written to the documented
``llvm.coverage.json.export`` 2.0.1 shape that ``cargo llvm-cov --json --summary-only`` prints, with ``@ROOT@``
standing for the workspace root. Replace it with a recording once the tool is installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import covreports
from dev_lab.dev.covreports import Counts, ReportRefused

_FIXTURES = Path(__file__).resolve().parent / '_coverage_fixtures'


def _llvm(tmp_path: Path, mutate=None) -> Path:
    data = json.loads(
        (_FIXTURES / 'llvm_cov_schema.json').read_text(encoding='utf-8').replace('@ROOT@', tmp_path.as_posix())
    )
    if mutate is not None:
        mutate(data)
    report = tmp_path / 'llvm.json'
    report.write_text(json.dumps(data), encoding='utf-8')
    return report


def test_the_recorded_coverage_py_report_reads_per_file_counts() -> None:
    found = covreports.python_report(Path('/repo'), _FIXTURES / 'coverage_py.json')
    assert found.tool == covreports.PYTHON_TOOL
    assert found.branch
    assert found.files['src/pkg/beta/half.py'] == Counts(lines=4, lines_hit=3, branches=2, branches_hit=1)
    assert found.files['src/pkg/alpha/core.py'] == Counts(lines=6, lines_hit=6, branches=2, branches_hit=2)
    assert found.files['src/pkg/__init__.py'] == Counts()  # a file with no statement is still READ, as zero
    assert len(found.files) == 6


def test_a_coverage_py_report_without_branches_says_so(tmp_path: Path) -> None:
    data = json.loads((_FIXTURES / 'coverage_py.json').read_text(encoding='utf-8'))
    data['meta']['branch_coverage'] = False
    report = tmp_path / 'c.json'
    report.write_text(json.dumps(data), encoding='utf-8')
    assert not covreports.python_report(tmp_path, report).branch


def test_an_absolute_path_reads_relative_to_the_root_and_one_outside_stays_absolute(tmp_path: Path) -> None:
    inside, outside = (tmp_path / 'src' / 'pkg' / 'a.py').as_posix(), (tmp_path.parent / 'x.py').as_posix()
    summary = {'num_statements': 1, 'covered_lines': 1, 'num_branches': 0, 'covered_branches': 0}
    data = {'meta': {'branch_coverage': True}, 'files': {inside: {'summary': summary}, outside: {'summary': summary}}}
    report = tmp_path / 'c.json'
    report.write_text(json.dumps(data), encoding='utf-8')
    assert set(covreports.python_report(tmp_path, report).files) == {'src/pkg/a.py', outside}


def test_the_llvm_cov_report_reads_per_file_counts(tmp_path: Path) -> None:
    found = covreports.rust_report(tmp_path, _llvm(tmp_path))
    assert found.tool == covreports.RUST_TOOL
    assert found.branch
    assert found.files == {
        'crates/core_a/src/lib.rs': Counts(lines=100, lines_hit=98, branches=20, branches_hit=19),
        'crates/core_b/src/lib.rs': Counts(lines=50, lines_hit=45, branches=10, branches_hit=8),
    }


def test_an_llvm_cov_report_with_no_branch_counted_was_not_run_with_branches(tmp_path: Path) -> None:
    def no_branches(data: dict) -> None:
        for one in data['data'][0]['files']:
            one['summary']['branches'] = {'count': 0, 'covered': 0, 'notcovered': 0, 'percent': 0.0}

    assert not covreports.rust_report(tmp_path, _llvm(tmp_path, no_branches)).branch


def test_a_file_stated_twice_is_refused_never_summed_or_overwritten(tmp_path: Path) -> None:
    def twice(data: dict) -> None:
        data['data'].append({'files': [data['data'][0]['files'][0]]})

    with pytest.raises(ReportRefused, match=r'crates/core_a/src/lib\.rs.*twice'):
        covreports.rust_report(tmp_path, _llvm(tmp_path, twice))


@pytest.mark.parametrize(
    ('reader', 'text', 'why'),
    [
        (covreports.python_report, 'not json', 'is not JSON'),
        (covreports.python_report, '{"files": {}}', 'no meta.branch_coverage'),
        (covreports.python_report, '{"meta": {"branch_coverage": true}, "files": {"a.py": {}}}', 'a.py'),
        (covreports.rust_report, '{"type": "other", "data": []}', 'llvm.coverage.json.export'),
        (covreports.rust_report, '{"type": "llvm.coverage.json.export", "data": [{"files": [{}]}]}', 'filename'),
    ],
)
def test_a_report_of_the_wrong_shape_is_refused_naming_the_command_that_writes_it(
    tmp_path: Path,
    reader,
    text: str,
    why: str,
) -> None:
    report = tmp_path / 'r.json'
    report.write_text(text, encoding='utf-8')
    with pytest.raises(ReportRefused) as caught:
        reader(tmp_path, report)
    assert why in str(caught.value)
    assert str(report) in str(caught.value)
    assert ('coverage json' if reader is covreports.python_report else 'cargo llvm-cov') in str(caught.value)


def test_a_missing_report_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ReportRefused, match='no report'):
        covreports.python_report(tmp_path, tmp_path / 'absent.json')
