"""DECLARED-LAYOUT and NO-BACKUP-COPIES: the whole tree is an allow-list, and output/ and scratch/ hold no copy.

User rulings 2026-11-23. Every check carries its planted control: each refused shape (an undeclared directory, a
format a row does not allow, a clone, a worktree, an exported tree, a bundle, a patch, a write into a read-only
input) is planted and must be NAMED; each admitted shape must not be; an empty root reds on the floor; the
incremental scan must see a file planted after a clean journalled scan; and the write hook refuses exactly what
the scan refuses.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from dev_lab.dev import codeplace, floors, layout
from dev_lab.dev.codeplace import main
from dev_lab.dev.famtests.layout import assert_layout_holds
from dev_lab.dev.layout import LayoutNotDeclared, declared_layout, layout_violations, refuse_layout, scan_refusal

_HOMES = """'.' = ['.toml', '.md']
src = ['.py']
tests = ['.py']
scripts = ['.py']
scratch = ['*']
'.claude' = ['.json']
'.claude/memory' = ['.md']
'docs-src' = ['.md']
output = []
'output/logs' = []
'output/logs/[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*' = ['.csv', '.json']
"""
_TABLE = f"""[tool.dev_lab.placement]
pruned_paths = ['.claude/worktrees']
read_only = ['temp']
[tool.dev_lab.placement.layout]
{_HOMES}rust = ['.rs', '.toml']
'rust/crates/*/tests/goldens' = ['.bundle']
temp = ['*']
"""


def _checkout(root: Path, body: str = _TABLE) -> Path:
    (root / '.git').mkdir(parents=True)
    (root / 'pyproject.toml').write_text(body, encoding='utf-8')
    for top in ('src', 'rust', 'output/logs/26/11/23/run'):
        (root / top).mkdir(parents=True)
    return root


def _plant(root: Path, rel: str) -> Path:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text('x', encoding='utf-8')
    return root / rel


def test_the_family_homes_are_required() -> None:
    assert {'src', 'tests', 'scripts', 'scratch', '.claude', 'docs-src', 'output'} == layout.REQUIRED


def test_a_clean_tree_reads_no_violation(tmp_path) -> None:
    root = _checkout(tmp_path)
    for rel in (
        'output/logs/26/11/23/run/data.csv',
        'output/logs/26/11/23/run/deep/er/r.json',
        'rust/crates/x/tests/goldens/g.bundle',
        'src/pkg/x.py',
        'README.md',
        'temp/anything.xlsx',
        'scratch/26/11/23/probe.py',
    ):
        _plant(root, rel)
    assert layout_violations(root)[1] == []


@pytest.mark.parametrize(
    ('rel', 'named'),
    [
        (
            'output/logs/26/11/23/run/probe.py',
            'output/logs/26/11/23/run/probe.py: .py is not allowed under output/logs/',
        ),
        ('output/logs/26/11/23/run/notes.md', 'output/logs/26/11/23/run/notes.md: .md is not allowed'),
        ('output/logs/legacy/a/b/c/x.csv', 'output/logs/legacy/a/b/c/x.csv: .csv is not allowed under output/logs '),
        ('output/stray.csv', 'output/stray.csv: .csv is not allowed under output '),
        ('rust/crates/x/src/x.bundle', 'rust/crates/x/src/x.bundle: .bundle is not allowed under rust '),
        ('tmp/a.txt', 'tmp/a.txt: tmp/ is not declared'),
        ('run.ps1', 'run.ps1: .ps1 is not allowed under .'),
        ('output/logs/26/11/23/lane/lane.bundle', 'output/logs/26/11/23/lane/lane.bundle: NO-BACKUP-COPIES'),
        ('scratch/uncommitted.patch', 'scratch/uncommitted.patch: NO-BACKUP-COPIES'),
        ('output/logs/26/11/23/wt/.git', 'output/logs/26/11/23/wt/: NO-BACKUP-COPIES: holds .git'),
        ('scratch/clone/.git/HEAD', 'scratch/clone/: NO-BACKUP-COPIES: holds .git'),
        ('src/pkg/.claude/memory/note.md', 'src/pkg/.claude/: a .claude/ below the repo root'),
        ('output/worktree-archive/x/src/a.py', 'output/worktree-archive/x/src/a.py: .py is not allowed'),
    ],
)
def test_a_planted_violation_is_NAMED(tmp_path, rel, named) -> None:
    root = _checkout(tmp_path)
    _plant(root, rel)
    found = layout_violations(root)[1]
    assert len(found) == 1, found
    assert found[0].startswith(named), found


def test_an_exported_tree_is_a_copy_and_is_not_descended(tmp_path) -> None:
    root = _checkout(tmp_path)
    for rel in ('pyproject.toml', 'src/a.py', 'src/b.py', 'tests/t.py'):
        _plant(root, f'output/logs/26/11/23/base_tree/{rel}')
    assert layout_violations(root)[1] == [
        (
            f'output/logs/26/11/23/base_tree/: NO-BACKUP-COPIES: holds pyproject.toml beside src/: an exported copy '
            f'of a tree. {layout.COPY_DOOR}'
        )
    ]


def test_many_files_of_one_cause_are_one_line(tmp_path) -> None:
    root = _checkout(tmp_path)
    for n in range(5):
        _plant(root, f'output/logs/26/11/23/run/p{n}.py')
    assert layout_violations(root)[1] == [
        (
            'output/logs/26/11/23/run/ (5 files, e.g. p0.py): .py is not allowed under '
            "output/logs/[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/* (allowed: ['.csv', '.json'])"
        )
    ]


def test_pruned_trees_and_tool_state_are_not_judged(tmp_path) -> None:
    root = _checkout(tmp_path)
    _plant(root, '.claude/worktrees/lane/output/x.py')
    _plant(root, '.venv/Lib/site.py')
    _plant(root, 'output/.pytest_cache/x.py')
    assert layout_violations(root)[1] == []


def test_the_incremental_scan_sees_a_file_planted_after_a_clean_scan(tmp_path) -> None:
    root = _checkout(tmp_path)
    assert layout_violations(root, incremental=True)[1] == []
    journal = root / '.git' / 'dev-lab' / 'layout-scan.json'
    assert journal.is_file(), 'PLANTED CONTROL: the clean scan journalled its directories'
    planted = _plant(root, 'output/logs/26/11/23/run/probe.py')
    folder = planted.parent
    os.utime(folder, ns=(folder.stat().st_atime_ns, folder.stat().st_mtime_ns + 10**9))
    assert [line.split(':', 1)[0] for line in layout_violations(root, incremental=True)[1]] == [
        'output/logs/26/11/23/run/probe.py'
    ]


def test_an_unchanged_directory_is_read_from_the_journal(tmp_path, monkeypatch) -> None:
    root = _checkout(tmp_path)
    layout_violations(root, incremental=True)
    listed: list[Path] = []
    real = layout._listing
    monkeypatch.setattr(layout, '_listing', lambda folder: listed.append(folder) or real(folder))
    layout_violations(root, incremental=True)
    assert listed == [], 'no directory changed, so none is listed again'
    (root / 'pyproject.toml').write_text(_TABLE + "docs = ['.md']\n", encoding='utf-8')
    layout_violations(root, incremental=True)
    assert listed, 'PLANTED CONTROL: a changed declaration rescans every directory'


@pytest.mark.parametrize(
    'body',
    [
        '[tool.dev_lab.placement]\n',
        f"[tool.dev_lab.placement.layout]\n{_HOMES}rust = 'x'\n",
        "[tool.dev_lab.placement.layout]\nsrc = ['.py']\n",
        f"[tool.dev_lab.placement.layout]\n{_HOMES}'output/cache' = ['.py']\n",
        f"[tool.dev_lab.placement.layout]\n{_HOMES}'output/cache' = ['*']\n",
    ],
)
def test_an_absent_malformed_or_code_admitting_table_is_REFUSED(tmp_path, body) -> None:
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


def test_the_run_entry_refusal_names_the_violation_and_stays_silent_when_clean(tmp_path) -> None:
    root = _checkout(tmp_path)
    assert scan_refusal(root) is None
    _plant(root, 'scratch/old/.git')
    refusal = scan_refusal(root)
    assert refusal is not None
    assert 'scratch/old/: NO-BACKUP-COPIES' in refusal
    assert 'MERGE-OR-DELETE' in refusal


def test_the_cli_exits_one_on_a_violation_and_two_when_undeclared(tmp_path) -> None:
    root = _checkout(tmp_path)
    assert layout.main(['--root', str(root), '--full']) == 0
    _plant(root, 'tmp/x.txt')
    assert layout.main(['--root', str(root), '--full']) == 1
    (root / 'pyproject.toml').write_text('[tool.dev_lab.placement]\n', encoding='utf-8')
    assert layout.main(['--root', str(root)]) == 2


@pytest.mark.parametrize(
    ('rel', 'refused'),
    [
        ('output/logs/26/11/23/run/probe.py', 'DECLARED-LAYOUT: '),
        ('rust/crates/x/src/x.bundle', 'DECLARED-LAYOUT: '),
        ('tmp/probe.txt', 'DECLARED-LAYOUT: '),
        ('temp/derived.csv', 'DECLARED-LAYOUT: '),
        ('scratch/lane.patch', 'NO-BACKUP-COPIES: '),
        ('rust/.claude/memory/x.md', 'DECLARED-LAYOUT: '),
        ('output/logs/26/11/23/run/data.csv', None),
        ('src/pkg/x.py', None),
        ('README.md', None),
        ('.claude/worktrees/lane/tmp/x.py', None),
    ],
)
def test_the_write_hook_refuses_exactly_what_the_scan_refuses(tmp_path, rel, refused) -> None:
    root = _checkout(tmp_path)
    reason = refuse_layout(root / rel)
    assert (reason is None) is (refused is None)
    if refused:
        assert reason.startswith(refused)
        assert 'details: ' in reason


def test_a_checkout_without_a_layout_table_is_not_judged_by_the_hook(tmp_path) -> None:
    root = _checkout(tmp_path, '[tool.dev_lab.placement]\n')
    assert refuse_layout(root / 'tmp' / 'x.txt') is None
    assert scan_refusal(root) is None


def test_the_hook_entry_denies_a_write_into_an_undeclared_directory(tmp_path, capsys, monkeypatch) -> None:
    # tmp_path lies under the OS temp dir, which WRITES-STAY-IN-THE-TREE refuses first; this test is about the layout.
    monkeypatch.setattr(codeplace, 'refuse_outside_tree', lambda _path: None)
    root = _checkout(tmp_path)
    bad = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(root / 'tmp' / 'x.txt')}})
    assert main(stdin=io.StringIO(bad)) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert decision['permissionDecision'] == 'deny'
    assert 'DECLARED-LAYOUT' in decision['permissionDecisionReason']
