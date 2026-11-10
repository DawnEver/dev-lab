"""WORKTREES-STAY-INSIDE, both halves: the deny row through the REAL engine, and the detector over a REAL repo.

The row's own ``refuses``/``permits`` are already proved segment by segment in ``test_dev_hooks.py``.
What only the engine can show is the WHOLE-LINE behaviour: an opening is tested against the entire
command, so one good worktree must not open a second, misplaced one chained after it.

The detector is driven over a throwaway repository in ``tmp_path`` with a worktree PLANTED outside it,
so the green on this checkout is a measurement and not a reader that finds nothing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev.famtests.worktreeplace import assert_every_worktree_stays_inside
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.venvpath import checkout_interpreter, current_os_name, venv_interpreter
from dev_lab.dev.worktreeplace import (
    WORKTREES_REL,
    family_root,
    is_inside,
    listed_worktrees,
    main_checkout,
    misplaced_worktrees,
    remedy,
)


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The universal rows only -- this row needs no repo artefact, so an empty adoption ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.mark.parametrize(
    'command',
    [
        'git worktree add --detach .claude/worktrees/a 4ad12b6 && git worktree add --detach ../b 4ad12b6',
        'cd /c/repo && git -C /c/repo worktree add --detach /c/repo-wt 4ad12b6',
        'git worktree add --detach "../lab commons wt" HEAD',
    ],
)
def test_the_engine_refuses_a_misplaced_tree_and_names_the_allowed_form(rules: Path, command: str) -> None:
    """REFUSAL-NAMES-THE-REMEDY: the reason carries the exact allowed path form."""
    reason = agenthooks.decide(command, rules)
    assert reason is not None, f'allowed: {command!r}'
    assert f'{WORKTREES_REL}/<name>' in reason, reason


@pytest.mark.parametrize(
    'command',
    [
        'git worktree add --detach .claude/worktrees/a 4ad12b6 && git worktree add .claude/worktrees/b 4ad12b6',
        'git -C /c/repo worktree add --detach /c/repo/.claude/worktrees/wt 4ad12b6',
        'git worktree list --porcelain',
    ],
)
def test_the_engine_permits_a_tree_inside_its_repository(rules: Path, command: str) -> None:
    """The other side: a guard that refuses the allowed form gets routed around."""
    assert agenthooks.decide(command, rules) is None, command


def _git(*args: str, cwd: Path) -> None:
    subprocess.run([shutil.which('git') or 'git', *args], cwd=cwd, check=True, capture_output=True, timeout=60)


_CLONE = 'sh scripts/hooks/with-retry.sh clone'


@pytest.fixture
def family(tmp_path: Path) -> Path:
    """Two sibling checkouts on two forges, `alpha` with a worktree inside; the family root is returned.

    A family repo is cloned BESIDE its siblings -- that is where every family checkout lives -- so the
    row must admit exactly that shape and nothing that merely resembles it (2026-11-08: adopting learn-lab
    was refused because the row read every clone outside `.claude/worktrees` as a misplaced tree).
    """
    root = tmp_path / 'family'
    for name, url in (('alpha', 'https://forge.example/fam/alpha.git'), ('beta', 'git@other.example:team/beta.git')):
        checkout = root / name
        checkout.mkdir(parents=True)
        _git('init', '-q', cwd=checkout)
        _git('remote', 'add', 'origin', url, cwd=checkout)
    _git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init', cwd=root / 'alpha')
    _git('worktree', 'add', '-q', '--detach', f'{WORKTREES_REL}/wt', 'HEAD', cwd=root / 'alpha')
    (root / 'taken').mkdir()
    return root


@pytest.mark.parametrize(
    ('where', 'command'),
    [
        ('alpha', f'{_CLONE} https://forge.example/fam/gamma.git ../gamma'),
        ('alpha', f'cd .. && {_CLONE} https://forge.example/fam/gamma.git gamma'),
        ('alpha', 'git clone https://forge.example/fam/gamma.git ../gamma'),
        ('alpha', f'{_CLONE} git@other.example:team/delta.git ../delta'),  # beta's forge is the family's too
        (f'alpha/{WORKTREES_REL}/wt', f'{_CLONE} https://forge.example/fam/gamma.git {{family}}/gamma'),
    ],
)
def test_a_family_repo_clones_beside_its_siblings(family: Path, rules: Path, where: str, command: str) -> None:
    """A NEW sibling named for its repo, from a forge a sibling already comes from, is admitted."""
    command = command.replace('{family}', family.as_posix())
    assert agenthooks.decide(command, rules, cwd=family / where) is None, command


@pytest.mark.parametrize(
    'command',
    [
        f'{_CLONE} https://forge.example/fam/taken.git ../taken',  # the directory exists
        f'{_CLONE} https://evil.example/x/gamma.git ../gamma',  # no sibling comes from that forge
        f'{_CLONE} https://forge.example/fam/gamma.git ../other',  # not named for its repo
        f'{_CLONE} https://forge.example/fam/gamma.git ../../gamma',  # not beside the siblings
        f'{_CLONE} https://forge.example/fam/gamma.git ../taken/gamma',  # deeper than the siblings root
        f'{_CLONE} https://forge.example/fam/gamma.git ../gamma && git clone https://forge.example/fam/zeta.git ../x',
        f'{_CLONE} https://forge.example/fam/gamma.git ../gamma && git worktree add ../w HEAD',
        'git clone https://forge.example/fam/gamma.git',  # lands inside the checkout, unnamed
    ],
)
def test_anything_else_a_clone_could_be_is_still_refused(family: Path, rules: Path, command: str) -> None:
    """The other side: the admission is the one shape, so every near-miss still names the remedy."""
    reason = agenthooks.decide(command, rules, cwd=family / 'alpha')
    assert reason is not None, f'allowed: {command!r}'
    assert 'WORKTREES-STAY-INSIDE' in reason, reason


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A one-commit repository with one worktree INSIDE and nothing else."""
    root = tmp_path / 'repo'
    root.mkdir()
    _git('init', '-q', cwd=root)
    _git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init', cwd=root)
    _git('worktree', 'add', '-q', '--detach', f'{WORKTREES_REL}/inside', 'HEAD', cwd=root)
    return root


