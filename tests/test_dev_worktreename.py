"""WORKTREE-NAMES-ITS-TASK, both halves: the deny row through the REAL engine, and the detector over a REAL repo.

User ruling 2026-11-22: a worktree's name has a physical meaning related to its task; a hash appended by an
agent is forbidden. Every reading is planted both ways -- a hash-like name refused, a meaningful one let through.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev.disclosure import details_for, problems
from dev_lab.dev.famtests.worktreeplace import assert_every_worktree_names_its_task
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.worktreename import DOOR, RULE, hash_like, hash_named
from dev_lab.dev.worktreeplace import WORKTREES_REL

ROOT = Path(__file__).resolve().parents[1]

#: Names an agent or a harness mints: nothing in them says what the tree is for.
HASH_LIKE = ('agent-a1b2c3d4', 'agent-facade', 'fix-4ad12b6', 'fix_4ad12b6', 'windows-base-green-9ec201a0',
             '4ad12b6', '9ec201a0f3', 'lane.0c7317f0', 'AGENT-A1B2C3D4', 'probe-4AD12B6')  # fmt: skip
#: Names that say what the tree is for, the live ones of 2026-11-22 among them; a date, an issue number and a
#: word spelled in hex letters are meaning, not a hash.
MEANINGFUL = ('windows-base-green-2', 'integrate-green-1122', 'principles-image-path-worktree-name', 'ci-same-sha',
              'uvwriter', 'hpc-repair', 'issue-123456', 'wave-20261122', 'user-facade', 'decade', 'x', 'wt',
              'lab-commons-wt-cf', 'fix-4ad12', 'agent-guard', 'agent-a1b2', 'fix-4ad12b6-on-windows')  # fmt: skip


@pytest.mark.parametrize('name', HASH_LIKE)
def test_a_hash_like_name_is_hash_like(name: str) -> None:
    assert hash_like(name), name


@pytest.mark.parametrize('name', MEANINGFUL)
def test_a_name_with_a_meaning_is_not(name: str) -> None:
    """The other side: a predicate that refused these would be routed around."""
    assert not hash_like(name), name


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The universal rows only -- this row needs no repo artefact, so an empty adoption ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.mark.parametrize('name', HASH_LIKE)
@pytest.mark.parametrize(
    'shape',
    [
        'git worktree add --detach .claude/worktrees/{name} 4ad12b6',
        'git worktree add -b pr/task/feature .claude/worktrees/{name} origin/integrate/main',
        'git -C C:/work/repo worktree add "C:/work/repo/.claude/worktrees/{name}" HEAD',
        r'git worktree add --detach C:\work\repo\.claude\worktrees\{name} 4ad12b6',
        'git worktree move .claude/worktrees/lane .claude/worktrees/{name}',
        'git worktree add --detach .claude/worktrees/good 4ad12b6 && git worktree add .claude/worktrees/{name} HEAD',
    ],
)
def test_the_engine_refuses_a_hash_named_tree_by_name_and_names_the_door(rules: Path, shape: str, name: str) -> None:
    reason = agenthooks.decide(shape.replace('{name}', name), rules)
    assert reason is not None, f'allowed: {shape} with {name}'
    assert RULE in reason, reason
    assert DOOR in reason, reason
    assert f'{WORKTREES_REL}/<feature>' in reason, reason
    assert reason.splitlines()[-1] == details_for(RULE)
    assert problems(reason, 'refusal') == []


@pytest.mark.parametrize('name', MEANINGFUL)
def test_the_engine_permits_a_tree_named_for_its_task(rules: Path, name: str) -> None:
    for shape in (
        'git worktree add --detach .claude/worktrees/{name} 4ad12b6',
        'git worktree add -b pr/toolchain/{name} .claude/worktrees/{name} origin/integrate/main',
        'git worktree move .claude/worktrees/agent-a1b2c3d4 .claude/worktrees/{name}',
    ):
        command = shape.replace('{name}', name)
        assert agenthooks.decide(command, rules) is None, command


@pytest.mark.parametrize(
    'command',
    [
        # The commit-ish and the branch are hashes by nature; only the tree's own name is judged.
        'git worktree add --detach .claude/worktrees/probe 4ad12b6f',
        'git worktree add -b fix/4ad12b6f .claude/worktrees/probe 4ad12b6f',
        'git worktree move .claude/worktrees/agent-a1b2c3d4 .claude/worktrees/render-the-page',
        'git worktree list --porcelain',
        'git commit -m "refuse git worktree add .claude/worktrees/agent-a1b2c3d4"',
    ],
)
def test_only_the_name_of_a_tree_being_made_is_judged(rules: Path, command: str) -> None:
    assert agenthooks.decide(command, rules) is None, command


def _git(*args: str, cwd: Path) -> None:
    subprocess.run([shutil.which('git') or 'git', *args], cwd=cwd, check=True, capture_output=True, timeout=60)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A one-commit repository with one worktree named for its task."""
    root = tmp_path / 'repo'
    root.mkdir()
    _git('init', '-q', cwd=root)
    _git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init', cwd=root)
    _git('worktree', 'add', '-q', '--detach', f'{WORKTREES_REL}/render-the-page', 'HEAD', cwd=root)
    return root


def test_the_detector_names_a_planted_hash_named_tree_and_its_door(repo: Path) -> None:
    """PLANTED: green on trees named for their task, red the moment one arrives named by a hash."""
    assert hash_named(repo) == ()
    assert_every_worktree_names_its_task(root=repo)
    _git('worktree', 'add', '-q', '--detach', f'{WORKTREES_REL}/agent-a1b2c3d4', 'HEAD', cwd=repo)
    assert [path.name for path in hash_named(repo)] == ['agent-a1b2c3d4']
    with pytest.raises(AssertionError, match='agent-a1b2c3d4') as red:
        assert_every_worktree_names_its_task(root=repo)
    assert RULE in str(red.value)
    assert 'worktree move' in str(red.value)


def test_no_worktree_of_this_repository_is_named_by_a_hash() -> None:
    """The list of this very checkout through the consumer body; the main checkout is excepted, it is the repository."""
    assert_every_worktree_names_its_task(root=ROOT)
