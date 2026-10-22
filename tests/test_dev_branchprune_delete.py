"""LOSSLESS-DELETE: an agent deletes an origin branch only when every commit on it lives somewhere else.

Real git (a bare ``origin`` and a clone, the real fetch and the real leased ``push --delete``) and the stateful
fake forge for the open PRs. The evidence is what ``origin`` holds afterwards. PLANTED CONTROL: the one branch with
a commit of its own is refused and survives, beside the contained ones that go.
"""

from __future__ import annotations

from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.branchprune import delete
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.hooks import DENY_RULES, denies, rules_by_id

SESSION = 'session_aaaabbbbcccc'


def _on_origin(work: Path, branch: str) -> bool:
    return bool(git_out(work, 'ls-remote', '--heads', 'origin', branch))


def _delete(work: Path, forge: StateForge, *branches: str) -> tuple[int, list[str], list[object]]:
    said: list[str] = []
    alarms: list[object] = []
    code = delete(
        work, branches, client=forge, session=SESSION, fetch=fetch_origin, say=said.append, alarm=alarms.append
    )
    return code, said, alarms


def _branch_at(work: Path, branch: str, sha: str) -> None:
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{sha}:refs/heads/{branch}')


def test_a_branch_contained_in_integration_is_deleted_naming_it(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    _branch_at(work, 'feat/done', tip)
    code, said, alarms = _delete(work, StateForge(), 'feat/done')
    assert code == 0
    assert not _on_origin(work, 'feat/done')
    assert any('every commit is on integrate/main' in line for line in said)
    assert any(SESSION in line for line in said), 'the record names the session'
    assert len(alarms) == 1


def test_a_branch_contained_in_an_open_pr_head_is_deleted_naming_the_pr(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    old = advance(work, 'pr/x', 'x.txt', 'x\n')
    advance(work, 'pr/x', 'y.txt', 'y\n')
    _branch_at(work, 'lane/old', old)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main')
    code, said, _ = _delete(work, forge, 'lane/old')
    assert code == 0
    assert not _on_origin(work, 'lane/old')
    assert any(f'open PR #{number} (pr/x)' in line for line in said)


def test_a_branch_with_a_commit_of_its_own_is_refused_naming_it(tmp_path: Path) -> None:
    """PLANTED control: beside it a contained branch is deleted, so the refusal is the commit, not the door."""
    _, work = clone_pair(tmp_path)
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    _branch_at(work, 'feat/done', tip)
    unique = advance(work, 'lane/mine', 'm.txt', 'm\n')
    code, said, _ = _delete(work, StateForge(), 'lane/mine', 'feat/done')
    assert code == 1
    assert _on_origin(work, 'lane/mine')
    assert not _on_origin(work, 'feat/done')
    assert any(f'1 commit(s) exist on it alone: {unique[:12]}' in line for line in said)


def test_an_open_pr_head_and_the_integration_branch_are_never_deleted(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/x', 'x.txt', 'x\n')
    forge = StateForge()
    forge.add_pull('pr/x', 'integrate/main')
    code, said, _ = _delete(work, forge, 'pr/x', 'integrate/main')
    assert code == 1
    assert _on_origin(work, 'pr/x')
    assert _on_origin(work, 'integrate/main')
    assert len([line for line in said if 'never deleted' in line]) == 2


def test_a_raw_remote_delete_is_still_refused_and_its_remedy_names_the_door() -> None:
    """PLANTED control: the door's own invocation is permitted."""
    assert denies(DENY_RULES, 'git -C ../sib push origin --delete lane/x') == 'PUSH-REMOTE-DELETE'
    assert denies(DENY_RULES, 'sh scripts/hooks/with-retry.sh push origin :lane/x') == 'PUSH-REMOTE-DELETE'
    assert 'dev_lab.dev.branchprune delete' in str(rules_by_id(DENY_RULES)['PUSH-REMOTE-DELETE'].remedy)
    assert denies(DENY_RULES, '.venv/Scripts/python.exe -m dev_lab.dev.branchprune delete lane/x') is None
