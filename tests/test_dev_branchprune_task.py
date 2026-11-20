"""A closed task prunes its branches (user ruling D25): ``branchprune task <slug>`` deletes its ``pr/<slug>/*`` heads.

Real git (a bare ``origin`` and a clone, the real fetch and the real leased ``push --delete``) and the stateful fake
forge for the open PRs. PLANTED CONTROLS: a head with an open PR and a head with unlanded content are kept and
named beside landed ones that go, and another task's head is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.branchdelete import delete_task
from dev_lab.dev.forge import fetch_origin


def _on_origin(work: Path, branch: str) -> bool:
    return bool(git_out(work, 'ls-remote', '--heads', 'origin', branch))


def _prune(work: Path, forge: StateForge, slug: str) -> tuple[int, list[str]]:
    said: list[str] = []
    code = delete_task(
        work, slug, client=forge, session='s', fetch=fetch_origin, say=said.append, alarm=lambda _a: None
    )
    return code, said


def _landed_heads(work: Path, *branches: str) -> None:
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    for branch in branches:
        run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/{branch}')


def test_a_task_with_two_landed_heads_prunes_both_and_no_other_tasks(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    _landed_heads(work, 'pr/alpha/one', 'pr/alpha/two', 'pr/alphabet/x')
    code, said = _prune(work, StateForge(), 'alpha')
    assert code == 0, said
    assert not _on_origin(work, 'pr/alpha/one')
    assert not _on_origin(work, 'pr/alpha/two')
    assert _on_origin(work, 'pr/alphabet/x'), 'another task shares only a prefix'
    assert said[-1] == 'task alpha: 2 of 2 head(s) pruned'


def test_a_head_with_an_open_pr_or_unlanded_content_is_kept_and_named(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    _landed_heads(work, 'pr/alpha/done', 'pr/alpha/open')
    advance(work, 'pr/alpha/mine', 'm.txt', 'm\n')
    forge = StateForge()
    forge.add_pull('pr/alpha/open', 'integrate/main')
    code, said = _prune(work, forge, 'alpha')
    assert code == 1
    assert not _on_origin(work, 'pr/alpha/done')
    assert _on_origin(work, 'pr/alpha/open')
    assert _on_origin(work, 'pr/alpha/mine')
    assert any('pr/alpha/open: refused' in line for line in said), said
    assert any('pr/alpha/mine: refused' in line and 'm.txt' in line for line in said), said
    assert said[-1] == 'task alpha: 1 of 3 head(s) pruned; kept: pr/alpha/mine, pr/alpha/open'


def test_a_task_with_no_heads_prunes_nothing(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    code, said = _prune(work, StateForge(), 'alpha')
    assert code == 0
    assert said == ['task alpha: no pr/alpha/* head on origin']


@pytest.mark.parametrize('slug', ['', 'a/b', 'a*', '*'])
def test_a_slug_that_is_not_one_segment_is_refused_before_any_fetch(tmp_path: Path, slug: str) -> None:
    def fetch(_root: Path) -> None:
        msg = 'fetched'
        raise AssertionError(msg)

    with pytest.raises(ValueError, match='not a task slug'):
        delete_task(tmp_path, slug, client=StateForge(), session='s', fetch=fetch, say=print)
