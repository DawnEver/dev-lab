"""The session-branch invariants, each through a REAL ``git push`` to a bare origin and a REAL pre-push hook.

P2 PUBLISH-IS-THE-LOCAL-REF, P3 SESSION-HISTORY-ONLY-GROWS, P4 INTEGRATION-IS-MERGES-ONLY -- and P1
ONE-WRITER-PER-SESSION-BRANCH, proved to be git's own mechanisms. Every refusal has its planted control: the
same push, made the right way, lands. Names are declared non-defaults (``int/line``, ``stable``, ``feat/s``).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev.sessionbranch import P3

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
def repo(tmp_path: Path) -> Path:
    """A clone of origin with the three declared branches published, the hook installed."""
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


def test_two_sessions_in_two_worktrees_of_one_repo_on_one_host_never_share_a_writer(repo: Path, tmp_path: Path) -> None:
    """ONE-WRITER-PER-SESSION-BRANCH is git's own: one checkout per branch locally, compare-and-swap remotely."""
    _git(repo, 'checkout', 'stable')
    first, second = tmp_path / 'wt-a', tmp_path / 'wt-b'
    _git(repo, 'worktree', 'add', str(first), 'feat/s')
    taken = subprocess.run(
        [_GIT, 'worktree', 'add', str(second), 'feat/s'],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    assert taken.returncode != 0, 'a second worktree checked out a branch another session holds'
    _git(repo, 'worktree', 'add', str(second), 'lane/x')
    _git(second, 'commit', '--allow-empty', '-m', 'feat: the other session')
    assert _push(second, 'lane/x:feat/s').returncode != 0, 'publishing onto the other session branch'
    other = tmp_path / 'other-host'
    _git(tmp_path, 'clone', '-q', '-b', 'feat/s', str(tmp_path / 'origin.git'), str(other))
    _git(other, 'commit', '--allow-empty', '-m', 'feat: a clone that went first')
    assert (
        subprocess.run([_GIT, 'push', 'origin', 'feat/s'], cwd=other, capture_output=True, check=False).returncode == 0
    )
    _git(first, 'commit', '--allow-empty', '-m', 'feat: on a stale tip')
    stale = _push(first, 'feat/s')
    assert stale.returncode != 0, 'a stale tip overwrote the other writer'
    assert P3 in stale.stderr, 'git hands the hook the real remote tip: the stale push is judged before it is sent'
    assert P3 in _push(first, '--force', 'feat/s').stderr, 'the force that would bypass it'
    _git(first, 'pull', '-q', '--no-rebase', '--no-edit', 'origin', 'feat/s')
    landed = _push(first, 'feat/s')
    assert landed.returncode == 0, landed.stderr