def test_a_tree_inside_is_not_reported_and_the_reader_read_something(repo: Path) -> None:
    """FLOOR: two trees listed (main plus one), so the empty answer is a measurement."""
    assert len(listed_worktrees(repo)) == 2
    assert misplaced_worktrees(repo) == ()


def test_a_planted_sibling_tree_is_reported_with_the_move_that_fixes_it(repo: Path) -> None:
    """PLANTED CONTROL: the exact incident shape, a worktree created as a sibling of its repo."""
    sibling = repo.parent / 'repo-wt-cf'
    _git('worktree', 'add', '-q', '--detach', str(sibling), 'HEAD', cwd=repo)
    found = misplaced_worktrees(repo)
    assert [item.path.name for item in found] == ['repo-wt-cf']
    assert f'{WORKTREES_REL}/repo-wt-cf' in remedy(found[0])
    # Asked from inside a linked worktree, the answer is the same: git lists one set from every tree.
    assert [item.path.name for item in misplaced_worktrees(repo / WORKTREES_REL / 'inside')] == ['repo-wt-cf']


def test_is_inside_refuses_the_directory_itself_and_a_lookalike_prefix(tmp_path: Path) -> None:
    """``.claude/worktrees`` itself is not a tree inside it, and ``worktrees-old`` is not ``worktrees``."""
    assert is_inside(tmp_path / WORKTREES_REL / 'x', tmp_path)
    assert not is_inside(tmp_path / WORKTREES_REL, tmp_path)
    assert not is_inside(tmp_path / f'{WORKTREES_REL}-old' / 'x', tmp_path)
    assert not is_inside(tmp_path.parent / 'x', tmp_path)


def test_the_family_assertion_is_green_here_and_red_on_the_plant(repo: Path) -> None:
    """The consumer-facing body, both directions, through the same reader."""
    assert_every_worktree_stays_inside(root=repo)
    _git('worktree', 'add', '-q', '--detach', str(repo.parent / 'sibling'), 'HEAD', cwd=repo)
    with pytest.raises(AssertionError, match='worktree move'):
        assert_every_worktree_stays_inside(root=repo)


def test_a_worktree_inside_finds_the_family_but_requires_its_own_venv(repo: Path) -> None:
    """PLANTED: from `<repo>/.claude/worktrees/inside`, siblings resolve beside the MAIN checkout."""
    inside = repo / WORKTREES_REL / 'inside'
    assert main_checkout(inside).resolve() == repo.resolve()
    assert family_root(inside).resolve() == repo.parent.resolve()
    assert inside.parent.parent.resolve() != repo.parent.resolve(), 'the plant must sit where `..` misleads'
    relative = venv_interpreter(os_name=current_os_name())
    with pytest.raises(FileNotFoundError, match='--bootstrap'):
        checkout_interpreter(inside, os_name=current_os_name())
    own = inside / relative
    own.parent.mkdir(parents=True)
    own.write_text('', encoding='utf-8')
    assert checkout_interpreter(inside, os_name=current_os_name()) == own
