"""The controls for :mod:`dev_lab.dev.famtests.treechecks` -- D42's adopted rows, planted both ways.

Each row is driven through a REAL pytest session over a REAL declared git checkout, so "every family repo
runs it" is measured at the plugin, not claimed at the module.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab import pytest_family
from dev_lab.dev.agent_wiring import RULES_REL
from dev_lab.dev.famtests import alwayson, treechecks
from dev_lab.dev.rules import RULES

pytest_plugins = ['pytester']

_GIT = shutil.which('git') or 'git'
_MANIFEST = '[tool.lab_commons.tests]\nresources = []\n'
_TEST = 'def test_x():\n    pass\n'
_SKIP = (
    'import sys\nimport pytest\n\n@pytest.mark.skipif(sys.platform != "win32", reason="w")\ndef test_y():\n    pass\n'
)
_NODE = 'import subprocess\n\ndef test_y():\n    subprocess.run(["node", "x.js"])\n'


def _checkout(root: Path, files: dict[str, str]) -> None:
    for name, text in {'pyproject.toml': _MANIFEST, **files}.items():  # a file may replace the manifest
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True, timeout=60)
    subprocess.run([_GIT, 'add', '--', '.'], cwd=root, check=True, timeout=60)


def _run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.RunResult:
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    return pytester.runpytest_subprocess('-p', pytest_family.__name__, 'tests', '-q', '-rA', timeout=300)


def _rules_json(reason: str) -> str:
    return json.dumps([{'name': 'R', 'pattern': 'x', 'matches': 'command', 'reason': reason}])


@pytest.mark.parametrize(
    ('row', 'files'),
    [
        ('platformskips', {'tests/test_y.py': _SKIP}),
        ('hostnode', {'tests/test_y.py': _NODE}),
        ('testleaks', {'tests/test_y.py': 'import tempfile\n\ndef test_y():\n    tempfile.mkdtemp()\n'}),
        ('restatedrules', {'AGENTS.md': f'# R\n\n{RULES[0].statement}\n'}),
        ('remedypaths', {RULES_REL: _rules_json('stop it: python -m dev_lab.dev.stoprun --pid 1')}),
    ],
)
def test_each_row_reds_its_planted_violation(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, row: str, files: dict[str, str]
) -> None:
    _checkout(pytester.path, {'tests/test_x.py': _TEST, **files})
    result = _run(pytester, monkeypatch)
    result.stdout.fnmatch_lines([f'FAILED ::family::{row}*'])
    assert result.stdout.str().count('FAILED') == 1, 'only the planted row reds'


def test_a_clean_checkout_runs_every_row_green(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    _checkout(
        pytester.path,
        {
            'tests/test_x.py': _TEST,
            'AGENTS.md': '# R\n\n- `XFAIL-NOT-SKIP`: earned here by a local incident.\n',
            RULES_REL: _rules_json('stop it: {python} -m dev_lab.dev.stoprun --pid 1'),
        },
    )
    result = _run(pytester, monkeypatch)
    for row in treechecks.TREE_CHECKS:
        result.stdout.fnmatch_lines([f'PASSED ::family::{row}*'])
    result.assert_outcomes(passed=1 + len(alwayson.rows()) + len(treechecks.TREE_CHECKS))


def test_a_row_runs_only_where_its_population_exists(tmp_path: Path) -> None:
    assert treechecks.applicable(tmp_path) == {}
    _checkout(tmp_path, {'tests/test_x.py': _TEST})
    assert set(treechecks.applicable(tmp_path)) == {'platformskips', 'hostnode', 'testleaks'}


def test_the_declared_ledger_admits_a_finding_and_refuses_a_stale_key(tmp_path: Path) -> None:
    ledger = '[tool.dev_lab.platformskips]\ndeclared = ["tests/test_y.py"]\n'
    _checkout(tmp_path, {'pyproject.toml': _MANIFEST + ledger, 'tests/test_y.py': _SKIP})
    treechecks.judge(tmp_path, 'platformskips')
    (tmp_path / 'tests' / 'test_y.py').write_text(_TEST, encoding='utf-8')
    with pytest.raises(AssertionError, match='no longer found'):
        treechecks.judge(tmp_path, 'platformskips')


def test_an_empty_population_is_refused_not_clean(tmp_path: Path) -> None:
    _checkout(tmp_path, {'tests/data.txt': 'x\n'})
    (tmp_path / 'tests' / 'untracked.py').write_text(_TEST, encoding='utf-8')
    with pytest.raises(AssertionError, match='EMPTY'):
        treechecks.judge(tmp_path, 'hostnode')


def test_a_tests_tree_without_python_has_no_python_rows(tmp_path: Path) -> None:
    _checkout(tmp_path, {'tests/probe.test.js': 'x\n'})
    assert treechecks.applicable(tmp_path) == {}


def test_an_undeclared_checkout_gets_no_tree_row(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    pytester.makepyfile(**{'tests/test_y': _SKIP})
    subprocess.run([_GIT, 'init', '-q'], cwd=pytester.path, check=True, timeout=60)
    subprocess.run([_GIT, 'add', '--', '.'], cwd=pytester.path, check=True, timeout=60)
    result = _run(pytester, monkeypatch)
    assert 'platformskips' not in result.stdout.str()
