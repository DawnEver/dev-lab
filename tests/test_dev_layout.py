"""DECLARED-LAYOUT: every top-level directory is declared, and a declared one may forbid suffixes beneath it.

User requirement 2026-11-23. Each check carries its planted control: an undeclared directory and a forbidden
suffix are planted and must be named; a declared directory, an allowed suffix and a pruned tree must not be; an
empty root must red on the floor; and the write hook must refuse exactly what the scan refuses.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dev_lab.dev import codeplace, floors
from dev_lab.dev.codeplace import main
from dev_lab.dev.famtests.layout import assert_layout_holds
from dev_lab.dev.layout import FAMILY_LAYOUT, LayoutNotDeclared, declared_layout, layout_violations, refuse_layout

_TABLE = """[tool.dev_lab.placement]
pruned_paths = ['.claude/worktrees']
[tool.dev_lab.placement.layout]
rust = []
cases = ['.rs']
"""


def _checkout(root: Path, body: str = _TABLE) -> Path:
    (root / '.git').mkdir(parents=True)
    (root / 'pyproject.toml').write_text(body, encoding='utf-8')
    for top in ('src', 'rust', 'cases', 'output/logs/26/11/23/run'):
        (root / top).mkdir(parents=True)
    return root


def _plant(root: Path, rel: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text('x', encoding='utf-8')


def test_the_family_homes_are_declared_and_output_forbids_its_code() -> None:
    assert {'src', 'tests', 'scripts', 'scratch', '.claude', 'docs-src', 'output'} == set(FAMILY_LAYOUT)
    assert {'.py', '.rs', '.toml'} <= FAMILY_LAYOUT['output']
    assert not FAMILY_LAYOUT['src']


def test_a_clean_tree_reads_no_violation(tmp_path) -> None:
    root = _checkout(tmp_path)
    _plant(root, 'output/logs/26/11/23/run/data.csv')
    _plant(root, 'cases/ipm/case.toml')
    _plant(root, 'src/pkg/x.py')
    assert layout_violations(root)[1] == []


@pytest.mark.parametrize(
    ('rel', 'named'),
    [
        ('output/logs/26/11/23/run/probe.py', 'output/logs/26/11/23/run/probe.py: .py is forbidden under output/'),
        ('output/x/config.toml', 'output/x/config.toml: .toml is forbidden under output/'),
        ('cases/ipm/lib.rs', 'cases/ipm/lib.rs: .rs is forbidden under cases/'),
        ('tmp/a.txt', 'tmp/: tmp/ is not a declared top-level directory'),
    ],
)
def test_a_planted_violation_is_NAMED(tmp_path, rel, named) -> None:
    root = _checkout(tmp_path)
    _plant(root, rel)
    found = layout_violations(root)[1]
    assert len(found) == 1
    assert found[0].startswith(named)


def test_pruned_trees_and_tool_state_are_not_judged(tmp_path) -> None:
    root = _checkout(tmp_path)
    _plant(root, '.claude/worktrees/lane/output/x.py')
    _plant(root, '.venv/Lib/site.py')
    _plant(root, 'output/.pytest_cache/x.py')
    assert layout_violations(root)[1] == []


def test_a_repo_row_adds_to_the_family_forbidden_set(tmp_path) -> None:
    root = _checkout(tmp_path, _TABLE + "output = ['.md']\n")
    assert {'.md', '.py'} <= declared_layout(root).dirs['output']


@pytest.mark.parametrize(
    'body',
    [
        '[tool.dev_lab.placement]\n',
        "[tool.dev_lab.placement.layout]\nsrc = 'x'\n",
        "[tool.dev_lab.placement.layout]\nsrc = ['py']\n",
        "[tool.dev_lab.placement.layout]\n'a/b' = []\n",
    ],
)
def test_an_absent_or_malformed_table_is_REFUSED(tmp_path, body) -> None:
    root = _checkout(tmp_path, body)
    with pytest.raises(LayoutNotDeclared):
        declared_layout(root)


def test_the_famtest_floor_refuses_a_walk_that_read_nothing(tmp_path) -> None:
    root = tmp_path / 'empty'
    root.mkdir()
    (root / 'pyproject.toml').write_text(_TABLE, encoding='utf-8')
    with pytest.raises(floors.FloorUnmet):
        assert_layout_holds(root=root, floor=3, headroom=5)


def test_the_famtest_names_every_violation_and_passes_a_clean_tree(tmp_path) -> None:
    root = _checkout(tmp_path)
    assert_layout_holds(root=root, floor=4, headroom=5)
    _plant(root, 'output/logs/p.py')
    _plant(root, 'vendor-dump/x.log')
    with pytest.raises(AssertionError, match=r'(?s)output/logs/p\.py.*vendor-dump/'):
        assert_layout_holds(root=root, floor=4, headroom=5)


@pytest.mark.parametrize(
    ('rel', 'refused'),
    [
        ('output/logs/26/11/23/run/probe.py', True),
        ('cases/ipm/lib.rs', True),
        ('tmp/probe.txt', True),
        ('output/logs/26/11/23/run/data.csv', False),
        ('src/pkg/x.py', False),
        ('README.md', False),
        ('.claude/worktrees/lane/tmp/x.py', False),
    ],
)
def test_the_write_hook_refuses_exactly_what_the_scan_refuses(tmp_path, rel, refused) -> None:
    root = _checkout(tmp_path)
    reason = refuse_layout(root / rel)
    assert (reason is not None) is refused
    if refused:
        assert reason.startswith('DECLARED-LAYOUT: ')
        assert '[tool.dev_lab.placement.layout]' in reason
        assert 'details: ' in reason


def test_a_checkout_without_a_layout_table_is_not_judged_by_the_hook(tmp_path) -> None:
    root = _checkout(tmp_path, '[tool.dev_lab.placement]\n')
    assert refuse_layout(root / 'tmp' / 'x.txt') is None


def test_the_hook_entry_denies_a_write_into_an_undeclared_directory(tmp_path, capsys, monkeypatch) -> None:
    # tmp_path lies under the OS temp dir, which WRITES-STAY-IN-THE-TREE refuses first; this test is about the layout.
    monkeypatch.setattr(codeplace, 'refuse_outside_tree', lambda _path: None)
    root = _checkout(tmp_path)
    bad = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(root / 'tmp' / 'x.txt')}})
    assert main(stdin=io.StringIO(bad)) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert decision['permissionDecision'] == 'deny'
    assert 'DECLARED-LAYOUT' in decision['permissionDecisionReason']
