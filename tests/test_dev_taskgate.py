"""SESSION-COMMITS-UNDER-ITS-TASK: an opt-in repo refuses an agent push off the task its user bound through rem."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from _rem_binding import bind_as_rem, plant_claude_rem

from dev_lab.dev import taskbinding, taskgate
from dev_lab.dev.githooks.table import base_rows

SESSION_ENV = 'CLAUDE_CODE_SESSION_ID'

AGENT = {SESSION_ENV: '1d9000bd-6cd0-42ab-873f-102cd963e53d'}
_SESSION = AGENT[SESSION_ENV]
_GIT = shutil.which('git') or 'git'


@pytest.fixture(autouse=True)
def _current_rem(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every gate here reads a home whose Claude Code runs a current rem: the door is the user's `task:` prompt.

    The binder skew (rem absent, disabled or old) has its own planted cases in test_dev_remplugin.py.
    """
    home = tmp_path_factory.mktemp('home')
    plant_claude_rem(home, '2.6.0')
    for key in ('HOME', 'USERPROFILE'):
        monkeypatch.setenv(key, str(home))
    for key in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME'):
        monkeypatch.delenv(key, raising=False)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=', *args],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=True, timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def _repo(tmp_path: Path, *, required: bool) -> Path:
    """A git checkout whose pyproject does or does not require a task, holding the open tasks `toolchain`, `other`."""
    root = tmp_path / 'repo'
    root.mkdir(parents=True, exist_ok=True)
    table = '[tool.dev_lab.task]\nrequired = true\n' if required else '[project]\nname = "x"\n'
    (root / 'pyproject.toml').write_text(table, encoding='utf-8')
    for slug in ('toolchain', 'other'):
        folder = root / '.claude' / 'tasks' / slug
        folder.mkdir(parents=True, exist_ok=True)
        head = f'---\nname: {slug}\nkind: task\nauthority: a1\nstatus: open\n---\n'
        (folder / 'TASK.md').write_text(head, encoding='utf-8')
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'chore: seed')
    return root


def _bind(root: Path, slug: str = 'toolchain') -> str:
    """The USER's `task: <slug>` prompt binds the session through rem -- the one record the gate reads."""
    return bind_as_rem(root, _SESSION, slug)


class _Rem:
    """A fake rem task CLI: answers ``log`` and ``show``; records every call."""

    def __init__(self, journal: str = '', status: int = 0) -> None:
        self.journal, self.status = journal, status
        self.calls: list[list[str]] = []

    def __call__(self, root: Path, args: Sequence[str]) -> tuple[int, str]:
        del root
        self.calls.append(list(args))
        if self.status:
            return self.status, 'boom'
        return 0, {'show': self.journal}.get(args[0], 'logged')


def test_an_unbound_session_is_refused_naming_rems_door(tmp_path: Path) -> None:
    said = taskgate.refusal(_repo(tmp_path, required=True), env=AGENT, branch='pr/toolchain/a')
    assert said is not None
    assert taskgate.RULE in said
    assert '`task: <slug>`' in said
    assert "rem's UserPromptSubmit hook" in said
    assert '/rem:task open' in said


def test_the_gate_is_one_pre_push_row_and_no_commit_is_judged() -> None:
    """In-session work is rem's PreToolUse guard; the git side judges a push once, never a commit."""
    gate = 'dev_lab.dev.taskgate'
    found = [(stage, row['id']) for stage, rows in base_rows().items() for row in rows if gate in row['run']]
    assert found == [('pre-push', taskgate.HOOK_ID)]


def test_a_binding_rem_wrote_is_read_at_pre_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The file rem's `task: <slug>` hook writes is the whole input: no binder wiring, no dev-lab prompt hook."""
    root = _repo(tmp_path, required=True)
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/a')
    monkeypatch.chdir(root)
    monkeypatch.setenv(SESSION_ENV, _SESSION)
    assert taskgate.main([]) == 1, 'planted control: unbound, the push is refused'
    binding = taskbinding.ledger(root) / taskbinding.BINDINGS / f'{_SESSION}.json'
    binding.parent.mkdir(parents=True)
    binding.write_text(f'{{"session": "{_SESSION}", "task": "toolchain@a1"}}', encoding='utf-8')  # rem's bytes
    assert taskgate.main([]) == 0


