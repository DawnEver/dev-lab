"""OWNER-COVERAGE: each owner ``dependencies.toml`` declares holds its line and branch coverage bar, and a ratchet.

Every refusal below is a PLANTED CONTROL beside the case that passes: the instrument is shown able to say no.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from dev_lab.dev import ownercov
from dev_lab.dev.covreports import PYTHON_TOOL, RUST_TOOL, Counts, Measurement

_FIXTURES = Path(__file__).resolve().parent / '_coverage_fixtures'

DECLARED = '[python.owners]\nalpha = []\nbeta = ["alpha"]\n\n[rust.crates]\ncore_a = []\ncore_b = ["core_a"]\n'
TREE = {
    'src/pkg/__init__.py': '',
    'src/pkg/alpha/__init__.py': '',
    'src/pkg/beta/__init__.py': '',
    'crates/core_a/Cargo.toml': '[package]\nname = "core_a"\n',
    'crates/core_a/src/lib.rs': '',
    'crates/core_b/Cargo.toml': '[package]\nname = "core-b"\n',
    'crates/core_b/src/lib.rs': '',
}
#: Every line and branch hit: above every bar.
FULL = Counts(lines=100, lines_hit=100, branches=10, branches_hit=10)
#: 97 % of lines, 92 % of branches: above the family bars, so a floor is recorded at exactly these.
GOOD = Counts(lines=1000, lines_hit=970, branches=100, branches_hit=92)


def _repo(tmp_path: Path, coverage: str = '', declared: str = DECLARED) -> tuple[Path, list[str]]:
    (tmp_path / 'pyproject.toml').write_text(f'[project]\nname = "pkg"\n{coverage}', encoding='utf-8')
    (tmp_path / 'dependencies.toml').write_text(declared, encoding='utf-8')
    for rel, text in TREE.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding='utf-8')
    return tmp_path, [*TREE, 'pyproject.toml', 'dependencies.toml']


def _py(files: dict[str, Counts], *, branch: bool = True) -> Measurement:
    """coverage.py's measurement of ``src/pkg/<key>.py`` for each key."""
    return Measurement(PYTHON_TOOL, 'py.json', branch=branch, files={f'src/pkg/{k}.py': v for k, v in files.items()})


def _rs(crates: dict[str, Counts]) -> Measurement:
    return Measurement(
        RUST_TOOL, 'rs.json', branch=True, files={f'crates/{k}/src/lib.rs': v for k, v in crates.items()}
    )


def _both(py: dict[str, Counts] | None = None, rs: dict[str, Counts] | None = None) -> dict[str, Measurement]:
    return {
        'python': _py(py or {'alpha/m': FULL, 'beta/m': FULL}),
        'rust': _rs(rs or {'core_a': FULL, 'core_b': FULL}),
    }


def _floors(root: Path) -> dict:
    return tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['dev_lab']['coverage']['floors']


