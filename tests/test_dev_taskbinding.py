"""A SESSION KEEPS ITS ONE TASK (D5): its branches derive from the user's binding as ``pr/<task>/<feature>``."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _arch_corpus import module_names
from _rem_binding import bind_as_rem, repo_key
from lab_commons.home import HOME_ENV

from dev_lab.dev import agent_wiring, forgetask, taskbinding
from dev_lab.dev.branchset import FAMILY_EPHEMERAL, BranchSet
from dev_lab.dev.sessionbranch import rename_remedy

_SESSION = '1d9000bd-6cd0-42ab-873f-102cd963e53d'
_GIT = shutil.which('git') or 'git'


def _task(root: Path, slug: str = 'toolchain') -> None:
    folder = root / '.claude' / 'tasks' / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'TASK.md').write_text('---\nauthority: a1\nstatus: open\n---\n', encoding='utf-8')
    if not (root / '.git').exists():
        subprocess.run([_GIT, 'init', '-q', str(root)], check=True, capture_output=True)


def test_a_tasks_heads_are_nested_under_it_and_never_the_bare_task() -> None:
    assert taskbinding.head_for('toolchain', 'a') == 'pr/toolchain/a'
    assert taskbinding.under('pr/toolchain/a', 'toolchain')
    assert taskbinding.under('pr/toolchain/a/b', 'toolchain')
    for other in ('pr/toolchain', 'pr/toolchain/', 'pr/toolchainx/a', 'pr/other/a', 'toolchain/a', 'pr/a'):
        assert not taskbinding.under(other, 'toolchain'), other


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


def test_the_rename_remedy_names_the_bound_tasks_head() -> None:
    assert 'git branch -m fix/x pr/x`' in rename_remedy('fix/x'), 'unbound: the flat pr/<feature> head'
    bound = rename_remedy('fix/x', 'toolchain')
    assert 'git branch -m fix/x pr/toolchain/x`' in bound
    assert 'push -u origin pr/toolchain/x' in bound


def test_pr_create_suggests_the_bound_tasks_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = {'CLAUDE_CODE_SESSION_ID': _SESSION}
    _task(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert forgetask.head_advice('pr/x', env) == (), 'planted control: unbound, nothing suggested'
    assert bind_as_rem(tmp_path, _SESSION, 'toolchain') == 'toolchain@a1'
    [said] = forgetask.head_advice('pr/x', env)
    assert 'pr/toolchain/<feature>' in said
    assert 'git branch -m pr/x pr/toolchain/x' in said
    assert forgetask.head_advice('pr/toolchain/x', env) == ()
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', _SESSION)
    assert forgetask.head_advice('pr/x', None) == (said,), 'the process environment is the default'


def test_dev_lab_binds_nothing_so_its_venv_cannot_block_a_prompt() -> None:
    """Rem owns the binding (its UserPromptSubmit hook, node only): dev-lab wires no binder and only reads.

    The 2026-11-16 incident: a stale venv's binder refused its own verb, and every prompt of every session failed.
    No dev-lab prompt row binds now, and the reader has no command line to go stale.
    """
    binders = [wire.name for wire in agent_wiring.WIRING if wire.module == taskbinding.__name__]
    assert binders == []
    names = module_names(taskbinding)
    assert 'head_for' in names, 'planted control: the reader the module keeps is found'
    assert not {'bind', 'main'} & names
    assert "rem's UserPromptSubmit hook" in taskbinding.DOOR


_FIXTURE = Path(__file__).parent / '_rem_fixtures' / 'session-binding.json'


def test_the_cross_language_fixture_is_the_path_and_record_rem_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D34: rem (node) and dev-lab (python) assert one fixture, byte-identical in both repos.

    The path is the machine home's (lab_commons.home) ``state/sessions/<session>.json``; the record
    names its task and the ledger that task lives in; the repo key is lab_commons.repostate's rule.
    """
    fixture = json.loads(_FIXTURE.read_text(encoding='utf-8'))
    session = fixture['session']
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    assert taskbinding.binding_path(session) == tmp_path / 'home' / fixture['relative_path']
    assert repo_key(fixture['common_dir'], caseless=fixture['caseless']) == fixture['repo_key']
    assert fixture['record']['ledger']['repo_key'] == fixture['repo_key']
    assert taskbinding.binding(session) is None, 'planted control: nothing written yet'
    path = taskbinding.binding_path(session)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(fixture['record']), encoding='utf-8')
    found = taskbinding.binding(session)
    assert found == taskbinding.Binding('toolchain@a1', Path(fixture['record']['ledger']['path']), path)
    assert taskbinding.binding('another-session') is None, 'a binding is keyed by its own session'
