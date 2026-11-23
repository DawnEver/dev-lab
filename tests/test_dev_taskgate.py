"""SESSION-COMMITS-UNDER-ITS-TASK: an opt-in repo refuses an agent push from a branch naming no open task."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from _task_ledger import open_task, plant_ledger

from dev_lab.dev import taskgate, walls
from dev_lab.dev.githooks.table import base_rows

SESSION_ENV = 'CLAUDE_CODE_SESSION_ID'

AGENT = {SESSION_ENV: '1d9000bd-6cd0-42ab-873f-102cd963e53d'}
_SESSION = AGENT[SESSION_ENV]
_GIT = shutil.which('git') or 'git'


@pytest.fixture
def ledger() -> Path:
    """The machine's one ledger, holding the open tasks ``toolchain`` and ``other``."""
    found = plant_ledger()
    for slug in ('toolchain', 'other'):
        open_task(found, slug)
    return found


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=', *args],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=True, timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def _repo(tmp_path: Path, *, required: bool, branch: str = 'main') -> Path:
    """A git checkout whose pyproject does or does not require a task, on *branch*."""
    root = tmp_path / 'repo'
    root.mkdir(parents=True, exist_ok=True)
    table = '[tool.dev_lab.task]\nrequired = true\n' if required else '[project]\nname = "x"\n'
    (root / 'pyproject.toml').write_text(table, encoding='utf-8')
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'chore: seed')
    if branch != 'main':
        _git(root, 'checkout', '-q', '-b', branch)
    return root


def _close(ledger: Path, slug: str = 'toolchain') -> None:
    open_task(ledger, slug, status='closed')


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


def test_an_agent_on_no_task_branch_is_refused_naming_the_branch_door(tmp_path: Path, ledger: Path) -> None:
    del ledger
    said = taskgate.refusal(_repo(tmp_path, required=True), env=AGENT)
    assert said is not None
    assert taskgate.RULE in said
    assert 'main is none' in said, 'the refusal names the branch it judged'
    assert 'pr/<slug>/<feature>' in said
    assert '/rem:task open' in said


def test_the_gate_judges_every_commit_and_every_push_for_any_agent() -> None:
    """The git side is the agent-independent backstop: rem's PreToolUse guard exists only under Claude Code."""
    gate = 'dev_lab.dev.taskgate'
    found = sorted((stage, row['id']) for stage, rows in base_rows().items() for row in rows if gate in row['run'])
    assert found == [('commit-msg', taskgate.COMMIT_HOOK_ID), ('pre-push', taskgate.HOOK_ID)]


@pytest.mark.parametrize('native', ['CODEX_THREAD_ID', 'ANTIGRAVITY_CONVERSATION_ID'])
def test_a_codex_or_agy_session_is_judged_like_a_claude_one(tmp_path: Path, ledger: Path, native: str) -> None:
    """Planted control: the same repo passes a human (no session) and refuses each agent's session."""
    del ledger
    root = _repo(tmp_path, required=True)
    assert taskgate.refusal(root, env={}) is None
    said = taskgate.refusal(root, env={native: _SESSION})
    assert said is not None
    assert taskgate.RULE in said