def test_an_undeclared_repo_is_not_judged(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "pkg"\n', encoding='utf-8')
    assert ownercov.problems(tmp_path, [], **_both()) is None


def test_every_owner_at_or_above_its_bar_passes(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    assert ownercov.problems(root, files, **_both()) == []


def test_the_family_bars_are_quantities_with_units() -> None:
    assert ownercov.BARS == {'line': '95 %', 'branch': '90 %'}


def test_an_owner_below_the_bar_reds_naming_the_owner_the_measured_value_and_the_bar(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    low = Counts(lines=1000, lines_hit=949, branches=10, branches_hit=10)  # 94.9 %: one line short of passing
    found = ownercov.problems(root, files, **_both(py={'alpha/m': FULL, 'beta/m': low}))
    assert found == ['[python.owners] beta: line coverage 94.90 % is below the bar 95.00 % -- cover it']


def test_an_owner_below_its_floor_reds_naming_the_owner_the_measured_value_and_the_floor(tmp_path: Path) -> None:
    coverage = '[tool.dev_lab.coverage.floors.rust]\ncore_b = { line = "98.50 %" }\n'
    root, files = _repo(tmp_path, coverage)
    found = ownercov.problems(root, files, **_both(rs={'core_a': FULL, 'core_b': GOOD}))
    assert len(found) == 1
    assert found[0].startswith('[rust.crates] core_b: line coverage 97.00 % is below its floor 98.50 %')
    assert 'record' in found[0]  # the door: floors are written only by `record`


def test_a_measured_gain_past_the_bar_is_recorded_as_the_new_floor(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    assert ownercov.record(root, files, **_both(py={'alpha/m': GOOD, 'beta/m': FULL})) == []
    floors = _floors(root)
    assert floors['python']['alpha'] == {'line': '97.00 %', 'branch': '92.00 %'}
    assert floors['python']['beta'] == {'line': '100.00 %', 'branch': '100.00 %'}
    # and a gain past that floor raises it again
    better = Counts(lines=1000, lines_hit=981, branches=100, branches_hit=92)
    assert ownercov.record(root, files, **_both(py={'alpha/m': better, 'beta/m': FULL})) == []
    assert _floors(root)['python']['alpha'] == {'line': '98.10 %', 'branch': '92.00 %'}


def test_a_recorded_floor_is_truncated_so_the_same_measurement_meets_it_again(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    third = Counts(lines=3, lines_hit=3, branches=30, branches_hit=29)  # 96.666... %
    assert ownercov.record(root, files, **_both(py={'alpha/m': third, 'beta/m': FULL})) == []
    assert _floors(root)['python']['alpha']['branch'] == '96.66 %'
    assert ownercov.problems(root, files, **_both(py={'alpha/m': third, 'beta/m': FULL})) == []


def test_the_floor_never_moves_down(tmp_path: Path) -> None:
    coverage = '[tool.dev_lab.coverage.floors.python]\nalpha = { line = "99.00 %" }\n'
    root, files = _repo(tmp_path, coverage)
    found = ownercov.record(root, files, **_both(py={'alpha/m': GOOD, 'beta/m': FULL}))
    assert any('alpha: line coverage 97.00 % is below its floor 99.00 %' in one for one in found)
    assert _floors(root)['python']['alpha']['line'] == '99.00 %'  # kept, never lowered to the measurement


def test_a_floor_edited_above_the_measured_value_is_refused(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    measured = _both(py={'alpha/m': GOOD, 'beta/m': FULL})
    assert ownercov.record(root, files, **measured) == []
    path = root / 'pyproject.toml'
    path.write_text(path.read_text(encoding='utf-8').replace('97.00 %', '99.50 %'), encoding='utf-8')  # a hand raise
    before = path.read_bytes()
    found = ownercov.problems(root, files, **measured)
    assert found == [
        (
            '[python.owners] alpha: line coverage 97.00 % is below its floor 99.50 % -- restore the tests that covered '
            'it; a floor is only ever a measurement `record` wrote, so a floor edited past one is restored, not met'
        )
    ]
    assert ownercov.record(root, files, **measured) == found  # record refuses it too, and accepts nothing
    assert path.read_bytes() == before


def test_a_floor_naming_no_declared_owner_reds(tmp_path: Path) -> None:
    root, files = _repo(tmp_path, '[tool.dev_lab.coverage.floors.python]\ngone = { line = "99.00 %" }\n')
    found = ownercov.problems(root, files, **_both())
    assert found == [
        (
            'pyproject.toml [tool.dev_lab.coverage.floors.python] gone: a floor for an owner no [python.owners] row of '
            'dependencies.toml declares -- move it with the owner when it was renamed, else delete it'
        )
    ]


def test_a_declared_owner_with_no_measurement_reds(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    found = ownercov.problems(root, files, python=_py({'alpha/m': FULL}), rust=_rs({'core_a': FULL, 'core_b': FULL}))
    assert found == [
        (
            '[python.owners] beta: no line was measured in src/pkg/beta -- is it under [tool.coverage.run] source, '
            'and does a test reach it?'
        )
    ]


def test_a_crate_with_no_measurement_reds(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    found = ownercov.problems(root, files, python=_py({'alpha/m': FULL, 'beta/m': FULL}), rust=_rs({'core_a': FULL}))
    assert found == ['[rust.crates] core_b: no line was measured in crates/core_b -- does `cargo llvm-cov` build it?']


def test_a_measurement_with_no_owner_reds(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    python = _py({'alpha/m': FULL, 'beta/m': FULL, '__main__': Counts(1, 0)})
    python.files['tests/test_x.py'] = Counts(3, 3)  # type: ignore[index] -- a plain dict built by _py
    found = ownercov.problems(root, files, python=python, rust=_rs({'core_a': FULL, 'core_b': FULL}))
    assert found == [
        f'{PYTHON_TOOL} measured src/pkg/__main__.py, which lies in no owner dependencies.toml declares',
        f'{PYTHON_TOOL} measured tests/test_x.py, which lies in no owner dependencies.toml declares',
    ]


def test_a_file_with_no_line_needs_no_owner(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    python = _py({'alpha/m': FULL, 'beta/m': FULL, '__init__': Counts()})
    assert ownercov.problems(root, files, python=python, rust=_rs({'core_a': FULL, 'core_b': FULL})) == []


def test_a_declared_language_with_no_report_reds_and_a_report_with_no_owner_table_reds(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    assert ownercov.problems(root, files, python=_py({'alpha/m': FULL, 'beta/m': FULL})) == [
        f'[rust.crates] is declared but no {RUST_TOOL} report was given -- --rust <report>'
    ]
    root, files = _repo(tmp_path, declared='[python.owners]\nalpha = []\nbeta = []\n')
    found = ownercov.problems(root, files, **_both())
    assert found == [
        f'a {RUST_TOOL} report was given but dependencies.toml declares no [rust.crates] row to own what it measured'
    ]


def test_a_report_that_measured_no_branch_reds(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    python = _py({'alpha/m': FULL, 'beta/m': FULL}, branch=False)
    found = ownercov.problems(root, files, python=python, rust=_rs({'core_a': FULL, 'core_b': FULL}))
    assert found == [
        (
            f'{PYTHON_TOOL} report py.json measured no branch, so the branch bar cannot be judged -- '
            'set [tool.coverage.run] branch = true'
        )
    ]


def test_an_owner_with_no_branch_to_take_misses_none(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    straight = Counts(lines=10, lines_hit=10)
    assert ownercov.problems(root, files, **_both(py={'alpha/m': straight, 'beta/m': FULL})) == []


def test_an_owner_is_judged_on_its_summed_counts_never_an_average_of_file_percentages(tmp_path: Path) -> None:
    root, files = _repo(tmp_path)
    # 1 of 1 and 90 of 100 average to 95 % but sum to 91 of 101 = 90.09 %
    python = _py({'alpha/a': Counts(1, 1, 1, 1), 'alpha/b': Counts(100, 90, 1, 1), 'beta/m': FULL})
    found = ownercov.problems(root, files, python=python, rust=_rs({'core_a': FULL, 'core_b': FULL}))
    assert found == ['[python.owners] alpha: line coverage 90.09 % is below the bar 95.00 % -- cover it']


def test_a_repo_may_raise_a_bar(tmp_path: Path) -> None:
    root, files = _repo(tmp_path, '[tool.dev_lab.coverage]\nline = "98 %"\n')
    found = ownercov.problems(root, files, **_both(py={'alpha/m': GOOD, 'beta/m': FULL}))
    assert found == ['[python.owners] alpha: line coverage 97.00 % is below the bar 98.00 % -- cover it']


@pytest.mark.parametrize(
    ('coverage', 'why'),
    [
        ('line = "90 %"', 'line = "90 %" lowers the family bar 95 %: a repo may only raise it (BAR-IS-A-CONSTANT)'),
        ('branch = "90 %"', 'branch = "90 %" restates the family bar 90 %: delete it, the family bar holds'),
        ('line = 96', 'line = 96 is a bare number: write it with its unit, such as "96 %"'),
        ('line = "0.96"', 'line = "0.96" carries no unit: write it with its unit, such as "96 %"'),
        ('line = "101 %"', 'line = "101 %" is not a share between 0 % and 100 %'),
        ('lines = "96 %"', "unknown key(s) ['lines']"),
        ('[tool.dev_lab.coverage.floors.go]\nx = { line = "99 %" }', "unknown language(s) ['go']"),
        ('[tool.dev_lab.coverage.floors.python]\nalpha = { line = 99 }', 'alpha line = 99 is a bare number'),
        ('[tool.dev_lab.coverage.floors.python]\nalpha = {}', 'alpha holds no floor'),
    ],
)
def test_a_malformed_declaration_is_refused_by_name(tmp_path: Path, coverage: str, why: str) -> None:
    table = coverage if coverage.startswith('[') else f'[tool.dev_lab.coverage]\n{coverage}'
    root, files = _repo(tmp_path, f'{table}\n')
    found = ownercov.problems(root, files, **_both())
    assert len(found) == 1
    assert why in found[0]
    assert found[0].startswith('pyproject.toml [tool.dev_lab.coverage')


def test_a_floor_at_or_below_the_bar_is_a_second_copy_of_the_bar_and_record_deletes_it(tmp_path: Path) -> None:
    root, files = _repo(tmp_path, '[tool.dev_lab.coverage.floors.python]\nalpha = { line = "95 %" }\n')
    found = ownercov.problems(root, files, **_both())
    assert found == [
        (
            'pyproject.toml [tool.dev_lab.coverage.floors.python] alpha line = "95 %" is not above the bar 95.00 %: '
            'a floor exists only above the bar -- `record` deletes it'
        )
    ]
    assert ownercov.record(root, files, **_both()) == []
    assert _floors(root)['python']['alpha'] == {'line': '100.00 %', 'branch': '100.00 %'}


def test_record_writes_nothing_while_the_declaration_is_malformed(tmp_path: Path) -> None:
    root, files = _repo(tmp_path, '[tool.dev_lab.coverage]\nline = "90 %"\n')
    before = (root / 'pyproject.toml').read_bytes()
    assert ownercov.record(root, files, **_both())
    assert (root / 'pyproject.toml').read_bytes() == before


def test_the_cli_judges_the_recorded_report_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, _ = _repo(tmp_path, declared='[python.owners]\nalpha = []\nbeta = ["alpha"]\n')
    for argv in (['init', '-q'], ['add', '-A']):
        subprocess.run(['git', *argv], cwd=root, check=True)  # noqa: S607 -- the CLI reads the tracked tree
    report = str(_FIXTURES / 'coverage_py.json')
    assert ownercov.main(['check', '--python', report], cwd=root) == 1
    out = capsys.readouterr().out
    assert 'src/pkg/__main__.py, which lies in no owner' in out  # one statement at the package root
    assert '[python.owners] beta: line coverage 75.00 % is below the bar 95.00 %' in out
    assert '[python.owners] beta: branch coverage 50.00 % is below the bar 90.00 %' in out
    assert '[python.owners] alpha' not in out  # 6 of 6 lines, 2 of 2 branches
    assert ownercov.main(['record', '--python', report], cwd=root) == 1
    assert _floors(root) == {'python': {'alpha': {'line': '100.00 %', 'branch': '100.00 %'}}}
