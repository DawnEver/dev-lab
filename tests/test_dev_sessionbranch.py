"""The four session-branch invariants, each through a REAL ``git push`` to a bare origin and a REAL pre-push hook.

P1 ONE-WRITER-PER-SESSION-BRANCH, P2 PUBLISH-IS-THE-LOCAL-REF, P3 SESSION-HISTORY-ONLY-GROWS,
P4 INTEGRATION-IS-MERGES-ONLY. Every refusal has its planted control: the same push, made the right way,
lands. Names are declared non-defaults (``int/line``, ``stable``, ``feat/s``).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab_commons.dev.sessionbranch import P1
from lab_commons.dev.sessionlease import read, release, take

_GIT = shutil.which('git') or 'git'
_DECL = (
    "[tool.lab_commons.branchset]\ntrunk = 'stable'\nsessions = ['int/line', 'feat/s']\n\n"
    "[tool.lab_commons.integrator]\nintegration = 'int/line'\ntrunk = 'stable'\n"
)
_TEST = 'def test_a():\n    assert True\n\n\ndef test_b():\n    assert 1\n'


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=', *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=60,
    )
    return done.stdout.strip()


def _push(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """``git push origin <args>`` through the installed pre-push hook."""
    return subprocess.run(
        [_GIT, 'push', 'origin', *args],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=120,
    )


def _remote(cwd: Path, branch: str) -> str:
    out = _git(cwd, 'ls-remote', 'origin', f'refs/heads/{branch}')
    return out.split()[0] if out else ''


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A clone of origin with the three declared branches published, the hook installed, ``alice`` running."""
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    monkeypatch.setenv('LAB_COMMONS_SESSION', 'alice')
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--bare', '-b', 'stable', str(origin))
    work = tmp_path / 'work'
    _git(tmp_path, 'clone', str(origin), str(work))
    (work / 'pyproject.toml').write_text(_DECL, encoding='utf-8')
    (work / 'tests').mkdir()
    (work / 'tests' / 'test_a.py').write_text(_TEST, encoding='utf-8')
    _git(work, 'checkout', '-b', 'stable')
    _git(work, 'add', '.')
    _git(work, 'commit', '-m', 'chore: seed')
    for branch in ('int/line', 'feat/s', 'lane/x'):
        _git(work, 'branch', branch)
    _git(work, 'push', 'origin', 'stable', 'int/line', 'feat/s')
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    python = Path(sys.executable).as_posix()
    (hooks / 'pre-push').write_text(
        f'#!/bin/sh\nexec "{python}" -m lab_commons.dev.sessionbranch "$@"\n', encoding='utf-8', newline='\n'
    )
    (hooks / 'pre-push').chmod(0o755)
    _git(work, 'config', 'core.hooksPath', hooks.as_posix())
    _git(work, 'config', 'user.name', 't')
    _git(work, 'config', 'user.email', 't@t')
    for branch in ('int/line', 'feat/s'):
        take(work, branch, who='alice', where='G')
    return work


# --- P2 PUBLISH-IS-THE-LOCAL-REF --------------------------------------------------------------------


@pytest.mark.parametrize('spec', ['HEAD:feat/s', 'lane/x:feat/s', 'HEAD:int/line'])
def test_a_session_branch_published_from_another_ref_is_refused(repo: Path, spec: str) -> None:
    _git(repo, 'checkout', 'lane/x')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: unreviewed')
    done = _push(repo, spec)
    assert done.returncode != 0, done.stderr
    assert 'PUBLISH-IS-THE-LOCAL-REF' in done.stderr
    assert _remote(repo, spec.split(':')[1]) != _git(repo, 'rev-parse', 'HEAD')


def test_a_detached_head_is_refused_and_the_branchs_own_ref_lands(repo: Path) -> None:
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: s')
    _git(repo, 'checkout', '--detach')
    assert 'PUBLISH-IS-THE-LOCAL-REF' in _push(repo, 'HEAD:feat/s').stderr
    _git(repo, 'checkout', 'feat/s')
    done = _push(repo, 'HEAD:feat/s')
    assert done.returncode == 0, done.stderr
    assert _remote(repo, 'feat/s') == _git(repo, 'rev-parse', 'feat/s')


def test_a_branch_needs_no_checkout_to_be_published(repo: Path) -> None:
    """Not bound to a directory: ``git push origin feat/s`` from a checkout on another branch lands."""
    _git(repo, 'branch', '-f', 'feat/s', _git(repo, 'commit-tree', 'stable^{tree}', '-p', 'stable', '-m', 'feat: s'))
    _git(repo, 'checkout', 'lane/x')
    done = _push(repo, 'feat/s')
    assert done.returncode == 0, done.stderr


