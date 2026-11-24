"""``dev_lab.dev.strays``: STRAY-FILE-REFUSED -- the untracked-file census, its refusal and its hooks."""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import os
import time
from pathlib import PurePosixPath

import _arch_corpus
import pytest
from lab_commons import launch

from dev_lab.dev.codeplace import FAMILY_STRAY_ROOTS
from dev_lab.dev.disclosure import problems
from dev_lab.dev.retiredfiles import RetiredFile
from dev_lab.dev.strays import (
    StrayCensusUnreadable,
    declared_strays,
    main,
    retired_copies,
    stray_files,
    stray_refusal,
)

_DAY = 86400.0


def _plant(root, rel: str, *, age_days: float = 0.0) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x' + chr(10), encoding='utf-8')
    stamp = time.time() - age_days * _DAY
    os.utime(path, (stamp, stamp))


# -- STRAY-FILE-REFUSED: an untracked, non-ignored file outside the stray roots -------------------------------


def _repo(root, *, stray_roots: str = '[]', retired: str = '') -> None:
    launch.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'pyproject.toml').write_text(
        f"[tool.dev_lab.placement]\npruned_paths = ['lanes']\nstray_roots = {stray_roots}\n{retired}", encoding='utf-8'
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
        assert main(['hook'], stdin=io.StringIO(json.dumps(payload))) == 0
    decision = json.loads(out.getvalue())
    assert decision['decision'] == 'block'
    assert 'JobSystem.jlog' in decision['reason']
    again = io.StringIO()
    with contextlib.redirect_stdout(again):
        main(['hook'], stdin=io.StringIO(json.dumps({'hook_event_name': 'Stop', 'stop_hook_active': True})))
    assert again.getvalue() == ''


def test_the_pre_commit_row_exits_non_zero_while_a_stray_exists(tmp_path, monkeypatch) -> None:
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(['check']) == 0
    _plant(tmp_path, 'status.txt')
    assert main(['check']) == 1


def test_the_stray_refusal_fits_the_budget_and_gives_each_file_one_remedy_by_its_kind(tmp_path) -> None:
    _repo(tmp_path)
    for rel in ('probe.py', 'fr_parts.txt', *(f'log{n}.txt' for n in range(30))):
        _plant(tmp_path, rel)
    reason = stray_refusal(tmp_path)
    assert reason is not None
    assert problems(reason, 'refusal') == []
    first, exits, _details = reason.splitlines()
    assert first.startswith('STRAY-FILE-REFUSED: 32 untracked file(s)')
    assert '(+29 more)' in first
    assert 'probe.py -> scratch/<yy>/<mm>/<dd>/<kind>/' in exits
    assert 'data -> output/logs/<yy>/<mm>/<dd>/<kind>/' in exits
    assert 'git add' not in exits


def test_a_stray_under_a_code_root_is_a_file_meant_and_its_one_remedy_is_git_add(tmp_path) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'src/new_module.py')
    reason = stray_refusal(tmp_path)
    assert reason is not None
    assert 'git add src/new_module.py' in reason.splitlines()[1]
    assert 'scratch/' not in reason.splitlines()[1]


#: rem's retired generated index: a CONSUMER's tree path, so it is test data here and never a literal in src/.
_INDEX = '.claude/rules/MEMORY.md'
_DOOR = "delete them through rem's migration"
_ROW = f'retired = [{{ path = "{_INDEX}", what = "a retired generated index", door = "{_DOOR}" }}]\n'


def _plant_the_incident(root) -> None:
    """The 2026-11-17 wall: twelve stale indexes, eleven under src/, beside one ordinary new source file."""
    for one in (_INDEX, *(f'src/pkg{n}/{_INDEX}' for n in range(11)), 'src/new_module.py'):
        _plant(root, one)


def test_a_declared_retired_file_is_named_with_its_deletion_door_and_never_git_add(tmp_path) -> None:
    """The checkout declares the row in its own placement table, and the stray census reads it from there."""
    _repo(tmp_path, retired=_ROW)
    _plant_the_incident(tmp_path)
    reason = stray_refusal(tmp_path)
    assert reason is not None
    assert problems(reason, 'refusal') == []
    exits = reason.splitlines()[1]
    assert f'12 x {_INDEX} retired (a retired generated index): {_DOOR}' in exits
    assert 'git add src/new_module.py' in exits, 'a file meant still gets the add remedy'
    assert 'MEMORY.md' not in exits.split('git add', 1)[1], 'a retired file is never offered to git add'
    assert 'data -> ' not in exits, 'the root copy is not data either'


def test_PLANTED_CONTROL_with_no_declared_row_the_same_strays_are_judged_as_before(tmp_path) -> None:
    """No row, no retired exit: the leaf holds no table of its own, so an index under src/ reads as meant."""
    _repo(tmp_path)
    _plant_the_incident(tmp_path)
    reason = stray_refusal(tmp_path)
    assert reason is not None
    exits = reason.splitlines()[1]
    assert 'retired' not in exits
    assert f'git add src/new_module.py src/pkg0/{_INDEX} src/pkg1/{_INDEX}' in exits
    assert 'data -> ' in exits, 'the root copy is data, as before'


def test_the_retired_check_takes_its_table_with_no_default() -> None:
    """The leaf holds no consumer's rows: a caller that forgets the table is a TypeError, never an empty verdict."""
    assert inspect.signature(retired_copies).parameters['retired'].default is inspect.Parameter.empty
    row = RetiredFile(_INDEX, 'w', 'd')
    assert retired_copies([_INDEX, 'src/x.py'], retired=(row,)) == {row: [_INDEX]}
    assert retired_copies([_INDEX, 'src/x.py'], retired=()) == {}