def test_a_branch_named_after_a_task_binds_nothing(tmp_path: Path) -> None:
    """The retired guess: a tree or branch an agent names after a task is not the user's word."""
    root = _repo(tmp_path, required=True)
    _git(root, 'checkout', '-q', '-b', 'toolchain')
    assert taskgate.refusal(root, env=AGENT) is not None
    _bind(root)
    assert taskgate.refusal(root, env=AGENT) is None, 'planted control: the user binds'


def test_a_bound_session_keeps_its_task_across_a_landed_pr(tmp_path: Path) -> None:
    """D5: pr/<task>/a commits, lands, and pr/<task>/b commits -- no task change, no new binding."""
    root = _repo(tmp_path, required=True)
    assert _bind(root) == 'toolchain@a1'
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/a')
    assert taskgate.refusal(root, env=AGENT) is None
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'feat: a')
    _git(root, 'checkout', '-q', 'main')
    _git(root, 'merge', '-q', '--no-ff', '-m', 'Merge pr/toolchain/a', 'pr/toolchain/a')  # a's PR landed
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/b')
    assert taskgate.refusal(root, env=AGENT) is None


@pytest.mark.parametrize('branch', ['pr/other/a', 'pr/toolchain', 'pr/a'])
def test_a_pr_branch_outside_the_bound_task_is_refused_naming_it(tmp_path: Path, branch: str) -> None:
    root = _repo(tmp_path, required=True)
    _bind(root)
    said = taskgate.refusal(root, env=AGENT, branch=branch)
    assert said is not None
    assert 'bound to task toolchain@a1' in said
    assert f'git branch -m {branch} pr/toolchain/' in said
    assert taskgate.refusal(root, env=AGENT, branch='pr/toolchain/a') is None, 'planted control: its own head'


def test_local_fan_out_and_a_detached_tip_are_not_pr_heads(tmp_path: Path) -> None:
    root = _repo(tmp_path, required=True)
    _bind(root)
    assert taskgate.refusal(root, env=AGENT, branch='lane/x') is None
    _git(root, 'checkout', '-q', '--detach')
    assert taskgate.refusal(root, env=AGENT) is None


def test_a_binding_to_a_task_closed_since_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, required=True)
    _bind(root)
    task = root / '.claude' / 'tasks' / 'toolchain' / 'TASK.md'
    task.write_text(task.read_text(encoding='utf-8').replace('status: open', 'status: closed'), encoding='utf-8')
    said = taskgate.refusal(root, env=AGENT, branch='pr/toolchain/a')
    assert said is not None
    assert 'no longer open' in said


def test_a_repo_that_does_not_declare_it_is_never_judged(tmp_path: Path) -> None:
    assert taskgate.refusal(_repo(tmp_path, required=False), env=AGENT, branch='pr/x') is None


def test_a_human_commit_is_not_judged(tmp_path: Path) -> None:
    assert taskgate.refusal(_repo(tmp_path, required=True), env={}, branch='pr/x') is None


def test_the_hook_row_refuses_an_unbound_agent_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path, required=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv(SESSION_ENV, _SESSION)
    assert taskgate.main([]) == 1
    _bind(root)
    assert taskgate.main([]) == 0, 'planted control: bound, on main (not a pr/ head)'


def test_a_missing_rem_cli_is_an_unreadable_ledger(tmp_path: Path) -> None:
    read = taskgate.reader_for({taskgate.REM_ENV: str(tmp_path / 'absent.js')}, tmp_path)
    with pytest.raises(taskgate.TaskUnreadable, match=taskgate.REM_ENV):
        read(tmp_path, ['show', 'toolchain'])


def test_an_opened_pr_is_appended_through_rems_log_verb_to_the_bound_task(tmp_path: Path) -> None:
    rem = _Rem()
    url = 'https://forge.example/o/r/pulls/12'
    root = _repo(tmp_path, required=True)
    assert taskgate.record(root, 'pr', url, env=AGENT, read=rem) is None, 'planted control: unbound, nothing logged'
    assert rem.calls == []
    _bind(root)
    taskgate.record(root, 'pr', url, env=AGENT, read=rem)
    assert rem.calls[-1] == ['log', f'pr opened: {url}', '--task', 'toolchain']


