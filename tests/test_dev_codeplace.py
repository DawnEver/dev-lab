"""``dev_lab.dev.codeplace``: the placement map, the code-root allow-list and its write hook, on planted trees."""

from __future__ import annotations

import io
import json
import os
import time

import pytest

from dev_lab.dev.codeplace import (
    ARCHIVED_SEGMENTS,
    FAMILY_CODE_ROOTS,
    FAMILY_HOMES,
    PlacementNotDeclared,
    declared_misplaced,
    declared_placement,
    is_archived,
    main,
    misplaced_code,
    refuse_write,
)
from dev_lab.dev.famtests import noreflection
from dev_lab.dev.retiredfiles import RetiredFile

_ROOTS = ('src/', 'tests/', 'scratch/', '.claude/memory/')
_DAY = 86400.0


@pytest.fixture(autouse=True)
def _outside_every_write_prone_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pytest's tmp_path lives in the OS temp dir, a WRITES-STAY-IN-THE-TREE root; that rule has its own tests."""
    monkeypatch.setattr('dev_lab.dev.codeplace.refuse_outside_tree', lambda _path: None)


def _plant(root, rel: str, *, age_days: float = 0.0) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x\n', encoding='utf-8')
    stamp = time.time() - age_days * _DAY
    os.utime(path, (stamp, stamp))


@pytest.mark.parametrize(
    ('path', 'misplaced'),
    [
        ('output/logs/26/09/25/probe.py', True),
        ('cases/x/drive.rs', True),
        ('run_me.ps1', True),
        ('docs-src/snippet.sh', True),
        ('src/pkg/x.py', False),
        ('scratch/try.py', False),
        ('.claude/memory/2026/09/25/attachments/probe.py', False),
        ('output/logs/26/09/25/table.csv', False),
    ],
)
def test_the_allow_list_refuses_and_admits_each_planted_shape(tmp_path, path, misplaced) -> None:
    _plant(tmp_path, path)
    assert (misplaced_code(tmp_path, code_roots=_ROOTS) == [path]) is misplaced


def test_pruned_directories_are_not_walked(tmp_path) -> None:
    for rel in ('.venv/Lib/site.py', 'rust/target/debug/build.rs', 'worktrees/lane/output/x.py'):
        _plant(tmp_path, rel)
    assert misplaced_code(tmp_path, code_roots=_ROOTS, pruned_paths=('worktrees',)) == []


def test_the_cluster_run_directories_in_a_judged_tree_are_not_walked(tmp_path) -> None:
    """Measured 2026-10-12 on Ada: a run writes ``.lab-ci/env.sh`` and ``.lab-hpc/<run>/job.sh`` into its tree."""
    for rel in ('.lab-ci/env.sh', '.lab-hpc/run-abc-r0/job.sh'):
        (tmp_path / rel).parent.mkdir(parents=True)
        (tmp_path / rel).write_text('x', encoding='utf-8')
    (tmp_path / 'stray.sh').write_text('x', encoding='utf-8')
    assert misplaced_code(tmp_path, code_roots=_ROOTS) == ['stray.sh']


def test_an_empty_allow_list_is_REFUSED_rather_than_refusing_everything(tmp_path) -> None:
    with pytest.raises(ValueError, match='code roots'):
        misplaced_code(tmp_path, code_roots=())


# --- the declared placement, and the Write/Edit hook that reads the SAME declaration -------------


def _declare(root, body: str) -> None:
    (root / '.git').mkdir(exist_ok=True)
    (root / 'layout.toml').write_text(body, encoding='utf-8')


def test_the_family_code_roots_are_read_off_the_one_placement_map() -> None:
    assert set(FAMILY_CODE_ROOTS) <= set(FAMILY_HOMES.values())
    assert 'scripts/' not in FAMILY_HOMES.values(), 'dev mechanisms live in dev-lab (user ruling 2026-11-24)'
    assert FAMILY_HOMES['one-off experiment, probe or verification'] == 'scratch/'
    assert 'docs-src/' not in FAMILY_CODE_ROOTS
    assert 'output/logs/' not in FAMILY_CODE_ROOTS


def test_a_repo_declares_only_its_extra_roots_and_the_family_roots_come_with_them(tmp_path) -> None:
    _declare(tmp_path, "code_roots = ['rust/']\npruned_paths = ['.claude/worktrees']\n")
    placement = declared_placement(tmp_path)
    assert placement.code_roots == (*FAMILY_CODE_ROOTS, 'rust/')
    assert placement.pruned_paths == ('.claude/worktrees',)


@pytest.mark.parametrize('body', ['', "code_roots = 'rust/'\n", 'pruned_paths = [1]\n'])
def test_an_absent_or_malformed_declaration_is_REFUSED(tmp_path, body) -> None:
    if body:
        _declare(tmp_path, body)
    with pytest.raises(PlacementNotDeclared):
        declared_placement(tmp_path)