@pytest.mark.parametrize(
    ('rel', 'retired'),
    [
        (_INDEX, True),
        (f'src/pkg/sub/{_INDEX}', True),
        (f'attic/old/{_INDEX}', False),  # an archive is frozen source: rem's migration skips it
        ('.claude/rules/taste.md', False),
        ('docs/rules/MEMORY.md', False),
        ('src/pkg/x.claude/rules/MEMORY.md', False),
    ],
)
def test_a_retired_file_is_matched_by_its_path_at_any_depth_outside_an_archive(rel: str, *, retired: bool) -> None:
    row = RetiredFile(_INDEX, 'w', 'd')
    assert (retired_copies([rel], retired=(row,)) == {row: [rel]}) is retired


def _literals_naming(text: str, needle: str) -> list[str]:
    """Every string constant of module *text* containing *needle*, docstrings excepted: those are prose."""
    tree = ast.parse(text)
    docs = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and needle in node.value
        and id(node) not in docs
    ]


def test_PLANTED_CONTROL_the_literal_reading_sees_a_path_and_a_glob_but_not_a_docstring() -> None:
    planted = f'"""Mentions {_INDEX} in prose."""\nA = {_INDEX!r}\nB = "**/{_INDEX}"\n'
    assert _literals_naming(planted, _INDEX) == [_INDEX, f'**/{_INDEX}']


def test_no_source_module_holds_the_retired_index_as_a_literal_or_a_glob() -> None:
    """The leaf scan's remedy, taken: rem's layout is the consumer's data, never a path literal in src/."""
    modules = _arch_corpus.source_modules()
    _arch_corpus.assert_floor(len(modules), _arch_corpus.SOURCE_FLOOR, 'retired-index literal')
    found = [_arch_corpus.rel(path) for path in modules if _literals_naming(path.read_text(encoding='utf-8'), _INDEX)]
    assert found == []


# -- no checkout holds a task ledger any more (user ruling 2026-11-23): a leftover one is a stray ------------------


def _stop(root) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(['hook'], stdin=io.StringIO(json.dumps({'hook_event_name': 'Stop', 'cwd': str(root)})))
    return out.getvalue()


def test_a_ledger_left_inside_a_checkout_is_a_stray_like_any_other(tmp_path) -> None:
    """The ledger is the global tasks repo (taskledger.ledger); the in-checkout exemption is gone with it."""
    _repo(tmp_path)
    assert _stop(tmp_path) == '', 'planted control: a clean tree is silent'
    leftover = PurePosixPath('.claude', 'tasks', 'plecs-alignment', 'TASK.md').as_posix()  # the retired place
    _plant(tmp_path, leftover)
    assert declared_strays(tmp_path) == [leftover]
    assert json.loads(_stop(tmp_path))['decision'] == 'block'


# -- O52: a stray already carried by a pushed PR head, the merges-only door, and another writer's file -----------


def _commit(root, message: str = 'c') -> None:
    run = ['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=/dev/null']
    launch.run([*run, 'commit', '-q', '-m', message], check=True)


def _integrated(root) -> None:
    _repo(root)
    manifest = root / 'pyproject.toml'
    manifest.write_text(
        manifest.read_text(encoding='utf-8')
        + "code_roots = ['src/']\n[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n",
        encoding='utf-8',
    )
    launch.run(['git', '-C', str(root), 'add', 'pyproject.toml'], check=True)
    _commit(root)
    launch.run(['git', '-C', str(root), 'branch', '-q', '-M', 'integrate/main'], check=True)


def _pushed_pr_head_holding(root, rel: str) -> None:
    """A local remote-tracking pr/* ref whose tree holds *rel* with the content of the working file."""
    launch.run(['git', '-C', str(root), 'add', rel], check=True)
    _commit(root, 'pr')
    launch.run(['git', '-C', str(root), 'update-ref', 'refs/remotes/origin/pr/t/f', 'HEAD'], check=True)
    launch.run(['git', '-C', str(root), 'reset', '-q', '--soft', 'HEAD~1'], check=True)
    launch.run(['git', '-C', str(root), 'rm', '-q', '--cached', rel], check=True)


def test_a_stray_a_pushed_pr_head_already_carries_is_not_refused(tmp_path) -> None:
    _integrated(tmp_path)
    _plant(tmp_path, 'src/a.py')
    _pushed_pr_head_holding(tmp_path, 'src/a.py')
    assert stray_refusal(tmp_path) is None
    (tmp_path / 'src' / 'a.py').write_text('changed\n', encoding='utf-8')  # PLANTED: other content is a stray
    assert 'src/a.py' in (stray_refusal(tmp_path) or '')


def test_on_the_integration_branch_the_door_is_the_pr_route_never_git_add(tmp_path) -> None:
    _integrated(tmp_path)
    _plant(tmp_path, 'src/b.py')
    reason = stray_refusal(tmp_path) or ''
    assert 'forge pr create' in reason
    assert 'git add' not in reason
    launch.run(['git', '-C', str(tmp_path), 'switch', '-q', '-c', 'lane/x'], check=True)
    assert 'git add src/b.py' in (stray_refusal(tmp_path) or '')  # PLANTED: a lane still stages it


def test_only_the_strays_this_session_wrote_are_judged(tmp_path) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'mine-notes.log')
    _plant(tmp_path, 'someone-else.log')
    reason = stray_refusal(tmp_path, mentions='wrote mine-notes.log here') or ''
    assert 'mine-notes.log' in reason
    assert 'someone-else.log' not in reason
    assert stray_refusal(tmp_path, mentions='nothing of theirs') is None
    assert 'someone-else.log' in (stray_refusal(tmp_path) or '')  # PLANTED: without a transcript, all are judged