def test_nothing_is_recorded_when_the_repo_does_not_require_a_task(tmp_path: Path) -> None:
    rem = _Rem()
    root = _repo(tmp_path, required=False)
    _bind(root)
    assert taskgate.record(root, 'pr', 'u', env=AGENT, read=rem) is None
    assert rem.calls == []


def test_the_task_watches_every_pr_its_journal_records_once(tmp_path: Path) -> None:
    journal = (
        '- 2026-11-14 progress: pr opened: https://forge.example/o/r/pulls/12\n'
        '- 2026-11-14 progress: issue opened: https://forge.example/o/r/issues/7\n'
        '- 2026-11-14 progress: pr opened: https://forge.example/o/r/pulls/13\n'
        '- 2026-11-14 progress: pr opened: https://forge.example/o/r/pulls/12\n'
    )
    assert taskgate.task_prs(tmp_path, 'toolchain', _Rem(journal=journal)) == (12, 13)


def test_an_unreadable_journal_raises(tmp_path: Path) -> None:
    with pytest.raises(taskgate.TaskUnreadable):
        taskgate.task_prs(tmp_path, 'toolchain', _Rem(status=1))


class _Forge:
    def pr_view(self, number: int) -> object:
        return type('Pr', (), {'head_sha': f'sha{number}'})()


def test_watch_by_task_watches_the_head_of_every_recorded_pr() -> None:
    journal = 'pr opened: https://forge.example/o/r/pulls/12\npr opened: https://forge.example/o/r/pulls/13\n'
    argv = taskgate.watch_argv(['--task', 'toolchain', '--stream'], _Forge, read=_Rem(journal=journal))
    assert argv == ['sha12', 'sha13', '--stream']


def test_watch_by_a_task_with_no_recorded_pr_refuses() -> None:
    """The control: an empty journal is a named refusal, never a watch of nothing."""
    with pytest.raises(taskgate.TaskUnreadable, match='no open PR head'):
        taskgate.watch_argv(['--task', 'toolchain'], _Forge, read=_Rem())


def test_a_task_opened_in_one_worktree_is_bound_journaled_and_admitted_from_another(tmp_path: Path) -> None:
    """W4: the ledger and the binding are REPO state -- one directory, reached the same way from every worktree.

    PLANTED CONTROLS: an unbound session is still refused from either tree, and a closed task is refused everywhere.
    """
    main = _repo(tmp_path, required=True)
    tree_a, tree_b = tmp_path / 'a', tmp_path / 'b'
    _git(main, 'worktree', 'add', '-q', '-b', 'pr/toolchain/a', str(tree_a))
    _git(main, 'worktree', 'add', '-q', '-b', 'pr/toolchain/b', str(tree_b))
    ledger = taskbinding.ledger(main)
    assert taskbinding.ledger(tree_a) == taskbinding.ledger(tree_b) == ledger
    (ledger / 'opened-in-a').mkdir()  # what rem's /rem:task open writes from tree A: the one ledger
    (ledger / 'opened-in-a' / 'TASK.md').write_text('---\nauthority: a9\nstatus: open\n---\n', encoding='utf-8')
    other = {SESSION_ENV: 'second-session-0001'}
    assert taskgate.refusal(tree_b, env=other, branch='pr/opened-in-a/x') is not None
    assert bind_as_rem(tree_b, other[SESSION_ENV], 'opened-in-a') == 'opened-in-a@a9'
    assert (ledger / taskbinding.BINDINGS / 'second-session-0001.json').is_file()
    for tree in (tree_a, tree_b, main):
        assert taskbinding.session_task(other, start=tree) == 'opened-in-a@a9'
        assert taskgate.refusal(tree, env=other, branch='pr/opened-in-a/x') is None
    rem = _Rem()
    taskgate.record(tree_a, 'pr', 'u', env=other, read=rem)
    assert rem.calls[-1] == ['log', 'pr opened: u', '--task', 'opened-in-a']
    assert taskgate.refusal(tree_a, env=AGENT, branch='pr/toolchain/a') is not None, 'an unbound session'
    task = ledger / 'opened-in-a' / 'TASK.md'
    task.write_text(task.read_text(encoding='utf-8').replace('open', 'closed'), encoding='utf-8')
    for tree in (tree_a, tree_b, main):
        assert 'no longer open' in (taskgate.refusal(tree, env=other, branch='pr/opened-in-a/x') or '')
