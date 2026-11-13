"""BASE-HOLDS-THE-MILESTONE and VERSION-TAG-NEEDS-APPROVAL, judged on real repositories.

A pushed branch must contain the highest local ``v*`` tag in the family grammar (dev versions included); an agent
session creates a ``v*`` tag on origin only with the user's approval words in the environment. Every refusal has its
planted control: the same push, made the right way, passes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.milestonebase import APPROVED_ENV, BASE_RULE, TAG_RULE, milestone_version, refusals
from dev_lab.dev.sessionprs import SESSION_ENV

_GIT = shutil.which('git') or 'git'
_ZERO = '0' * 40
_WIDTH = 320


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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """``old`` is behind the milestone ``v0.2.13.dev1``, ``new`` contains it."""
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'feat: one')
    _git(tmp_path, 'tag', '-a', 'v0.2.12', '-m', 'v0.2.12')
    _git(tmp_path, 'branch', 'old')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'feat: two')
    _git(tmp_path, 'tag', '-a', 'v0.2.13.dev1', '-m', 'v0.2.13.dev1')
    _git(tmp_path, 'checkout', '-q', '-b', 'new')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'feat: three')
    return tmp_path


def _branch(root: Path, name: str) -> str:
    sha = _git(root, 'rev-parse', name)
    return f'refs/heads/{name} {sha} refs/heads/pr/{name} {_ZERO}\n'


def _tag(root: Path, name: str) -> str:
    sha = _git(root, 'rev-parse', name)
    return f'refs/tags/{name} {sha} refs/tags/{name} {_ZERO}\n'


def test_a_branch_behind_the_newest_milestone_is_refused_naming_the_door(repo: Path) -> None:
    found = refusals(repo, _branch(repo, 'old'), env={})
    assert len(found) == 1
    assert found[0].startswith(f'{BASE_RULE}:')
    assert 'v0.2.13.dev1' in found[0]
    assert 'python -m dev_lab.dev.forge sync' in found[0]
    assert len(found[0]) <= _WIDTH


def test_a_branch_containing_the_milestone_passes(repo: Path) -> None:
    """PLANTED CONTROL for the refusal above."""
    assert refusals(repo, _branch(repo, 'new'), env={}) == []


def test_the_highest_family_version_is_the_milestone_not_the_newest_tag(repo: Path) -> None:
    """``v0.2.13.dev10`` outranks ``.dev9`` and ``v0.2.13`` outranks both, whatever order they were made in."""
    _git(repo, 'checkout', '-q', 'main')
    _git(repo, 'commit', '-q', '--allow-empty', '-m', 'feat: four')
    _git(repo, 'tag', '-a', 'v0.2.13.dev10', '-m', 'x')
    _git(repo, 'commit', '-q', '--allow-empty', '-m', 'feat: five')
    _git(repo, 'tag', '-a', 'v0.2.13.dev9', '-m', 'x')
    found = refusals(repo, _branch(repo, 'new'), env={})
    assert len(found) == 1
    assert 'v0.2.13.dev10' in found[0]
    assert refusals(repo, _branch(repo, 'main'), env={}) == []


def test_a_legacy_unverified_tag_reads_as_its_base_version_and_junk_is_ignored() -> None:
    assert milestone_version('v0.2.13-unverified') == milestone_version('v0.2.13')
    assert milestone_version('v0.2.13') > milestone_version('v0.2.13.dev3')  # type: ignore[operator]
    assert milestone_version('v0.2.13.dev10') > milestone_version('v0.2.13.dev9')  # type: ignore[operator]
    assert milestone_version('v0.2.13.dev1-unverified') == milestone_version('v0.2.13.dev1')
    assert milestone_version('v0.2.13rc1') is None
    assert milestone_version('vendor-drop') is None
    assert milestone_version('0.2.13') is None


def test_no_version_tag_passes(tmp_path: Path) -> None:
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'feat: one')
    _git(tmp_path, 'branch', 'old')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'feat: two')
    _git(tmp_path, 'tag', '-a', 'vendor-drop', '-m', 'x')
    assert refusals(tmp_path, _branch(tmp_path, 'old'), env={}) == []


def test_a_deleted_branch_is_not_judged(repo: Path) -> None:
    assert refusals(repo, f'(delete) {_ZERO} refs/heads/pr/old {"a" * 40}\n', env={}) == []


def test_an_agent_session_creating_a_version_tag_is_refused(repo: Path) -> None:
    found = refusals(repo, _tag(repo, 'v0.2.13.dev1'), env={SESSION_ENV: 's1'})
    assert len(found) == 1
    assert found[0].startswith(f'{TAG_RULE}:')
    assert APPROVED_ENV in found[0]
    assert len(found[0]) <= _WIDTH


def test_the_users_approval_words_admit_the_tag(repo: Path) -> None:
    """PLANTED CONTROL: the same push, with the user's words, passes; blank words do not count."""
    line = _tag(repo, 'v0.2.13.dev1')
    assert refusals(repo, line, env={SESSION_ENV: 's1', APPROVED_ENV: 'tag dev1 now'}) == []
    assert refusals(repo, line, env={SESSION_ENV: 's1', APPROVED_ENV: '  '}) != []


def test_a_human_push_and_other_tags_are_not_judged(repo: Path) -> None:
    assert refusals(repo, _tag(repo, 'v0.2.13.dev1'), env={}) == []
    _git(repo, 'tag', 'build-7')
    assert refusals(repo, _tag(repo, 'build-7'), env={SESSION_ENV: 's1'}) == []


def test_an_existing_tag_on_origin_is_not_a_new_one(repo: Path) -> None:
    sha = _git(repo, 'rev-parse', 'v0.2.13.dev1')
    line = f'refs/tags/v0.2.13.dev1 {sha} refs/tags/v0.2.13.dev1 {sha}\n'
    assert refusals(repo, line, env={SESSION_ENV: 's1'}) == []
