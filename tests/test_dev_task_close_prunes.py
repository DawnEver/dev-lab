"""``task close <slug>`` prunes the task's MERGED branches and refuses while one is unmerged (user ruling 2026-11-24).

Real git (a bare ``origin`` and a clone) for the ``pr/<slug>/*`` heads, local and on origin; the stateful fake forge
for the open PRs; conftest's isolated machine home for the ledger. PLANTED CONTROLS: an unmerged head (origin or local
only) blocks the close and is listed by name with its door, nothing written; once discarded the close runs and every
merged head -- origin and local -- is deleted, another task's head untouched.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge
from _task_ledger import plant_ledger

from dev_lab.dev import task, taskauthority
from dev_lab.dev._task_io import TaskRefused
from dev_lab.dev.branchdelete import TaskBranches
from dev_lab.dev.forge import fetch_origin

_DAY = '2026-11-24'


class _Issues:
    def open(self, slug: str, goal: str) -> str:
        del slug, goal
        return 'https://forge.example/t/tasks/issues/1'

    def close(self, url: str) -> None:
        del url


def _grant(verb: str, slug: str) -> None:
    payload = json.dumps({'prompt': f'/task {verb} {slug}', 'session_id': 's'})
    assert taskauthority.main(['hook'], stdin=io.StringIO(payload)) == 0


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't',
                       'GIT_COMMITTER_EMAIL': 't@x'}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    root = plant_ledger()
    _grant('open', 'alpha')
    task.open_task('alpha', 'prune on close', forge=_Issues(), date=_DAY)
    return root


def _heads(work: Path) -> set[str]:
    local = git_out(work, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/pr/')
    remote = git_out(work, 'ls-remote', '--heads', 'origin', 'refs/heads/pr/*')
    return {*local.split(), *(f'origin/{r.split()[1].removeprefix("refs/heads/")}' for r in remote.splitlines())}


def _landed(work: Path, *branches: str) -> None:
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    for branch in branches:
        run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    run_git(work, 'branch', '-q', 'pr/alpha/local-done', tip)
    run_git(work, 'checkout', '-q', 'main')


def _close(work: Path, said: list[str]) -> Path:
    branches = TaskBranches(work, client=StateForge(), session='s', fetch=fetch_origin, alarm=lambda _a: None)
    return task.close('alpha', 'done', cwd=work, forge=_Issues(), date=_DAY, branches=branches, say=said.append)


def test_merged_heads_are_deleted_on_close_and_no_other_tasks(ledger: Path, tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    _landed(work, 'pr/alpha/one', 'pr/alpha/two', 'pr/alphabet/x')
    _grant('close', 'alpha')
    said: list[str] = []
    dest = _close(work, said)
    assert dest == ledger / 'archive' / _DAY / 'alpha'
    assert _heads(work) == {'origin/pr/alphabet/x'}, said
    assert any('pr/alpha/local-done' in line and 'deleted' in line for line in said), said


def test_an_unmerged_head_blocks_the_close_and_is_listed(ledger: Path, tmp_path: Path) -> None:
    """PLANTED CONTROL: one unmerged head on origin, one only local -- both named, nothing written or deleted."""
    _, work = clone_pair(tmp_path)
    _landed(work, 'pr/alpha/done')
    advance(work, 'pr/alpha/wip', 'w.txt', 'w\n')
    run_git(work, 'checkout', '-q', '-b', 'pr/alpha/mine', 'origin/main')
    (work / 'm.txt').write_text('m\n', encoding='utf-8')
    run_git(work, 'add', 'm.txt')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'mine')
    run_git(work, 'checkout', '-q', 'main')
    before = _heads(work)
    _grant('close', 'alpha')
    with pytest.raises(TaskRefused) as refused:
        _close(work, [])
    said = str(refused.value)
    assert 'pr/alpha/wip' in said
    assert 'pr/alpha/mine' in said
    assert 'pr/alpha/done' not in said
    assert 'branchset --discard' in said
    assert 'branchprune delete' in said
    assert (ledger / 'alpha' / 'TASK.md').is_file(), 'the task stays open'
    assert _heads(work) == before, 'nothing was deleted'
    run_git(work, 'branch', '-q', '-D', 'pr/alpha/mine')  # discarded locally
    run_git(work, 'push', '-q', '--no-verify', 'origin', '--delete', 'pr/alpha/wip')  # discarded on origin
    _close(work, [])
    assert not {h for h in _heads(work) if '/alpha/' in h}
