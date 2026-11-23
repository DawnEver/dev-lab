"""ONE TASK LEDGER PER MACHINE, AND THE BRANCH NAMES THE TASK (user ruling 2026-11-23).

The ledger is ``<machine home>/repos/tasks``, a clone of the family ``[tasks] remote``; a checkout works on the
task its branch ``pr/<slug>/<feature>`` names, open in that ledger. No binding store exists.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _arch_corpus import module_names
from _task_ledger import on_branch, open_task, plant_ledger
from lab_commons.config import CONFIG_ENV
from lab_commons.home import HOME_ENV, part

from dev_lab.dev import agent_wiring, forgetask, taskledger
from dev_lab.dev.branchset import FAMILY_EPHEMERAL, BranchSet
from dev_lab.dev.sessionbranch import rename_remedy

_GIT = shutil.which('git') or 'git'


def test_the_ledger_is_the_machine_homes_repos_tasks_clone() -> None:
    ledger = plant_ledger()
    assert ledger == part('repos') / 'tasks'
    assert taskledger.ledger() == ledger


def test_a_ledger_that_is_no_clone_names_the_clone_of_the_family_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PLANTED CONTROL: nothing cloned yet -- the resolver refuses naming the clone, it never guesses a path."""
    machine = tmp_path / 'machine.toml'
    machine.write_text('[tasks]\nremote = "https://forge.example/t/tasks.git"\n', encoding='utf-8')
    monkeypatch.setenv(CONFIG_ENV, str(machine))
    with pytest.raises(taskledger.LedgerUnresolvedError, match='not a git clone') as refused:
        taskledger.ledger()
    said = str(refused.value)
    target = (part('repos') / 'tasks').as_posix()
    assert f'Door: git clone https://forge.example/t/tasks.git {target}' in said
    (part('repos') / 'tasks').mkdir(parents=True)
    with pytest.raises(taskledger.LedgerUnresolvedError):
        taskledger.ledger()  # a bare directory is no clone either


def test_an_undeclared_remote_still_names_where_the_clone_goes() -> None:
    with pytest.raises(taskledger.LedgerUnresolvedError, match=r'\[tasks\] remote') as refused:
        taskledger.ledger()
    assert (part('repos') / 'tasks').as_posix() in str(refused.value)


def test_the_branch_names_the_task_and_the_ledger_judges_it_open(tmp_path: Path) -> None:
    ledger = plant_ledger()
    work = on_branch(tmp_path / 'work', 'main')
    assert taskledger.task_of(work) is None, 'planted control: a branch naming no task is no task'
    on_branch(work, 'pr/toolchain/a')
    with pytest.raises(ValueError, match='no task toolchain'):
        taskledger.task_of(work)
    assert open_task(ledger, 'toolchain') == 'toolchain@a1'
    assert taskledger.task_of(work) == 'toolchain@a1'
    open_task(ledger, 'toolchain', status='closed')
    with pytest.raises(ValueError, match='not open'):
        taskledger.task_of(work)


def test_a_retired_session_record_is_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The binding store is cancelled: a leftover record binds nothing; only the branch says which task."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    leftover = tmp_path / 'home' / 'state' / 'sessions' / 's.json'
    leftover.parent.mkdir(parents=True)
    leftover.write_text(json.dumps({'session': 's', 'task': 'toolchain@a1'}), encoding='utf-8')
    plant_ledger()
    assert taskledger.task_of(on_branch(tmp_path / 'work', 'main')) is None


def test_a_task_slug_is_read_from_a_nested_head_only() -> None:
    assert taskledger.slug_on('pr/toolchain/a') == 'toolchain'
    for other in ('pr/toolchain', 'pr/toolchain/', 'main', 'lane/x/y', None, 'pr/Bad_Slug/a'):
        assert taskledger.slug_on(other) is None, other


def test_a_tasks_heads_are_nested_under_it_and_never_the_bare_task() -> None:
    assert taskledger.head_for('toolchain', 'a') == 'pr/toolchain/a'
    assert taskledger.under('pr/toolchain/a', 'toolchain')
    assert taskledger.under('pr/toolchain/a/b', 'toolchain')
    for other in ('pr/toolchain', 'pr/toolchain/', 'pr/toolchainx/a', 'pr/other/a', 'toolchain/a', 'pr/a'):
        assert not taskledger.under(other, 'toolchain'), other


def test_origin_admits_a_nested_task_head_by_the_family_glob() -> None:
    """ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES: fnmatch's `*` crosses `/`, so `pr/*` admits `pr/<task>/<feature>`."""
    declared = BranchSet(trunk='main', sessions=frozenset({'integrate/main'}), ephemeral=FAMILY_EPHEMERAL)
    assert declared.admits('pr/toolchain/a')
    assert not declared.admits('lane/toolchain/a'), 'planted control: local fan-out stays undeclared'


def test_git_refuses_a_bare_task_branch_beside_its_heads(tmp_path: Path) -> None:
    """Why a task never publishes a bare `pr/<task>`: the ref would have to be a file and a directory at once."""
    subprocess.run([_GIT, 'init', '-q', '-b', 'main', str(tmp_path)], check=True)
    subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'seed'],
        cwd=tmp_path, check=True,
    )  # fmt: skip
    subprocess.run([_GIT, 'branch', 'pr/toolchain/a'], cwd=tmp_path, check=True)
    bare = subprocess.run([_GIT, 'branch', 'pr/toolchain'], cwd=tmp_path, capture_output=True, check=False)
    assert bare.returncode != 0


def test_the_rename_remedy_names_the_tasks_head() -> None:
    assert 'git branch -m fix/x pr/x`' in rename_remedy('fix/x'), 'no task: the flat pr/<feature> head'
    named = rename_remedy('fix/x', 'toolchain')
    assert 'git branch -m fix/x pr/toolchain/x`' in named
    assert 'push -u origin pr/toolchain/x' in named


def test_pr_create_suggests_the_checkouts_task_head(tmp_path: Path) -> None:
    ledger = plant_ledger()
    work = on_branch(tmp_path / 'work', 'pr/toolchain/x')
    assert forgetask.head_advice('pr/x', work) == (), 'planted control: the task is not open, nothing suggested'
    open_task(ledger, 'toolchain')
    [said] = forgetask.head_advice('pr/x', work)
    assert 'pr/toolchain/<feature>' in said
    assert 'git branch -m pr/x pr/toolchain/x' in said
    assert forgetask.head_advice('pr/toolchain/x', work) == ()


def test_dev_lab_binds_nothing_so_its_venv_cannot_block_a_prompt() -> None:
    """No dev-lab prompt row derives or writes a task; the reader has no command line to go stale."""
    binders = [wire.name for wire in agent_wiring.WIRING if wire.module == taskledger.__name__]
    assert binders == []
    names = module_names(taskledger)
    assert 'task_of' in names, 'planted control: the reader the module keeps is found'
    assert not {'bind', 'main', 'binding', 'binding_path'} & names
    assert 'pr/<slug>/<feature>' in taskledger.DOOR
