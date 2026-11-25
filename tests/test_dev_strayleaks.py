"""``dev_lab.dev.strayleaks``: each leak family found where it lands, removed only when its content proves it ours.

Planted under a fake drive and home, never the real ones. Controls beside every removal: a checkout cloned from
https, a ``results`` dir holding a person's file, a cache without pytest's README and an untraced family all stay.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import strayleaks

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_GIT = shutil.which('git') or 'git'
_SHA = 'ab' + 'c' * 62


def _git(path: Path, *args: str) -> None:
    subprocess.run([_GIT, '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True)


def _clone(path: Path, url: str, *, pushed: bool = True) -> None:
    """A real checkout naming *url* as origin; its one commit is on origin unless *pushed* is False."""
    (path / 'components' / 'numerics-lab').mkdir(parents=True)
    _git(path, 'init', '-q', '-b', 'main')
    (path / 'core.py').write_text('X = 1\n', encoding='utf-8')
    _git(path, 'add', 'core.py')
    _git(path, 'commit', '-q', '-m', 'one')
    _git(path, 'remote', 'add', 'origin', url)
    if pushed:
        _git(path, 'update-ref', 'refs/remotes/origin/main', 'HEAD')


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    drive, home = tmp_path / 'drive', tmp_path / 'home'
    drive.mkdir()
    home.mkdir()
    return drive, home


def test_every_family_of_the_report_is_found_and_judged(roots: tuple[Path, Path]) -> None:
    drive, home = roots
    (drive / 'var' / 'tmp' / 'lab-supervise-candidate' / 'home').mkdir(parents=True)
    (drive / 'results' / 'ab').mkdir(parents=True)
    (drive / 'results' / 'ab' / _SHA).write_bytes(b'x')
    _clone(drive / 'src' / 'repos' / 'product', 'file:///fixtures/product')
    _clone(drive / 'r' / 'repos' / 'dev-lab', 'file:///x/dev-lab')
    (drive / 'tmp_diag').mkdir()
    metrics = home / 'output' / 'logs' / '26' / '11' / '24' / 'metrics'
    metrics.mkdir(parents=True)
    (metrics / 'host_failure.jsonl').write_text('{}\n', encoding='utf-8')
    (home / '.pytest_cache').mkdir()
    (home / '.pytest_cache' / 'README.md').write_text('# pytest cache directory #\n', encoding='utf-8')
    verdicts = {one.family.name: one.kept for one in strayleaks.find([drive], home)}
    assert set(verdicts) == {family.name for family in strayleaks.FAMILIES if not family.glob}
    assert {name for name, why in verdicts.items() if why is not None} == set(), verdicts
    _removed, kept = strayleaks.remove(strayleaks.find([drive], home))
    assert kept == []
    assert list(drive.iterdir()) == [], 'every family and its emptied parents are gone'
    assert list(home.iterdir()) == []


@pytest.mark.parametrize(
    ('spoil', 'why'),
    [
        (lambda p: (p / 'notes.txt').write_text('x', encoding='utf-8'), 'uncommitted'),
        (lambda p: _git(p, 'commit', '-q', '--allow-empty', '-m', 'mine'), 'on no remote'),
        (lambda p: _git(p, 'remote', 'remove', 'origin'), 'names no remote'),
    ],
)
def test_planted_a_suspect_checkout_with_work_of_its_own_is_named_and_kept(
    roots: tuple[Path, Path], spoil: Callable[[Path], object], why: str
) -> None:
    """PLANTED CONTROL for SUSPECT: a change, an unpushed commit, or no remote at all keeps the checkout."""
    drive, home = roots
    product = drive / strayleaks.SUSPECT[0]
    _clone(product, 'file:///fixtures/product')
    spoil(product)
    found = strayleaks.find([drive], home)
    assert {one.family.name for one in found if one.kept is not None} >= {f'suspect:{strayleaks.SUSPECT[0]}'}
    assert any(why in (one.kept or '') for one in found)
    strayleaks.remove(found)
    assert (product / 'core.py').is_file()


def test_a_pushed_clean_suspect_checkout_and_its_parents_go(roots: tuple[Path, Path]) -> None:
    drive, home = roots
    _clone(drive / strayleaks.SUSPECT[0], 'https://forge.example/o/product.git')
    removed, kept = strayleaks.remove(strayleaks.find([drive], home))
    assert removed == [drive / strayleaks.SUSPECT[0]]
    assert [k for k, _ in kept] == [drive / 'src' / 'repos'], 'the https family keeps; it is empty and pruned'
    assert list(drive.iterdir()) == []


def test_tmp_diag_goes_empty_and_stays_holding_a_file(roots: tuple[Path, Path]) -> None:
    drive, home = roots
    (drive / 'tmp_diag' / 'sub').mkdir(parents=True)
    strayleaks.remove(strayleaks.find([drive], home))
    assert not (drive / 'tmp_diag').exists()
    (drive / 'tmp_diag').mkdir()
    (drive / 'tmp_diag' / 'trace.txt').write_text('x', encoding='utf-8')  # PLANTED CONTROL
    strayleaks.remove(strayleaks.find([drive], home))
    assert (drive / 'tmp_diag' / 'trace.txt').is_file()


def _https_clone(drive: Path, _home: Path) -> None:
    _clone(drive / 'src' / 'repos' / 'mine', 'https://forge.example/o/mine.git')


def _results_note(drive: Path, _home: Path) -> None:
    (drive / 'results').mkdir()
    (drive / 'results' / 'notes.txt').write_text('x', encoding='utf-8')


def _bare_cache(_drive: Path, home: Path) -> None:
    (home / '.pytest_cache').mkdir()
    (home / '.pytest_cache' / 'notes.md').write_text('x', encoding='utf-8')  # not pytest's


def _home_output(_drive: Path, home: Path) -> None:
    (home / 'output').mkdir()
    (home / 'output' / 'thesis.pdf').write_bytes(b'x')


@pytest.mark.parametrize(
    ('plant', 'family'),
    [
        (_https_clone, 'deploy-src-clones'),
        (_results_note, 'fake-remote-objects'),
        (_bare_cache, 'home-pytest-cache'),
        (_home_output, 'home-metrics'),
    ],
)
def test_planted_a_persons_tree_at_a_family_path_is_kept_by_name(
    roots: tuple[Path, Path], plant: Callable[[Path, Path], None], family: str
) -> None:
    """PLANTED CONTROL: the same path holding content no suite wrote is somebody's, so it stays."""
    drive, home = roots
    plant(drive, home)
    (found,) = strayleaks.find([drive], home)
    assert found.family.name == family
    assert found.kept is not None
    removed, kept = strayleaks.remove([found])
    assert (removed, [path for path, _ in kept]) == ([], [found.path])
    assert found.path.exists()


