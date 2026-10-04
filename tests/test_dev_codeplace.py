"""``lab_commons.dev.codeplace``: the code-root allow-list and the scratch lifecycle, on planted trees."""

from __future__ import annotations

import datetime
import io
import json
import os
import time

import pytest

from lab_commons.dev.codeplace import (
    FAMILY_CODE_ROOTS,
    FAMILY_HOMES,
    PlacementNotDeclared,
    archive_scratch,
    declared_misplaced,
    declared_placement,
    main,
    misplaced_code,
    overdue_scratch,
    pending_scratch,
    refuse_write,
)

_ROOTS = ('src/', 'tests/', 'scratch/', '.claude/memory/')
_DAY = 86400.0


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


def test_an_empty_allow_list_is_REFUSED_rather_than_refusing_everything(tmp_path) -> None:
    with pytest.raises(ValueError, match='code roots'):
        misplaced_code(tmp_path, code_roots=())


def test_only_a_file_older_than_the_limit_is_overdue(tmp_path) -> None:
    _plant(tmp_path, 'scratch/fresh.py', age_days=0.5)
    _plant(tmp_path, 'scratch/sub/old.py', age_days=4.0)
    scratch = tmp_path / 'scratch'
    assert overdue_scratch(scratch, root=tmp_path, max_age_days=3.0) == ['scratch/sub/old.py']
    assert [p for p, _ in pending_scratch(scratch, root=tmp_path)] == ['scratch/sub/old.py', 'scratch/fresh.py']
    assert pending_scratch(tmp_path / 'absent', root=tmp_path) == []


def test_an_archive_lands_beside_that_days_memory_and_records_why(tmp_path) -> None:
    _plant(tmp_path, 'scratch/probe.py')
    memory = tmp_path / '.claude' / 'memory'
    dest = archive_scratch(
        tmp_path / 'scratch/probe.py', why='read the card back', root=tmp_path, memory=memory,
        day=datetime.date(2026, 9, 25),
    )  # fmt: skip
    assert dest == memory / '2026/09/25/attachments/probe.py'
    assert not (tmp_path / 'scratch/probe.py').exists()
    assert '`probe.py` -- read the card back (from `scratch/probe.py`)' in (dest.parent / 'INDEX.md').read_text(
        encoding='utf-8'
    )


def test_an_archive_without_a_reason_is_REFUSED_and_moves_nothing(tmp_path) -> None:
    _plant(tmp_path, 'scratch/probe.py')
    with pytest.raises(ValueError, match='WHY'):
        archive_scratch(tmp_path / 'scratch/probe.py', why=' ', root=tmp_path, memory=tmp_path / 'm')
    assert (tmp_path / 'scratch/probe.py').exists()


def test_an_archive_never_overwrites(tmp_path) -> None:
    day = datetime.date(2026, 9, 25)
    _plant(tmp_path, 'scratch/a/probe.py')
    _plant(tmp_path, 'scratch/b/probe.py')
    memory = tmp_path / 'm'
    archive_scratch(tmp_path / 'scratch/a/probe.py', why='first', root=tmp_path, memory=memory, day=day)
    with pytest.raises(ValueError, match='already exists'):
        archive_scratch(tmp_path / 'scratch/b/probe.py', why='second', root=tmp_path, memory=memory, day=day)
    dest = archive_scratch(
        tmp_path / 'scratch/b/probe.py', why='second', root=tmp_path, memory=memory, day=day, name='b__probe.py'
    )
    assert dest.name == 'b__probe.py'


# --- the declared placement, and the Write/Edit hook that reads the SAME declaration -------------


def _declare(root, body: str) -> None:
    (root / '.git').mkdir(exist_ok=True)
    (root / 'pyproject.toml').write_text(f'[tool.lab_commons.placement]\n{body}', encoding='utf-8')


def test_the_family_code_roots_are_read_off_the_one_placement_map() -> None:
    assert set(FAMILY_CODE_ROOTS) <= set(FAMILY_HOMES.values())
    assert FAMILY_HOMES['repo-development mechanism'] == 'scripts/'
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
        assert 'pyproject.toml' in reason


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


def test_the_hook_entry_denies_through_the_harness_json_and_allows_by_silence(tmp_path, capsys) -> None:
    _declare(tmp_path, '')
    bad = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(tmp_path / 'out' / 'p.py')}})
    assert main(stdin=io.StringIO(bad)) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert decision['permissionDecision'] == 'deny'
    assert 'out/p.py' in decision['permissionDecisionReason']
    good = json.dumps({'tool_name': 'Edit', 'tool_input': {'file_path': str(tmp_path / 'src' / 'p.py')}})
    assert main(stdin=io.StringIO(good)) == 0
    assert capsys.readouterr().out == ''
    assert main(stdin=io.StringIO('not json')) == 0