def test_the_declared_scan_refuses_a_planted_file_and_admits_an_extra_root(tmp_path) -> None:
    _declare(tmp_path, "code_roots = ['rust/']\n")
    _plant(tmp_path, 'rust/lib.rs')
    _plant(tmp_path, 'output/logs/26/10/02/probe.py')
    assert declared_misplaced(tmp_path) == ['output/logs/26/10/02/probe.py']


@pytest.mark.parametrize(
    ('rel', 'refused'),
    [
        ('output/logs/26/10/02/probe.py', True),
        ('docs-src/snippet.sh', True),
        ('run_me.py', True),
        ('src/pkg/x.py', False),
        ('scratch/try.py', False),
        ('rust/lib.rs', False),
        ('docs-src/page.md', False),
        ('.venv/Lib/site.py', False),
        ('.claude/worktrees/lane/output/x.py', False),
    ],
)
def test_the_write_hook_refuses_exactly_what_the_scan_refuses(tmp_path, rel, refused) -> None:
    _declare(tmp_path, "code_roots = ['rust/']\npruned_paths = ['.claude/worktrees']\n")
    reason = refuse_write(tmp_path / rel)
    assert (reason is not None) is refused
    if refused:
        assert 'layout.toml' in reason


def test_a_refusal_names_the_home_a_test_file_belongs_in(tmp_path) -> None:
    _declare(tmp_path, '')
    assert 'tests/' in refuse_write(tmp_path / 'tools' / 'test_x.py')
    assert 'scratch/' in refuse_write(tmp_path / 'tools' / 'probe.py')


def test_a_worktree_inside_the_checkout_is_judged_by_its_own_declaration(tmp_path) -> None:
    _declare(tmp_path, "pruned_paths = ['.claude/worktrees']\n")
    lane = tmp_path / '.claude' / 'worktrees' / 'lane'
    lane.mkdir(parents=True)
    _declare(lane, "code_roots = ['rust/']\n")
    assert refuse_write(lane / 'rust' / 'lib.rs') is None
    assert refuse_write(lane / 'output' / 'x.py') is not None


def test_a_path_in_no_declaring_repo_is_not_this_hooks_to_judge(tmp_path) -> None:
    (tmp_path / '.git').mkdir()
    assert refuse_write(tmp_path / 'anywhere' / 'x.py') is None


def test_the_hook_entry_hints_a_misplaced_file_and_allows_by_silence(tmp_path, capsys) -> None:
    """CODE-IN-CODE-ROOTS is a HINT (toolchain plan P3): the write runs, and the home is said as context."""
    _declare(tmp_path, '')
    bad = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(tmp_path / 'out' / 'p.py')}})
    assert main(stdin=io.StringIO(bad)) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert 'permissionDecision' not in decision
    assert 'out/p.py' in decision['additionalContext']
    good = json.dumps({'tool_name': 'Edit', 'tool_input': {'file_path': str(tmp_path / 'src' / 'p.py')}})
    assert main(stdin=io.StringIO(good)) == 0
    assert capsys.readouterr().out == ''
    assert main(stdin=io.StringIO('not json')) == 0


@pytest.mark.parametrize(
    ('rel', 'archived'),
    [
        ('attic/repo/x.py', True),
        ('src/pkg/archived/x.py', True),
        ('.claude/memory/2026/10/19/attachments/probe.py', True),
        ('rust/.claude/memory/2026/10/19/attachments/sub/probe.py', True),
        ('.claude/memory/2026/10/19/note.md', False),
        ('src/attachments/x.py', False),
        ('.claude/memory/attachments', False),
        ('src/notattic/x.py', False),
    ],
)
def test_archived_code_is_one_reading_of_the_archive_constants(rel: str, *, archived: bool) -> None:
    assert is_archived(rel) is archived


def test_noreflection_excludes_the_same_archive_codeplace_writes() -> None:
    assert noreflection.EXCLUDED_SEGMENTS is ARCHIVED_SEGMENTS
    assert noreflection.is_archived is is_archived


_INDEX = '.claude/rules/MEMORY.md'
_DOOR = "delete them through rem's migration"
_ROW = f'retired = [{{ path = "{_INDEX}", what = "a retired generated index", door = "{_DOOR}" }}]\n'


def test_the_declared_rows_are_read_off_the_placement_table(tmp_path) -> None:
    _declare(tmp_path, _ROW)
    assert declared_placement(tmp_path).retired == (RetiredFile(_INDEX, 'a retired generated index', _DOOR),)
    _declare(tmp_path, '')
    assert declared_placement(tmp_path).retired == ()


@pytest.mark.parametrize(
    'body',
    [
        "retired = 'x'\n",
        "retired = ['x']\n",
        "retired = [{ path = 'a/b.md', what = 'w' }]\n",
        "retired = [{ path = '', what = 'w', door = 'd' }]\n",
        "retired = [{ path = 'a/b.md', what = 'w', door = 'd', extra = 'e' }]\n",
    ],
)
def test_a_malformed_retired_row_is_REFUSED(tmp_path, body) -> None:
    _declare(tmp_path, body)
    with pytest.raises(PlacementNotDeclared, match='retired'):
        declared_placement(tmp_path)
