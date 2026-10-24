"""MERGE-RESOLUTION-DECLARED: every conflicted file of a merge is declared once, ``<path>: <class> -- <why>``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import mergeresolution
from dev_lab.dev.mergeresolution import BOTH_NEEDED, CLASSES, conflicted, undeclared

_GIT = shutil.which('git') or 'git'


def test_the_classes_are_the_named_set() -> None:
    assert frozenset({'upstream-structure+lane-content', 'lane-supersedes', 'deleted-as-baggage', 'both-needed'}) == (
        CLASSES
    )


def test_every_conflicted_file_declared_once_with_a_class_passes() -> None:
    message = (
        'chore(merge): lane into integrate/main\n\n'
        'src/a.py: upstream-structure+lane-content -- rows moved into the derived table\n'
        'src/b.py: lane-supersedes\n'
        'Merged-Branch: lane\n'
    )
    assert undeclared(('src/a.py', 'src/b.py'), message) == ()
    assert undeclared((), 'chore(merge): clean\n\nMerged-Branch: lane\n') == ()


def test_each_way_a_declaration_fails_is_refused_by_name() -> None:
    """PLANTED CONTROLS: missing, twice, unknown class, both-needed without why, and an over-claim."""
    missing = undeclared(('src/a.py',), 'merge\n')
    assert len(missing) == 1
    assert missing[0].startswith('src/a.py: not declared')
    twice = 'src/a.py: lane-supersedes\nsrc/a.py: deleted-as-baggage\n'
    assert any('declared 2 times' in line for line in undeclared(('src/a.py',), twice))
    assert any('not a resolution class' in line for line in undeclared(('src/a.py',), 'src/a.py: mine\n'))
    assert any('needs its why' in line for line in undeclared(('src/a.py',), f'src/a.py: {BOTH_NEEDED}\n'))
    assert undeclared(('src/a.py',), f'src/a.py: {BOTH_NEEDED} -- both rows are live\n') == ()
    over = undeclared((), 'src/z.py: lane-supersedes -- claimed\n')
    assert over == ('src/z.py: declared, but the parents do not conflict on it -- delete the line',)


def _git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run([_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=check)
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    _git(root, 'add', *files)
    _git(root, 'commit', '-q', '-m', message)


@pytest.fixture
def conflicting(tmp_path: Path) -> Path:
    """A merge in progress whose parents conflict on ``src/a.py`` and merge ``src/c.py`` cleanly."""
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _git(tmp_path, 'config', 'user.email', 't@t')
    _git(tmp_path, 'config', 'user.name', 't')
    _commit(tmp_path, {'src/a.py': 'X = 1\n', 'src/c.py': 'C = 1\n'}, 'base')
    _git(tmp_path, 'checkout', '-q', '-b', 'lane')
    _commit(tmp_path, {'src/a.py': 'X = 2\n', 'src/c.py': 'C = 2\n'}, 'lane')
    _git(tmp_path, 'checkout', '-q', 'main')
    _commit(tmp_path, {'src/a.py': 'X = 3\n'}, 'main')
    _git(tmp_path, 'merge', '-q', '--no-commit', 'lane', check=False)
    (tmp_path / 'src/a.py').write_text('X = 3\n', encoding='utf-8')
    _git(tmp_path, 'add', 'src/a.py')
    return tmp_path


def test_the_conflicted_set_is_recomputed_from_the_parents_trees(conflicting: Path) -> None:
    assert conflicted(conflicting, ('HEAD', 'lane')) == ('src/a.py',)
    assert conflicted(conflicting, ('HEAD', 'HEAD~1')) == ()


def test_the_commit_msg_hook_refuses_an_undeclared_conflict_and_passes_a_declared_one(
    conflicting: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(conflicting)
    message = conflicting / 'MSG'
    message.write_text('merge lane\n\nsrc/c.py: lane-supersedes -- claimed, but c merged clean\n', encoding='utf-8')
    assert mergeresolution.main([str(message)]) == 1
    err = capsys.readouterr().err
    assert 'src/a.py: not declared' in err
    assert 'src/c.py: declared, but the parents do not conflict' in err
    message.write_text('merge lane\n\nsrc/a.py: lane-supersedes -- main holds the newer X\n', encoding='utf-8')
    assert mergeresolution.main([str(message)]) == 0, capsys.readouterr().err


def test_a_plain_commit_is_not_judged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, 'init', '-q', '-b', 'main')
    monkeypatch.chdir(tmp_path)
    message = tmp_path / 'MSG'
    message.write_text('feat: x\n', encoding='utf-8')
    assert mergeresolution.main([str(message)]) == 0