# --- P3 SESSION-HISTORY-ONLY-GROWS ------------------------------------------------------------------


def test_a_rewritten_session_branch_is_refused_even_forced(repo: Path) -> None:
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: one')
    assert _push(repo, 'feat/s').returncode == 0
    _git(repo, 'commit', '--amend', '--allow-empty', '-m', 'feat: one, rewritten')
    done = _push(repo, '--force', 'feat/s')
    assert done.returncode != 0
    assert 'SESSION-HISTORY-ONLY-GROWS' in done.stderr


def test_deleting_a_session_branch_is_refused(repo: Path) -> None:
    done = _push(repo, ':feat/s')
    assert done.returncode != 0
    assert 'SESSION-HISTORY-ONLY-GROWS' in done.stderr
    assert _remote(repo, 'feat/s')


# --- P1 ONE-WRITER-PER-SESSION-BRANCH ---------------------------------------------------------------


def test_another_session_is_refused_and_the_holder_lands_and_renews(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: s')
    monkeypatch.setenv('LAB_COMMONS_SESSION', 'bob')
    done = _push(repo, 'feat/s')
    assert done.returncode != 0
    assert 'ONE-WRITER-PER-SESSION-BRANCH' in done.stderr
    assert 'alice' in done.stderr
    monkeypatch.setenv('LAB_COMMONS_SESSION', 'alice')
    before = read(repo, 'feat/s')
    done = _push(repo, 'feat/s')
    assert done.returncode == 0, done.stderr
    after = read(repo, 'feat/s')
    assert before is not None
    assert after is not None
    assert after.sha != before.sha, 'a push by the holder renews its lease'


def test_a_branch_without_a_lease_or_without_an_identity_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _git(tmp_path / 'origin.git', 'update-ref', '-d', 'refs/leases/feat/s')
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: s')
    done = _push(repo, 'feat/s')
    assert done.returncode != 0
    assert 'sessionlease take feat/s' in done.stderr
    monkeypatch.delenv('LAB_COMMONS_SESSION')
    assert 'LAB_COMMONS_SESSION' in _push(repo, 'feat/s').stderr


def test_an_expired_lease_does_not_publish(repo: Path, tmp_path: Path) -> None:
    lease = read(repo, 'feat/s')
    assert lease is not None
    past = datetime.now(UTC) - timedelta(hours=1)
    stale = _git(
        repo,
        'commit-tree',
        f'{lease.sha}^{{tree}}',
        '-p',
        lease.sha,
        '-m',
        f'lease feat/s\n\nHolder: alice\nWhere: G\nExpires: {past.strftime("%Y-%m-%dT%H:%M:%SZ")}\n',
    )
    _git(tmp_path / 'origin.git', 'fetch', '-q', str(repo), stale)
    _git(tmp_path / 'origin.git', 'update-ref', 'refs/leases/feat/s', stale)
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: s')
    done = _push(repo, 'feat/s')
    assert done.returncode != 0
    assert 'EXPIRED' in done.stderr


def test_the_trunk_is_guarded_by_the_integration_lease(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(repo, 'checkout', 'lane/x')
    monkeypatch.setenv('LAB_COMMONS_SESSION', 'bob')
    _git(repo, 'branch', '-f', 'stable', _git(repo, 'commit-tree', 'stable^{tree}', '-p', 'stable', '-m', 'x: y'))
    done = _push(repo, 'stable')
    assert done.returncode != 0
    assert 'int/line' in done.stderr
    monkeypatch.setenv('LAB_COMMONS_SESSION', 'alice')
    assert _push(repo, 'stable').returncode == 0


# --- P4 INTEGRATION-IS-MERGES-ONLY ------------------------------------------------------------------


def _merge(repo: Path, branch: str, message: str) -> str:
    """A two-parent commit of ``int/line`` and *branch* on the merged tree, moved onto ``int/line``."""
    tree = _git(repo, 'merge-tree', '--write-tree', 'int/line', branch).splitlines()[0]
    sha = _git(repo, 'commit-tree', tree, '-p', 'int/line', '-p', branch, '-m', message)
    _git(repo, 'branch', '-f', 'int/line', sha)
    return sha


def test_a_plain_commit_on_the_integration_branch_is_refused(repo: Path) -> None:
    _git(repo, 'checkout', 'int/line')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: straight onto integration')
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'INTEGRATION-IS-MERGES-ONLY' in done.stderr
    assert 'not a merge' in done.stderr


def test_a_merge_naming_its_branch_lands_and_one_naming_none_is_refused(repo: Path) -> None:
    _git(repo, 'checkout', 'lane/x')
    (repo / 'x.txt').write_text('x\n', encoding='utf-8')
    _git(repo, 'add', 'x.txt')
    _git(repo, 'commit', '-m', 'feat: x')
    _git(repo, 'checkout', 'stable')
    _merge(repo, 'lane/x', 'chore(merge): lane/x into int/line')
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'Merged-Branch' in done.stderr
    _git(repo, 'branch', '-f', 'int/line', 'int/line^1')
    _merge(repo, 'lane/x', 'chore(merge): lane/x into int/line\n\nMerged-Branch: lane/x\n')
    done = _push(repo, 'int/line')
    assert done.returncode == 0, done.stderr


def test_a_merge_that_loses_a_test_unnamed_is_refused_and_lands_once_named(repo: Path) -> None:
    _git(repo, 'checkout', 'lane/x')
    (repo / 'tests' / 'test_a.py').write_text('def test_a():\n    assert True\n', encoding='utf-8')
    _git(repo, 'commit', '-am', 'test: drop b')
    _git(repo, 'checkout', 'feat/s')
    (repo / 'feat.txt').write_text('f\n', encoding='utf-8')
    _git(repo, 'add', 'feat.txt')
    _git(repo, 'commit', '-m', 'feat: f')
    _git(repo, 'checkout', 'stable')
    base = _git(repo, 'rev-parse', 'int/line')
    message = 'chore(merge): feat/s into int/line\n\nMerged-Branch: feat/s\n'
    lost = _git(repo, 'commit-tree', 'lane/x^{tree}', '-p', base, '-p', 'feat/s', '-m', message)
    _git(repo, 'branch', '-f', 'int/line', lost)
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'LOST test_b' in done.stderr
    named = message + 'Merge-Audit: LOST test_b -- dropped on purpose\n'
    _git(
        repo,
        'branch',
        '-f',
        'int/line',
        _git(repo, 'commit-tree', 'lane/x^{tree}', '-p', base, '-p', 'feat/s', '-m', named),
    )
    done = _push(repo, 'int/line')
    assert done.returncode == 0, done.stderr


def test_creating_the_integration_branch_judges_only_commits_after_the_declared_start(
    repo: Path, tmp_path: Path
) -> None:
    _git(tmp_path / 'origin.git', 'update-ref', '-d', 'refs/heads/int/line')
    _git(repo, 'checkout', 'stable')
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'merges_only_since' in done.stderr
    seed = _git(repo, 'rev-parse', 'stable')
    text = (repo / 'pyproject.toml').read_text(encoding='utf-8')
    (repo / 'pyproject.toml').write_text(text + f"merges_only_since = '{seed}'\n", encoding='utf-8')
    done = _push(repo, 'int/line')
    assert done.returncode == 0, done.stderr


def test_two_sessions_in_two_worktrees_of_one_repo_on_one_host_each_own_only_their_branch(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ownership is per SESSION, never per host, repo or checkout: same box, same repo, two writers."""
    release(repo, 'feat/s', who='alice')
    take(repo, 'feat/s', who='bob', where='G')
    _git(repo, 'checkout', 'stable')
    trees = {'alice': tmp_path / 'wt-int', 'bob': tmp_path / 'wt-s'}
    _git(repo, 'worktree', 'add', str(trees['alice']), 'int/line')
    _git(repo, 'worktree', 'add', str(trees['bob']), 'feat/s')
    own = {'alice': 'int/line', 'bob': 'feat/s'}
    _git(trees['bob'], 'commit', '--allow-empty', '-m', 'feat: bob')
    _git(
        trees['alice'], 'branch', '-f', 'lane/x', _git(repo, 'commit-tree', 'stable^{tree}', '-p', 'stable', '-m', 'x')
    )
    tree = _git(repo, 'merge-tree', '--write-tree', 'int/line', 'lane/x').splitlines()[0]
    merge = _git(
        repo, 'commit-tree', tree, '-p', 'int/line', '-p', 'lane/x', '-m', 'chore(merge): x\n\nMerged-Branch: lane/x\n'
    )
    _git(trees['alice'], 'merge', '--ff-only', merge)
    pairs = (('alice', 'bob'), ('bob', 'alice'))
    for who, other in pairs:
        monkeypatch.setenv('LAB_COMMONS_SESSION', who)
        foreign = _push(trees[who], own[other])
        assert foreign.returncode != 0, f'{who} advanced {own[other]}'
        assert P1 in foreign.stderr
    for who, _ in pairs:
        monkeypatch.setenv('LAB_COMMONS_SESSION', who)
        mine = _push(trees[who], own[who])
        assert mine.returncode == 0, mine.stderr
