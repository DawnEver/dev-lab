"""TYPES-RATCHET: pyright's error counts per owner only fall, and a record never sits above a measurement."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from dev_lab.dev import typecheck
from dev_lab.dev.ownerdag import PythonTree

TREE = PythonTree('pkg', 'src/pkg', 'pkg_native')


@pytest.mark.parametrize(
    ('rel', 'expected'),
    [
        ('src/pkg/alpha/x.py', 'alpha'),
        ('src/pkg/alpha/deep/y.py', 'alpha'),
        ('src/pkg/__init__.py', 'pkg'),
        ('tests/unit/test_a.py', 'tests'),
        ('scripts/tool.py', 'scripts'),
    ],
)
def test_each_file_counts_against_its_owner(rel: str, expected: str) -> None:
    assert typecheck.owner(TREE, rel) == expected


def test_counts_read_errors_only_per_owner(tmp_path: Path) -> None:
    report = {
        'generalDiagnostics': [
            {'file': str(tmp_path / 'src/pkg/alpha/x.py'), 'severity': 'error'},
            {'file': str(tmp_path / 'src/pkg/alpha/y.py'), 'severity': 'error'},
            {'file': str(tmp_path / 'tests/test_a.py'), 'severity': 'error'},
            {'file': str(tmp_path / 'tests/test_a.py'), 'severity': 'warning'},
        ]
    }
    assert typecheck.counts(report, tmp_path, TREE) == {'alpha': 2, 'tests': 1}


def test_the_ratchet_is_two_sided() -> None:
    """PLANTED CONTROL: equal passes; a rise, a floor left above, a new owner and a stale one each refuse."""
    assert typecheck.problems({'alpha': 3}, {'alpha': 3}) == []
    assert 'a regression of 1' in typecheck.problems({'alpha': 4}, {'alpha': 3})[0]
    assert 'lower the record to 2' in typecheck.problems({'alpha': 2}, {'alpha': 3})[0]
    assert 'records no beta' in typecheck.problems({'alpha': 3, 'beta': 1}, {'alpha': 3})[0]
    assert '(delete the entry)' in typecheck.problems({}, {'alpha': 3})[0]


def _repo(root: Path, errors: str) -> None:
    (root / 'src/pkg/alpha').mkdir(parents=True)
    (root / 'src/pkg/__init__.py').write_text('', encoding='utf-8')
    (root / 'src/pkg/alpha/__init__.py').write_text('', encoding='utf-8')
    (root / 'src/pkg/alpha/bad.py').write_text('def f() -> int:\n    return "no"\n', encoding='utf-8')
    (root / 'pyproject.toml').write_text(
        '[project]\nname = "pkg"\n\n[tool.pyright]\ninclude = ["src"]\nstrict = ["src"]\ntypeCheckingMode = "basic"\n'
        f'\n[tool.dev_lab.typecheck]\nerrors = {errors}\n',
        encoding='utf-8',
    )


@pytest.mark.skipif(typecheck.binary() is None, reason='pyright is not installed in this environment')
def test_the_real_checker_reads_a_planted_error(tmp_path: Path) -> None:
    """THE PLANTED CONTROL through pyright itself: one error, recorded passes; unrecorded refuses; --write records."""
    _repo(tmp_path, '{ alpha = 1 }')
    out = io.StringIO()
    assert typecheck.check(tmp_path, handle=out) == typecheck.CLEAN, out.getvalue()
    _repo_text = (tmp_path / 'pyproject.toml').read_text(encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(_repo_text.replace('{ alpha = 1 }', '{}'), encoding='utf-8')
    out = io.StringIO()
    assert typecheck.check(tmp_path, handle=out) == typecheck.FOUND
    assert 'records no alpha' in out.getvalue()
    assert typecheck.check(tmp_path, handle=io.StringIO(), write=True) == typecheck.CLEAN
    assert 'alpha = 1' in (tmp_path / 'pyproject.toml').read_text(encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(_repo_text.replace('{ alpha = 1 }', '{ alpha = 0 }'), encoding='utf-8')
    out = io.StringIO()
    assert typecheck.check(tmp_path, handle=out, write=True) == typecheck.FOUND
    assert 'never raises' in out.getvalue()


def test_a_repo_without_the_base_is_not_judged_and_says_so(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "pkg"\n', encoding='utf-8')
    out = io.StringIO()
    assert typecheck.check(tmp_path, handle=out) == typecheck.CLEAN
    assert 'not judged' in out.getvalue()
