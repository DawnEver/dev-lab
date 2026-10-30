"""LOSSLESS-DELETE: an agent deletes an origin branch only when its commits or its content live elsewhere.

Real git (a bare ``origin`` and a clone, the real fetch and the real leased ``push --delete``) and the stateful
fake forge for the open PRs. The evidence is what ``origin`` holds afterwards. PLANTED CONTROL: the one branch with
a commit of its own is refused and survives, beside the contained ones that go.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.branchdelete import delete
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
    assert any('held by integrate/main' in line for line in said)
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
    assert any(
        f'1 commit(s) exist on it alone ({unique[:12]}), with unlanded content in: m.txt' in line for line in said
    )


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


def _sync_merge(work: Path, branch: str, extra: tuple[str, str] | None = None) -> str:
    """Merge origin's integrate/main into origin's *branch* (optionally committing *extra* in the merge); push."""
    run_git(work, 'checkout', '-q', '-B', 'tmp-sync', f'origin/{branch}')
    run_git(work, 'merge', '-q', '--no-ff', '--no-commit', 'origin/integrate/main')
    if extra:
        name, text = extra
        (work / name).write_text(text, encoding='utf-8')
        run_git(work, 'add', name)
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', 'sync')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    return git_out(work, 'rev-parse', 'HEAD')


def _landed(work: Path, branch: str) -> None:
    """Integration takes *branch*'s content as a new commit of its own (a squash), so ancestry never holds it."""
    run_git(work, 'checkout', '-q', '-B', 'tmp-land', 'origin/integrate/main')
    run_git(work, 'merge', '-q', '--squash', f'origin/{branch}')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', 'land')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/integrate/main')
    run_git(work, 'fetch', '-q', 'origin')


def test_a_branch_of_only_sync_merges_with_integrations_tree_is_deleted(tmp_path: Path) -> None:
    """Its commits are on it alone, but its tree adds nothing integration lacks."""
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/relock', 'r.txt', 'r\n')
    _landed(work, 'pr/relock')
    _sync_merge(work, 'pr/relock')
    code, said, _ = _delete(work, StateForge(), 'pr/relock')
    assert code == 0, said
    assert not _on_origin(work, 'pr/relock')
    assert any('no content integrate/main lacks' in line for line in said)


def test_a_branch_differing_from_integration_only_in_a_generated_file_is_deleted(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/relock', 'uv.lock', 'old\n')
    _landed(work, 'pr/relock')
    _sync_merge(work, 'pr/relock', extra=('uv.lock', 'regenerated\n'))
    code, said, _ = _delete(work, StateForge(), 'pr/relock')
    assert code == 0, said
    assert not _on_origin(work, 'pr/relock')


def test_a_branch_with_one_unlanded_line_is_refused_naming_its_file(tmp_path: Path) -> None:
    """PLANTED control: the same shape as the two deleted above, plus one line integration lacks."""
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/relock', 'r.txt', 'r\n')
    _landed(work, 'pr/relock')
    _sync_merge(work, 'pr/relock', extra=('src.py', 'unlanded = 1\n'))
    code, said, _ = _delete(work, StateForge(), 'pr/relock')
    assert code == 1
    assert _on_origin(work, 'pr/relock')
    assert any('unlanded content in: src.py' in line for line in said), said


def _own_commit(work: Path, branch: str, change: Callable[[Path], None]) -> None:
    """One commit of *branch*'s own applying *change* to the clone's tree; pushed."""
    start = f'origin/{branch}' if git_out(work, 'branch', '-r', '--list', f'origin/{branch}') else 'origin/main'
    run_git(work, 'checkout', '-q', '-B', 'tmp-own', start)
    change(work)
    run_git(work, 'add', '-A', '--', '.')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', 'own')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')


def _refused_naming(work: Path, branch: str, path: str) -> None:
    code, said, _ = _delete(work, StateForge(), branch)
    assert code == 1, said
    assert _on_origin(work, branch)
    assert any(f'unlanded content in: {path}' in line for line in said), said


def test_a_non_ascii_path_is_refused_naming_it(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/x', 'base2.txt', 'b\n')
    _landed(work, 'pr/x')
    (work / 'docs').mkdir(exist_ok=True)
    _own_commit(work, 'pr/x', lambda w: (w / 'docs' / 'café.md').write_text('c\n', encoding='utf-8'))
    _refused_naming(work, 'pr/x', 'docs/café.md')


def test_an_empty_new_file_is_refused(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    _own_commit(work, 'pr/x', lambda w: (w / 'empty.txt').write_text('', encoding='utf-8'))
    _refused_naming(work, 'pr/x', 'empty.txt')


def test_a_mode_only_change_is_refused(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    run_git(work, 'config', 'core.filemode', 'false')
    run_git(work, 'checkout', '-q', '-B', 'tmp-own', 'origin/main')
    run_git(work, 'update-index', '--chmod=+x', 'base.txt')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', 'chmod')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/x')
    run_git(work, 'fetch', '-q', 'origin')
    _refused_naming(work, 'pr/x', 'base.txt')


def test_a_line_deletion_is_refused(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    advance(work, 'integrate/main', 'two.txt', 'one\ntwo\n')
    run_git(work, 'checkout', '-q', '-B', 'tmp-own', 'origin/integrate/main')
    (work / 'two.txt').write_text('one\n', encoding='utf-8')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-am', 'drop')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/x')
    run_git(work, 'fetch', '-q', 'origin')
    _refused_naming(work, 'pr/x', 'two.txt')