def test_a_removal_takes_the_emptied_parents_and_stops_at_a_held_one(roots: tuple[Path, Path]) -> None:
    drive, home = roots
    (drive / 'var' / 'tmp' / 'lab-supervise-candidate').mkdir(parents=True)
    (drive / 'var' / 'log').mkdir()  # PLANTED CONTROL: a sibling keeps var/
    _clone(drive / 'src' / 'repos' / 'product', 'file:///x/product')
    (drive / 'src' / 'repos' / 'product' / '.git' / 'config').chmod(0o444)  # a git object's bits
    removed, kept = strayleaks.remove(strayleaks.find([drive], home))
    assert kept == []
    assert len(removed) == 2
    assert sorted(p.name for p in drive.iterdir()) == ['var']
    assert sorted(p.name for p in (drive / 'var').iterdir()) == ['log']


def test_nothing_is_found_on_a_clean_host(roots: tuple[Path, Path]) -> None:
    drive, home = roots
    assert strayleaks.find([drive], home) == []


def _project_temp(home: Path, name: str, *, days: float) -> Path:
    entry = home / 'JMAGDesignerTemp' / name
    entry.mkdir(parents=True)
    (entry / 'model.jproj.tmp').write_bytes(b'x')
    then = time.time() - days * 86400
    for one in (entry / 'model.jproj.tmp', entry):
        os.utime(one, (then, then))
    return entry


@pytest.mark.parametrize(
    ('days', 'held', 'removed'),
    [
        (30, [], True),
        (1, [], False),  # inside the age: a session may still write it
        (30, 'live', False),  # PLANTED CONTROL: a running JMAG holds a file inside
        (30, 'psutil is not installed, so a running holder cannot be ruled out', False),
    ],
)
def test_a_jmag_project_temp_goes_only_when_old_and_unheld(
    roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, days: float, held: object, *, removed: bool
) -> None:
    drive, home = roots
    entry = _project_temp(home, 'ProjectTemp_1234', days=days)
    (home / 'JMAGDesignerTemp' / 'settings.ini').write_text('x', encoding='utf-8')  # not ProjectTemp_*: never touched
    holders = [entry / 'model.jproj.tmp'] if held == 'live' else held
    monkeypatch.setattr(strayleaks, 'held_paths', lambda _prefixes: holders)
    found = [one for one in strayleaks.find([drive], home) if one.family.name == 'jmag-designer-temp']
    assert [one.path for one in found] == [entry]
    strayleaks.remove(found)
    assert entry.exists() is not removed
    assert (home / 'JMAGDesignerTemp' / 'settings.ini').is_file(), 'the tool dir and its other files stay'


def test_the_holder_reader_answers_on_this_host() -> None:
    """The real process reader runs: a path list, or the named reason it cannot tell (never a crash)."""
    assert isinstance(strayleaks.held_paths(('no-such-process-prefix',)), (list, str))
