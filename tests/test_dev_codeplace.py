"""``dev_lab.dev.codeplace``: the code-root allow-list and the scratch lifecycle, on planted trees."""

from __future__ import annotations

import contextlib
import io
import json
import os
import time

import pytest

from lab_commons import launch
from dev_lab.dev.codeplace import (
    ARCHIVED_SEGMENTS,
    FAMILY_CODE_ROOTS,
    FAMILY_HOMES,
    FAMILY_STRAY_ROOTS,
    PlacementNotDeclared,
    StrayCensusUnreadable,
    declared_misplaced,
    declared_placement,
    declared_strays,
    is_archived,
    main,
    misplaced_code,
    refuse_write,
    stray_files,
    stray_refusal,
)
from dev_lab.dev.famtests import noreflection

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


# -- STRAY-FILE-REFUSED: an untracked, non-ignored file outside the stray roots -------------------------------


def _repo(root, *, stray_roots: str = '[]') -> None:
    launch.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'pyproject.toml').write_text(
        f"[tool.lab_commons.placement]\npruned_paths = ['lanes']\nstray_roots = {stray_roots}\n", encoding='utf-8'
    )
    (root / '.gitignore').write_text('output/\n', encoding='utf-8')
    launch.run(['git', '-C', str(root), 'add', 'pyproject.toml', '.gitignore'], check=True)


def test_the_incidents_vendor_logs_in_the_root_are_strays_and_staged_ignored_scratch_files_are_not(tmp_path) -> None:
    _repo(tmp_path, stray_roots="['data/']")
    for rel in (
        'job_node_10_0_0_1_2026-10-20T12_19_56_1.log',  # the planted control: the 2026-10-20 incident
        'rust/pybind/uv.lock',
        'output/logs/26/10/20/jobsystem/status.txt',  # ignored: an artefact in its place
        'scratch/probe.py',
        'data/drop.csv',  # a repo-declared stray root
        'lanes/x/junk.txt',  # a pruned path: another checkout, judged by its own run
        'src/new_module.py',
    ):
        _plant(tmp_path, rel)
    launch.run(['git', '-C', str(tmp_path), 'add', 'src/new_module.py'], check=True)  # meant: staged
    assert declared_strays(tmp_path) == ['job_node_10_0_0_1_2026-10-20T12_19_56_1.log', 'rust/pybind/uv.lock']
    reason = stray_refusal(tmp_path)
    assert reason is not None
    assert reason.startswith('STRAY-FILE-REFUSED: 2 untracked')
    assert 'output/logs/<yy>/<mm>/<dd>/<kind>/' in reason


def test_a_clean_checkout_and_an_undeclared_one_are_silent(tmp_path) -> None:
    _repo(tmp_path)
    assert stray_refusal(tmp_path) is None
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    _plant(tmp_path, 'stray.log')
    assert stray_refusal(tmp_path) is None


def test_a_census_git_cannot_read_is_refused_not_clean(tmp_path) -> None:
    with pytest.raises(StrayCensusUnreadable):
        stray_files(tmp_path / 'not-a-repo', stray_roots=FAMILY_STRAY_ROOTS)


def test_the_shell_hook_blocks_naming_the_stray_and_a_repeated_stop_is_let_through(tmp_path) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'JobSystem.jlog')
    out = io.StringIO()
    payload = {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'cwd': str(tmp_path / 'scratch')}
    (tmp_path / 'scratch').mkdir()
    with contextlib.redirect_stdout(out):
        assert main(['stray'], stdin=io.StringIO(json.dumps(payload))) == 0
    decision = json.loads(out.getvalue())
    assert decision['decision'] == 'block'
    assert 'JobSystem.jlog' in decision['reason']
    again = io.StringIO()
    with contextlib.redirect_stdout(again):
        main(['stray'], stdin=io.StringIO(json.dumps({'hook_event_name': 'Stop', 'stop_hook_active': True})))
    assert again.getvalue() == ''


def test_the_pre_commit_row_exits_non_zero_while_a_stray_exists(tmp_path, monkeypatch) -> None:
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(['stray-check']) == 0
    _plant(tmp_path, 'status.txt')
    assert main(['stray-check']) == 1
