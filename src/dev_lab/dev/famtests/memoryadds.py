"""MEMORY-SHAPE, the change half, as the body a consumer's test suite runs: a branch only ADDS memory (W8, dev-lab#646).

The judgment is :func:`dev_lab.dev.memoryadds.problems_between`, the same one the ``pre-push`` row makes. A push
made with the hook off, from a worktree with no venv, or through a web edit never meets that row; the suite that
runs on every PR head does. So this body asserts the SAME reading over the tested head against its integration
branch -- a second door onto one judgment, never a second judgment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.launch import run

from dev_lab.dev.memoryadds import problems_between

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_memory_is_only_added', 'assert_the_memory_guard_still_convicts']

#: The remedy every refusal prints: the closure is a new entry, never an edit.
REMEDY = 'restore the entry and write a NEW one naming it (corrects: or supersedes:), never an edit'


def assert_memory_is_only_added(*, root: Path, base: str, head: str = 'HEAD') -> None:
    """*head*'s commits since its merge-base with *base* only ADD under ``**/.claude/memory/**``.

    Raises:
        AssertionError: an existing entry was edited, deleted or moved; each refusal is named, then the remedy.

    """
    problems = problems_between(root, base, head)
    if problems:
        raise AssertionError('\n  '.join((f'MEMORY-SHAPE: {len(problems)} refusal(s); {REMEDY}:', *problems)))


_ENTRY = '.claude/memory/2026/01/01/an-entry.md'
_TEXT = '---\nname: an-entry\ndescription: d\n---\n\nBody.\n'


def assert_the_memory_guard_still_convicts(plant_root: Path) -> None:
    """THE PLANTED CONTROL, both directions, over a real git repo: an added entry passes, an edited one reds.

    Raises:
        AssertionError: the added entry was refused, or the edited one passed.

    """

    def git(*args: str) -> None:
        run(['git', '-C', str(plant_root), *args], check=True, capture_output=True, timeout=60)

    git('init', '-q', '-b', 'integrate/main')
    git('config', 'user.email', 'plant@example.invalid')
    git('config', 'user.name', 'plant')
    entry = plant_root / _ENTRY
    entry.parent.mkdir(parents=True)
    entry.write_text(_TEXT, encoding='utf-8')
    git('add', _ENTRY)
    git('commit', '-q', '-m', 'base')
    git('update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    added = entry.with_name('another.md')
    added.write_text(_TEXT.replace('an-entry', 'another'), encoding='utf-8')
    git('add', '.')
    git('commit', '-q', '-m', 'add')
    if problems := problems_between(plant_root, 'origin/integrate/main', 'HEAD'):
        msg = f'an added entry was refused: {problems}'
        raise AssertionError(msg)
    entry.write_text(_TEXT + 'Edited.\n', encoding='utf-8')
    git('commit', '-q', '-am', 'edit')
    if not problems_between(plant_root, 'origin/integrate/main', 'HEAD'):
        msg = 'an edited entry passed: the guard reads a constant'
        raise AssertionError(msg)
