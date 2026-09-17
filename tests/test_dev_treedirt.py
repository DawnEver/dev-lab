"""Whether a verdict may be cited for the tree it tested, driven against real checkouts.

``status_paths`` is exercised against real ``git status`` output on real temporary repositories --
tracked edits, untracked files, staged renames -- because the parsing is entirely about a format
this code does not own, and a fixture that produced the format would be asserting the author's
belief about it rather than git's behaviour.

``verdict_dirt`` is pure over two readings, so its arms are tables: that is the half where every
wrong answer is a policy mistake rather than a parsing one, and where the planted controls belong.
"""

from __future__ import annotations

import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.treedirt import Dirt, Kind, path_of, status_paths, verdict_dirt

#: Resolved once, so the fixture drives the same git the module under test resolves.
_GIT = shutil.which('git') or 'git'


def _git(root: Path, *args: str) -> str:
    """One git command in *root*, failing loudly -- a broken fixture must not read as a finding."""
    return subprocess.run(
        [_GIT, *args], cwd=root, capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A checkout with one committed file, so "clean" is a state it can actually be in."""
    root = tmp_path / 'checkout'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'trunk')
    _git(root, 'config', 'user.email', 'fixture@example.invalid')
    _git(root, 'config', 'user.name', 'Fixture')
    (root / 'tracked.txt').write_text('one\n', encoding='utf-8')
    _git(root, 'add', 'tracked.txt')
    _git(root, 'commit', '-q', '-m', 'first')
    return root


def test_a_clean_checkout_reads_as_an_EMPTY_TUPLE_and_not_as_None(repo: Path) -> None:
    """THE FLOOR, and the distinction the whole module rests on: clean is not unreadable."""
    assert status_paths(repo) == ()


def test_a_modified_tracked_file_is_reported(repo: Path) -> None:
    """The ordinary dirty reading."""
    (repo / 'tracked.txt').write_text('two\n', encoding='utf-8')
    paths = status_paths(repo)
    assert paths is not None
    assert [path_of(line) for line in paths] == ['tracked.txt']


def test_an_UNTRACKED_file_is_reported_too(repo: Path) -> None:
    """The measured 2026-09-05 case: two 0-byte untracked files from a failed ``cd`` made a run uncitable.

    They count, which is correct -- the remedy is to NAME them, not to stop seeing them.
    """
    (repo / 'results.jsonl').write_text('', encoding='utf-8')
    paths = status_paths(repo)
    assert paths is not None
    assert [path_of(line) for line in paths] == ['results.jsonl']


def test_a_RENAME_reports_its_DESTINATION(repo: Path) -> None:
    """The file that now exists is the one a suite can read, so it is the one the prefix test sees."""
    _git(repo, 'mv', 'tracked.txt', 'moved.txt')
    paths = status_paths(repo)
    assert paths is not None
    assert [path_of(line) for line in paths] == ['moved.txt']


def test_a_directory_that_is_not_a_checkout_reads_as_None(tmp_path: Path) -> None:
    """AN UNREADABLE REPOSITORY IS ``None``, NEVER AN EMPTY LIST -- the vacuous-green shape, refused."""
    assert status_paths(tmp_path) is None


@pytest.mark.parametrize(
    ('line', 'expected'),
    [
        (' M src/a.py', 'src/a.py'),
        ('?? output/log.txt', 'output/log.txt'),
        ('A  .claude/tasks/t.json', '.claude/tasks/t.json'),
        ('R  old.py -> new.py', 'new.py'),
        ('?? "has space.txt"', 'has space.txt'),
        ('', ''),
    ],
)
def test_path_of_reads_each_porcelain_shape(line: str, expected: str) -> None:
    """Including the QUOTED spelling: a prefix test against a leading quote matches nothing at all."""
    assert path_of(line) == expected


def test_a_clean_start_and_a_clean_end_is_CITABLE() -> None:
    """THE FLOOR FOR EVERY REFUSAL BELOW: this function can still say yes."""
    got = verdict_dirt((), (), neutral_prefixes=())
    assert got == Dirt(Kind.CLEAN, ())
    assert not got.kind.disqualifying


def test_DIRTY_AT_START_refuses_and_names_what_was_already_there() -> None:
    """There is no commit to vouch for, so the remedy is to commit -- and the reader is told which."""
    got = verdict_dirt((' M src/a.py',), (' M src/a.py',), neutral_prefixes=())
    assert got == Dirt(Kind.DIRTY, (' M src/a.py',))
    assert got.kind.disqualifying


def test_a_tree_that_MOVED_MID_RUN_refuses_with_a_DIFFERENT_kind() -> None:
    """A different remedy -- re-run, not commit -- so it may not share a word with the case above."""
    got = verdict_dirt((), (' M docs/x.md',), neutral_prefixes=())
    assert got == Dirt(Kind.MOVED, (' M docs/x.md',))


def test_only_the_paths_that_APPEARED_are_named_and_not_the_whole_end_reading() -> None:
    """The reader needs the disqualifying edit, not a census of the tree at the end of a long run."""
    got = verdict_dirt((), ('?? a.txt', '?? b.txt'), neutral_prefixes=('a.',))
    assert got == Dirt(Kind.MOVED, ('?? b.txt',))


def test_a_NEUTRAL_path_appearing_mid_run_does_not_disqualify() -> None:
    """The escape hatch, with its ceiling: it applies only to prefixes the CALLER measured and named."""
    got = verdict_dirt((), ('?? .claude/tasks/t.json',), neutral_prefixes=('.claude/tasks/',))
    assert got == Dirt(Kind.CLEAN, ())


def test_the_SAME_path_DISQUALIFIES_when_the_caller_declared_nothing() -> None:
    """THE PLANTED CONTROL: fail-closed, so an unlisted path is verdict-bearing.

    Identical to the arm above in every respect but the declaration, which is what makes the
    declaration -- rather than a hard-coded set inherited from another repo -- the thing deciding.
    """
    got = verdict_dirt((), ('?? .claude/tasks/t.json',), neutral_prefixes=())
    assert got.kind is Kind.MOVED


def test_a_neutral_PREFIX_does_not_neutralise_a_path_that_merely_contains_it() -> None:
    """A prefix is anchored at the start, or ``src/.claude/tasks/`` would be waved through too."""
    got = verdict_dirt((), ('?? src/.claude/tasks/t.json',), neutral_prefixes=('.claude/tasks/',))
    assert got.kind is Kind.MOVED


@pytest.mark.parametrize(
    ('start', 'end'),
    [(None, ()), ((), None), (None, None)],
)
def test_an_UNREADABLE_reading_at_EITHER_END_refuses(start: tuple | None, end: tuple | None) -> None:
    """Promoting an unanswerable question to the reassuring answer is the defect this module is about."""
    got = verdict_dirt(start, end, neutral_prefixes=())
    assert got == Dirt(Kind.UNREADABLE, ())
    assert got.kind.disqualifying


def test_UNREADABLE_is_a_DIFFERENT_WORD_from_DIRTY() -> None:
    """The migrated version folded them and its own header recorded the cost: a refusal naming nothing."""
    assert Kind.UNREADABLE is not Kind.DIRTY
    assert verdict_dirt(None, None, neutral_prefixes=()).kind is not Kind.DIRTY


def test_the_neutral_set_is_a_REQUIRED_KEYWORD_with_no_default() -> None:
    """Inheriting another repo's measurement would wave through a path that IS a test input here.

    ``()`` must be spelled, so "we measured and found none" and "we never asked" are different acts.
    """
    neutral = inspect.signature(verdict_dirt).parameters['neutral_prefixes']
    assert neutral.kind is inspect.Parameter.KEYWORD_ONLY
    assert neutral.default is inspect.Parameter.empty


def test_the_whole_cycle_over_a_REAL_checkout_that_moves_under_the_run(repo: Path) -> None:
    """End to end: read, let something appear, read again, and get MOVED naming the new file."""
    start = status_paths(repo)
    (repo / 'appeared-mid-run.txt').write_text('', encoding='utf-8')
    end = status_paths(repo)
    got = verdict_dirt(start, end, neutral_prefixes=())
    assert got.kind is Kind.MOVED
    assert [path_of(line) for line in got.paths] == ['appeared-mid-run.txt']
