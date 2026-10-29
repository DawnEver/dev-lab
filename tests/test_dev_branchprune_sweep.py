"""LANDED-BRANCHES-SWEPT: after integration moves, every branch it now contains is deleted -- and nothing else.

User ruling 2026-10-29. Real git (a bare ``origin``, a clone, the real fetch, the real leased ``push --delete``)
and the stateful fake forge for the PRs; the evidence is what ``origin`` and the clone hold afterwards. PLANTED
CONTROLS: beside the landed branches that go, an unlanded branch, an unlanded open PR head, a declared session
branch, a busy local branch and an unlanded local branch all survive.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.branchprune import DELETED_EVENT, post_push, sweep
from dev_lab.dev.forge import fetch_origin

SESSION = 'session_aaaabbbbcccc'

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.dev_lab.branchset]
trunk = "main"
sessions = ["session/keep"]
ephemeral = ["pr/*"]

[tool.dev_lab.integrator]
integration = "integrate/main"
"""


def _repo(tmp_path: Path) -> Path:
    _, work = clone_pair(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    return work


def _on_origin(work: Path, branch: str) -> bool:
    return bool(git_out(work, 'ls-remote', '--heads', 'origin', branch))


def _local(work: Path, branch: str) -> bool:
    return bool(git_out(work, 'branch', '--list', branch))


def _sweep(work: Path, forge: StateForge, *, local: bool = False) -> tuple[int, list[str], list[object]]:
    said: list[str] = []
    alarms: list[object] = []
    code = sweep(
        work, client=forge, session=SESSION, fetch=fetch_origin, say=said.append, alarm=alarms.append, local=local
    )
    return code, said, alarms


def _squash_landed(work: Path, branch: str) -> str:
    """*branch* gets a file, integration takes it as a squash, *branch* syncs integration back in: its new tip."""
    advance(work, branch, f'{branch.replace("/", "-")}.txt', 'work\n')
    run_git(work, 'checkout', '-q', '-B', 'tmp-land', 'origin/integrate/main')
    run_git(work, 'merge', '-q', '--squash', f'origin/{branch}')
    run_git(work, 'commit', '-q', '--no-verify', '-m', 'land')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/integrate/main')
    run_git(work, 'checkout', '-q', '-B', 'tmp-sync', f'origin/{branch}')
    run_git(work, 'merge', '-q', '--no-ff', '--no-verify', '-m', 'sync', 'tmp-land')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    run_git(work, 'checkout', '-q', '--detach', 'origin/main')
    return git_out(work, 'rev-parse', f'origin/{branch}')


def test_landed_branches_are_deleted_and_every_other_branch_survives(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/feat/done')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/session/keep')
    squashed = _squash_landed(work, 'pr/squashed')
    advance(work, 'lane/mine', 'm.txt', 'm\n')
    opened = advance(work, 'pr/open', 'o.txt', 'o\n')
    forge = StateForge()
    number = forge.add_pull('pr/open', 'integrate/main', sha=opened)
    code, said, alarms = _sweep(work, forge)
    assert code == 0, said
    assert not _on_origin(work, 'feat/done')
    assert not _on_origin(work, 'pr/squashed'), 'content-landed under a different sha'
    assert squashed != git_out(work, 'rev-parse', 'origin/integrate/main')
    for kept in ('lane/mine', 'pr/open', 'session/keep', 'integrate/main', 'main'):
        assert _on_origin(work, kept), kept
    assert forge.pulls[number]['state'] == 'open'
    assert any('lane/mine' in line and 'm.txt' in line for line in said), said
    deleted = [json.loads(line)['ref'] for line in said if DELETED_EVENT in line]
    assert sorted(deleted) == ['feat/done', 'pr/squashed']
    assert len(alarms) == 1


def test_a_landed_open_pr_is_closed_and_its_head_deleted(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    head = _squash_landed(work, 'pr/landed')
    forge = StateForge()
    number = forge.add_pull('pr/landed', 'integrate/main', sha=head)
    code, said, _ = _sweep(work, forge)
    assert code == 0, said
    assert forge.pulls[number]['state'] == 'closed'
    assert not _on_origin(work, 'pr/landed')


def test_a_second_sweep_does_nothing(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/feat/done')
    _sweep(work, StateForge())
    code, said, alarms = _sweep(work, StateForge())
    assert code == 0
    assert not [line for line in said if DELETED_EVENT in line]
    assert alarms == []


def test_local_landed_branches_go_and_busy_or_unlanded_ones_stay(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    squashed = _squash_landed(work, 'pr/squashed')
    run_git(work, 'branch', 'pr/squashed', squashed)
    run_git(work, 'branch', 'feat/busy', 'origin/integrate/main')
    tree = tmp_path / 'busy-tree'
    run_git(work, 'worktree', 'add', '-q', str(tree), 'feat/busy')
    run_git(work, 'checkout', '-q', '-b', 'lane/local', 'origin/main')
    (work / 'l.txt').write_text('l\n', encoding='utf-8')
    run_git(work, 'add', 'l.txt')
    run_git(work, 'commit', '-q', '--no-verify', '-m', 'l')
    run_git(work, 'checkout', '-q', '--detach', 'origin/main')
    code, said, _ = _sweep(work, StateForge(), local=True)
    assert code == 0, said
    assert not _local(work, 'pr/squashed'), said
    assert _local(work, 'feat/busy'), 'checked out in a worktree'
    assert tree.is_dir(), 'a worktree touched within the quiet window is a live lease'
    assert _local(work, 'lane/local'), 'its commit is on no other ref'


def _payload(work: Path, command: str) -> io.StringIO:
    return io.StringIO(json.dumps({'cwd': str(work), 'tool_input': {'command': command}}))


def test_a_push_that_moved_integration_detaches_one_sweep_of_the_main_checkout(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    run_git(work, 'checkout', '-q', '-B', 'land', 'origin/integrate/main')
    (work / 'n.txt').write_text('n\n', encoding='utf-8')
    run_git(work, 'add', 'n.txt')
    run_git(work, 'commit', '-q', '--no-verify', '-m', 'n')
    command = 'sh scripts/hooks/with-retry.sh push origin land:integrate/main'
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'land:integrate/main')
    started: list[Path] = []
    assert post_push([], stdin=_payload(work, command), detach=started.append) == 0
    assert started == [work.resolve()]


def test_a_push_of_another_branch_or_a_fetch_detaches_nothing(tmp_path: Path) -> None:
    """PLANTED control: integration moved by a FETCH, then a push of a PR head -- neither is an integration push."""
    work = _repo(tmp_path)
    advance(work, 'integrate/main', 'i.txt', 'i\n')  # its tracking ref moves by fetch after the push
    run_git(work, 'update-ref', 'refs/remotes/origin/integrate/main', 'origin/main')
    run_git(work, 'fetch', '-q', 'origin')
    advance(work, 'pr/x', 'x.txt', 'x\n')
    started: list[Path] = []
    assert post_push([], stdin=_payload(work, 'git push origin HEAD:pr/x'), detach=started.append) == 0
    assert post_push([], stdin=_payload(work, 'git status'), detach=started.append) == 0
    assert started == []
