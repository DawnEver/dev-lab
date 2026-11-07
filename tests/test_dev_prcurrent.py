"""PR-HEAD-IS-CURRENT (user ruling 2026-11-07): a pr/* head holds integration's tip and a fresh lock.

Real git (a bare origin and a clone); the network fetch and the lock resolution are planted seams. Every refusal
has its planted control: the same head, made current, passes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from _forge_state import StateForge

from dev_lab.dev.prcurrent import RULE, SYNC, behind, fetch_ref, lock_stale, ready_refusals, refusals
from dev_lab.dev.relock import BRANCH as RELOCK_BRANCH

_GIT = shutil.which('git') or 'git'
_DECL = (
    "[tool.dev_lab.branchset]\ntrunk = 'stable'\nsessions = ['int/line']\n\n"
    "[tool.dev_lab.integrator]\nintegration = 'int/line'\ntrunk = 'stable'\n"
)
_LAG = 'uv.lock is not the newest resolution: Update lab-commons v0.3.1 -> v0.3.2'
_ZERO = '0' * 40


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=', *args],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=True, timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def _fresh(_tree: Path) -> tuple[str, ...]:
    return ()


def _lagging(_tree: Path) -> tuple[str, ...]:
    return (_LAG,)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clone on ``pr/x`` cut from ``int/line``, after which ``int/line`` moved on origin."""
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--bare', '-b', 'stable', str(origin))
    work = tmp_path / 'work'
    _git(tmp_path, 'clone', str(origin), str(work))
    (work / 'pyproject.toml').write_text(_DECL, encoding='utf-8')
    _git(work, 'checkout', '-b', 'int/line')
    _git(work, 'add', '.')
    _git(work, 'commit', '-m', 'chore: seed')
    _git(work, 'branch', 'pr/x')
    _git(work, 'commit', '--allow-empty', '-m', 'chore: integration moves on')
    _git(work, 'push', 'origin', 'int/line')
    _git(work, 'checkout', 'pr/x')
    _git(work, 'commit', '--allow-empty', '-m', 'feat: x')
    return work


def _line(work: Path, branch: str = 'pr/x', sha: str | None = None) -> str:
    tip = sha or _git(work, 'rev-parse', 'HEAD')
    return f'refs/heads/{branch} {tip} refs/heads/{branch} {_ZERO}\n'


def test_a_head_behind_integration_is_refused_naming_sync_and_once_synced_passes(repo: Path) -> None:
    (why,) = refusals(repo, _line(repo), fetch=fetch_ref, read=_fresh)
    assert RULE in why
    assert 'does not contain origin/int/line' in why
    assert SYNC in why
    _git(repo, 'merge', '--no-edit', 'origin/int/line')
    assert refusals(repo, _line(repo), fetch=fetch_ref, read=_fresh) == [], 'PLANTED CONTROL: synced, it lands'


def test_the_behind_check_reads_origin_afresh_never_a_stale_remote_ref(repo: Path) -> None:
    """The local origin/int/line is rewound to the head's base: only the fetch shows the head is behind."""
    _git(repo, 'update-ref', 'refs/remotes/origin/int/line', 'pr/x~1')
    assert behind(repo, _git(repo, 'rev-parse', 'HEAD'), 'int/line') is not None


def test_a_failed_fetch_refuses_with_the_networks_reason(repo: Path) -> None:
    _git(repo, 'merge', '--no-edit', 'origin/int/line')
    (why,) = refusals(repo, _line(repo), fetch=lambda _root, _branch: 'forge unreachable', read=_fresh)
    assert 'could not be fetched' in why
    assert 'forge unreachable' in why


def test_a_lock_lagging_a_floated_head_is_refused_naming_sync_and_a_fresh_one_passes(repo: Path) -> None:
    sha = _git(repo, 'rev-parse', 'HEAD')
    why = lock_stale(repo, sha, read=_lagging)
    assert why is not None
    assert _LAG in why
    assert SYNC in why
    assert lock_stale(repo, sha, read=_fresh) is None, 'PLANTED CONTROL'


def test_the_lock_is_read_at_the_pushed_head_never_the_working_tree(repo: Path) -> None:
    seen: list[str] = []
    old = _git(repo, 'rev-parse', 'HEAD~1')

    def read(tree: Path) -> tuple[str, ...]:
        seen.append(_git(tree, 'rev-parse', 'HEAD'))
        return ()

    assert lock_stale(repo, old, read=read) is None
    assert seen == [old]


def test_a_machine_branch_and_a_deletion_are_not_judged(repo: Path) -> None:
    """The relock is what makes a lock fresh. PLANTED CONTROL: the same tip pushed as pr/x is refused."""
    machine = _line(repo, RELOCK_BRANCH)
    deletion = f'(delete) {_ZERO} refs/heads/pr/x {_git(repo, "rev-parse", "HEAD")}\n'
    assert refusals(repo, machine + deletion, fetch=fetch_ref, read=_lagging) == []
    assert len(refusals(repo, _line(repo), fetch=fetch_ref, read=_lagging)) == 2


def test_ready_is_refused_on_a_dirty_tree_then_on_a_stale_head_and_passes_once_current(repo: Path) -> None:
    forge = StateForge()
    _git(repo, 'push', 'origin', 'pr/x')
    number = forge.add_pull('pr/x', 'int/line', title='WIP: x', sha=_git(repo, 'rev-parse', 'HEAD'))
    (repo / 'pyproject.toml').write_text(_DECL + '# edit\n', encoding='utf-8')
    (why,) = ready_refusals(repo, forge, forge.pr_view(number), read=_fresh)
    assert 'uncommitted changes' in why
    _git(repo, 'checkout', '--', 'pyproject.toml')
    (why,) = ready_refusals(repo, forge, forge.pr_view(number), read=_fresh)
    assert 'does not contain origin/int/line' in why
    _git(repo, 'merge', '--no-edit', 'origin/int/line')
    _git(repo, 'push', 'origin', 'pr/x')
    forge.pulls[number]['head']['sha'] = _git(repo, 'rev-parse', 'HEAD')
    (why,) = ready_refusals(repo, forge, forge.pr_view(number), read=_lagging)
    assert _LAG in why
    assert ready_refusals(repo, forge, forge.pr_view(number), read=_fresh) == [], 'PLANTED CONTROL'
