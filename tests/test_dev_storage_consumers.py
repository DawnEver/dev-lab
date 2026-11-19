"""D75, the consumers: every writer that held its own ``output/...``, worktree or temp spelling follows the kinds.

Each move is proved both ways: a BOUND root receives the write, and the PLANTED CONTROL -- nothing bound -- keeps it
in the tree exactly where it was. The binding is planted by replacing :func:`lab_commons.storage.declared` (what
every resolver asks when no layers are passed), never by this machine's own file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons import storage as storage_kinds

from dev_lab.dev import (
    agenthooks,
    checkout,
    datedlog,
    liverun,
    metrics,
    storage,
    walls,
    worktree_outputs,
    worktreeplace,
)
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.supervise import cli as supervise_cli

GIT = shutil.which('git') or 'git'


def _git(*args: str, cwd: Path) -> None:
    subprocess.run([GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    tree = tmp_path / 'repo-a'
    tree.mkdir()
    _git('init', '-q', cwd=tree)
    _git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init', cwd=tree)
    return tree


def _bind(monkeypatch: pytest.MonkeyPatch, **roots: str) -> None:
    planted = storage_kinds.declared({'storage': {'roots': roots}}, {})
    real = storage_kinds.declared
    monkeypatch.setattr(
        storage_kinds,
        'declared',
        lambda machine=None, family=None: planted if machine is None else real(machine, family),
    )


def test_metrics_and_walls_follow_a_bound_output(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    unbound = metrics.log_file(repo, metrics.PUSH)
    assert unbound.is_relative_to(repo / 'output' / 'logs'), 'PLANTED CONTROL: unbound stays in the tree'
    _bind(monkeypatch, output=str(tmp_path / 'big' / '{repo}'))
    assert metrics.log_file(repo, metrics.PUSH).is_relative_to(tmp_path / 'big' / 'repo-a' / 'logs')
    assert walls.ledger(repo).is_relative_to(tmp_path / 'big' / 'repo-a' / 'logs')


def test_the_supervise_journal_follows_a_bound_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / 'target'
    assert supervise_cli._journal(project) == project / 'output' / 'supervise' / 'cycles.jsonl'
    _bind(monkeypatch, output=str(tmp_path / 'big' / '{repo}'))
    assert supervise_cli._journal(project) == tmp_path / 'big' / 'target' / 'supervise' / 'cycles.jsonl'


def test_a_dated_log_and_the_test_temp_follow_a_bound_output(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert datedlog.dated_base(repo, 'output/logs') == repo / 'output' / 'logs', 'PLANTED CONTROL'
    assert datedlog.dated_base(repo, 'reports') == repo / 'reports'
    _bind(monkeypatch, output=str(tmp_path / 'big' / '{repo}'))
    assert datedlog.dated_base(repo, 'output/logs') == tmp_path / 'big' / 'repo-a' / 'logs'
    assert datedlog.dated_base(repo, 'reports') == repo / 'reports', 'a base outside output never moves'
    assert datedlog.dated_log(repo, 'x.log', base='output/logs', kind='pytest').is_relative_to(tmp_path / 'big')


def test_worktrees_live_in_a_bound_home(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert worktreeplace.home(repo) == repo / worktreeplace.WORKTREES_REL, 'PLANTED CONTROL'
    assert storage_kinds.KINDS['worktrees'] == worktreeplace.WORKTREES_REL, 'one spelling of the in-tree default'
    home = tmp_path / 'trees' / '{repo}'
    _bind(monkeypatch, worktrees=str(home))
    bound = tmp_path / 'trees' / 'repo-a'
    assert worktreeplace.home(repo) == bound
    assert worktreeplace.is_inside(bound / 'lane', repo)
    assert not worktreeplace.is_inside(repo / worktreeplace.WORKTREES_REL / 'lane', repo)
    misplaced = worktreeplace.Misplaced(tmp_path / 'elsewhere', repo)
    assert misplaced.move_to == bound / 'elsewhere'
    (bound / 'orphan').mkdir(parents=True)
    assert checkout.orphan_directories(repo) == ((bound / 'orphan').resolve(),)


def test_a_worktree_output_goes_home_to_the_bound_root(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rel = Path('output', 'logs', '26', 'x.log')
    assert worktree_outputs._home(repo, rel) == repo / rel, 'PLANTED CONTROL'
    _bind(monkeypatch, output=str(tmp_path / 'big' / '{repo}'))
    assert worktree_outputs._home(repo, rel) == tmp_path / 'big' / 'repo-a' / 'logs' / '26' / 'x.log'
    assert worktree_outputs._home(repo, Path('reports', 'y')) == repo / 'reports' / 'y'


def test_the_tree_a_run_never_reads_is_derived_from_the_kinds() -> None:
    assert set(liverun.NOT_THE_TREE) == {'output', '.venvs', '.claude', '.venv', '.venv-current'}
    assert 'target' not in liverun.NOT_THE_TREE, 'a run may load a native build: build is not an unread kind'


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


def test_a_published_bound_home_admits_a_worktree_there_and_nothing_else(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rules: Path
) -> None:
    bound = tmp_path / 'trees' / 'repo-a'
    add = f'git worktree add --detach {bound.as_posix()}/lane HEAD'
    assert agenthooks.decide(add, rules, cwd=repo) is not None, 'PLANTED CONTROL: nothing published, refused'
    _bind(monkeypatch, worktrees=str(tmp_path / 'trees' / '{repo}'))
    published = storage.publish(storage.roots_file())
    assert json.loads(published.read_text(encoding='utf-8')) == {
        'worktrees': {'root': str(tmp_path / 'trees' / '{repo}'), 'default': '.claude/worktrees'}
    }
    assert agenthooks.decide(add, rules, cwd=repo) is None, add
    elsewhere = f'git worktree add --detach {(tmp_path / "other" / "lane").as_posix()} HEAD'
    assert agenthooks.decide(elsewhere, rules, cwd=repo) is not None, 'outside both homes is still refused'
    mixed = f'{add} && git worktree add --detach ../stray HEAD'
    assert agenthooks.decide(mixed, rules, cwd=repo) is not None, 'one stray target refuses the whole line'
    escape = f'git worktree add --detach {bound.as_posix()}/../../escape HEAD'
    assert agenthooks.decide(escape, rules, cwd=repo) is not None, 'a dot-segment out of the home is refused'


def test_publish_with_nothing_bound_writes_an_empty_table(tmp_path: Path) -> None:
    to = storage.publish(tmp_path / 'roots.json', declared=storage_kinds.declared({}, {}))
    assert json.loads(to.read_text(encoding='utf-8')) == {}
