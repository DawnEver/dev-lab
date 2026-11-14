"""A main checkout follows its branch: lossless obstacles go, a real one or a divergence is refused by name."""

from __future__ import annotations

import sys
from pathlib import Path

from _ops_fixtures import git

from dev_lab.dev import mainsync

#: A bootstrap that changes nothing: the door's venv step is :func:`dev_lab.dev.hostrefresh.sync_venv`'s.
_NO_BOOTSTRAP = (sys.executable, '-c', 'pass')


def _origin_and_main(tmp: Path) -> tuple[Path, Path]:
    """A bare origin whose ``main`` carries ``kept.json``, and a main checkout left DETACHED one commit behind."""
    work, bare, main = tmp / 'work', tmp / 'origin.git', tmp / 'main'
    work.mkdir()
    git(work, 'init', '-q', '-b', 'main')
    git(work, 'config', 'user.email', 't@example.invalid')
    git(work, 'config', 'user.name', 't')
    (work / 'a.txt').write_text('one\n', encoding='utf-8')
    git(work, 'add', 'a.txt')
    git(work, 'commit', '-q', '-m', 'one')
    git(tmp, 'clone', '-q', '--bare', str(work), str(bare))
    git(tmp, 'clone', '-q', str(bare), str(main))
    git(main, 'checkout', '-q', '--detach')
    (work / 'kept.json').write_text('{"mode": "issues"}\n', encoding='utf-8')
    git(work, 'add', 'kept.json')
    git(work, 'commit', '-q', '-m', 'two')
    git(work, 'push', '-q', str(bare), 'main')
    return bare, main


def _sync(main: Path) -> str:
    return mainsync.sync(main, branch='main', bootstrap=_NO_BOOTSTRAP, git=('git',))


def test_an_identical_untracked_file_is_no_obstacle(tmp_path: Path) -> None:
    _, main = _origin_and_main(tmp_path)
    (main / 'kept.json').write_text('{"mode": "issues"}\n', encoding='utf-8')
    assert _sync(main) == ''
    assert git(main, 'branch', '--show-current') == 'main'
    assert git(main, 'rev-parse', 'HEAD') == git(main, 'rev-parse', 'origin/main')
    assert (main / 'kept.json').read_text(encoding='utf-8') == '{"mode": "issues"}\n'


def test_a_differing_untracked_file_is_refused_by_name(tmp_path: Path) -> None:
    _, main = _origin_and_main(tmp_path)
    (main / 'kept.json').write_text('{"mode": "mine"}\n', encoding='utf-8')
    why = _sync(main)
    assert 'kept.json' in why
    assert 'differ' in why
    assert (main / 'kept.json').read_text(encoding='utf-8') == '{"mode": "mine"}\n'  # never touched


def test_a_tracked_change_is_refused_by_name(tmp_path: Path) -> None:
    _, main = _origin_and_main(tmp_path)
    (main / 'a.txt').write_text('edited\n', encoding='utf-8')
    why = _sync(main)
    assert 'a.txt' in why


def test_a_divergent_branch_is_refused_not_merged(tmp_path: Path) -> None:
    _, main = _origin_and_main(tmp_path)
    git(main, 'switch', '-q', 'main')
    git(main, 'config', 'user.email', 't@example.invalid')
    git(main, 'config', 'user.name', 't')
    (main / 'local.txt').write_text('local\n', encoding='utf-8')
    git(main, 'add', 'local.txt')
    git(main, 'commit', '-q', '-m', 'local')
    why = _sync(main)
    assert 'diverge' in why
    assert git(main, 'log', '-1', '--format=%s') == 'local'  # nothing merged


def test_a_current_checkout_is_left_as_it_is(tmp_path: Path) -> None:
    _, main = _origin_and_main(tmp_path)
    git(main, 'switch', '-q', 'main')
    git(main, 'merge', '-q', '--ff-only', 'origin/main')
    assert _sync(main) == ''