def test_the_branch_is_the_whole_input(tmp_path: Path, ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No binding store: the checkout's branch pr/<slug>/<feature> names the task, open in the one ledger."""
    del ledger
    root = _repo(tmp_path, required=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv(SESSION_ENV, _SESSION)
    assert taskgate.main([]) == 1, 'planted control: on main, the push is refused'
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/a')
    assert taskgate.main([]) == 0


def test_a_branch_naming_an_unknown_or_closed_task_is_refused(tmp_path: Path, ledger: Path) -> None:
    root = _repo(tmp_path, required=True, branch='pr/nosuch/a')
    unknown = taskgate.refusal(root, env=AGENT)
    assert unknown is not None
    assert 'does not hold open' in unknown
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/a')
    assert taskgate.refusal(root, env=AGENT) is None, 'planted control: an open task admits'
    _close(ledger)
    closed = taskgate.refusal(root, env=AGENT)
    assert closed is not None
    assert 'not open' in closed


def test_an_unresolved_ledger_is_refused_with_its_own_door(tmp_path: Path) -> None:
    """No ledger is cloned in this test's machine home: the gate passes the resolver's door through."""
    said = taskgate.refusal(_repo(tmp_path, required=True, branch='pr/toolchain/a'), env=AGENT)
    assert said is not None
    assert 'task ledger cannot be read' in said
    assert 'git clone' in said


def test_a_flat_branch_named_after_a_task_is_no_task(tmp_path: Path, ledger: Path) -> None:
    del ledger
    root = _repo(tmp_path, required=True, branch='toolchain')
    assert taskgate.refusal(root, env=AGENT) is not None
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/x')
    assert taskgate.refusal(root, env=AGENT) is None, 'planted control: the nested head names it'


def test_a_task_survives_a_landed_pr(tmp_path: Path, ledger: Path) -> None:
    """D5: pr/<task>/a commits, lands, and pr/<task>/b commits -- no task change."""
    del ledger
    root = _repo(tmp_path, required=True, branch='pr/toolchain/a')
    assert taskgate.refusal(root, env=AGENT) is None
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'feat: a')
    _git(root, 'checkout', '-q', 'main')
    _git(root, 'merge', '-q', '--no-ff', '-m', 'Merge pr/toolchain/a', 'pr/toolchain/a')
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/b')
    assert taskgate.refusal(root, env=AGENT) is None


def test_a_repo_that_does_not_declare_it_is_never_judged(tmp_path: Path, ledger: Path) -> None:
    del ledger
    assert taskgate.refusal(_repo(tmp_path, required=False), env=AGENT) is None


def test_a_human_commit_is_not_judged(tmp_path: Path, ledger: Path) -> None:
    del ledger
    assert taskgate.refusal(_repo(tmp_path, required=True), env={}) is None


def _every_refusal(tmp_path: Path, ledger: Path) -> dict[str, str | None]:
    """One text per refusal :func:`taskgate.refusal` can give, each produced by its real cause."""
    said: dict[str, str | None] = {}
    said['no task branch'] = taskgate.refusal(_repo(tmp_path / 'main', required=True), env=AGENT)
    said['session unreadable'] = taskgate.refusal(_repo(tmp_path / 'blank', required=True), env={SESSION_ENV: ''})
    said['unknown task'] = taskgate.refusal(_repo(tmp_path / 'unknown', required=True, branch='pr/no/a'), env=AGENT)
    closed = _repo(tmp_path / 'closed', required=True, branch='pr/toolchain/a')
    _close(ledger)
    said['task closed'] = taskgate.refusal(closed, env=AGENT)
    return said


def test_every_refusal_puts_its_door_on_a_line_of_its_own(tmp_path: Path, ledger: Path) -> None:
    """MEASURED 2026-11-17: a door on the cause's own line is recorded ``remedy_present: false``.

    PLANTED CONTROL: the same text folded back onto one line names no door.
    """
    said = _every_refusal(tmp_path, ledger)
    assert all(text is not None and text.startswith(f'{taskgate.RULE}:') for text in said.values()), said
    assert {name for name, text in said.items() if not walls.has_remedy(text or '')} == set()
    assert {name for name, text in said.items() if walls.has_remedy(' '.join((text or '').splitlines()))} == set()


def test_a_missing_rem_cli_is_an_unreadable_ledger(tmp_path: Path) -> None:
    read = taskgate.reader_for({taskgate.REM_ENV: str(tmp_path / 'absent.js')}, tmp_path)
    with pytest.raises(taskgate.TaskUnreadable, match=taskgate.REM_ENV):
        read(tmp_path, ['show', 'toolchain'])


def test_an_opened_pr_is_appended_through_rems_log_verb_to_the_branchs_task(tmp_path: Path, ledger: Path) -> None:
    del ledger
    rem = _Rem()
    url = 'https://forge.example/o/r/pulls/12'
    root = _repo(tmp_path, required=True)
    assert taskgate.record(root, 'pr', url, read=rem) is None, 'planted control: no task branch, nothing logged'
    assert rem.calls == []
    _git(root, 'checkout', '-q', '-b', 'pr/toolchain/a')
    taskgate.record(root, 'pr', url, read=rem)
    assert rem.calls[-1] == ['log', f'pr opened: {url}', '--task', 'toolchain']


def test_nothing_is_recorded_when_the_repo_does_not_require_a_task(tmp_path: Path, ledger: Path) -> None:
    del ledger
    rem = _Rem()
    root = _repo(tmp_path, required=False, branch='pr/toolchain/a')
    assert taskgate.record(root, 'pr', 'u', read=rem) is None
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


def test_every_worktree_on_a_tasks_head_works_on_that_task(tmp_path: Path, ledger: Path) -> None:
    """One ledger per machine: two worktrees of one repo, each on a head of the task, both admitted.

    PLANTED CONTROLS: the main checkout (on main) is refused, and a closed task is refused in every tree.
    """
    main = _repo(tmp_path, required=True)
    tree_a, tree_b = tmp_path / 'a', tmp_path / 'b'
    _git(main, 'worktree', 'add', '-q', '-b', 'pr/toolchain/a', str(tree_a))
    _git(main, 'worktree', 'add', '-q', '-b', 'pr/toolchain/b', str(tree_b))
    assert taskgate.refusal(main, env=AGENT) is not None
    for tree in (tree_a, tree_b):
        assert taskgate.refusal(tree, env=AGENT) is None
    _close(ledger)
    for tree in (tree_a, tree_b):
        assert 'not open' in (taskgate.refusal(tree, env=AGENT) or '')
