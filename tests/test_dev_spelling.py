"""US-SPELLING-IS-CHECKED: ``verify`` runs typos, in locale en-us, over every checked file of the tree.

User ruling 2026-11-24 (v1-migration D35): the family spells US English. The config is ONE file dev-lab ships
(:data:`~dev_lab.dev.spelling.CONFIG`), never a per-repo copy; dated memory written before the ruling is
history and stays as written (:data:`~dev_lab.dev.spelling.MEMORY_CUTOFF`).
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tomllib
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from dev_lab.dev import spelling, verifysteps
from dev_lab.dev.reports import read_lint

_GIT = shutil.which('git') or 'git'


def _repo(at: Path, files: dict[str, str]) -> Path:
    at.mkdir(parents=True)
    subprocess.run([_GIT, 'init', '-q', str(at)], check=True, capture_output=True, timeout=60)
    for name, text in files.items():
        path = at / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    _track(at)
    return at


def _track(root: Path) -> None:
    subprocess.run([_GIT, '-C', str(root), 'add', '-A'], check=True, capture_output=True, timeout=60)


def test_only_tracked_files_are_checked(tmp_path: Path) -> None:
    """Issue #995: an untracked artifact (a bootstrap's egg-info) is never scanned; tracked, it still reds."""
    root = _repo(tmp_path / 'r', {'notes.md': 'the color\n'})
    (root / 'pkg.egg-info').mkdir()
    (root / 'pkg.egg-info' / 'notes.txt').write_text('the colour\n', encoding='utf-8')  # spelling-ignore-line
    assert _check(root) == spelling.CLEAN
    _track(root)
    assert _check(root) == spelling.FOUND


def _check(root: Path) -> int:
    return spelling.check(root, handle=io.StringIO())


# spelling-off
@pytest.mark.parametrize('word', ['behaviour', 'colour'])
def test_planted_british_spelling_fails(tmp_path: Path, word: str) -> None:
    """PLANTED CONTROL: the step can say no, to a British spelling in prose and in a file name."""
    assert _check(_repo(tmp_path / 'r', {'notes.md': f'the {word} of the tree\n'})) == spelling.FOUND
    assert _check(_repo(tmp_path / 'n', {f'{word}_map.py': 'x = 1\n'})) == spelling.FOUND


def test_us_spelling_passes(tmp_path: Path) -> None:
    assert _check(_repo(tmp_path / 'r', {'notes.md': 'the behavior and color of the tree\n'})) == spelling.CLEAN


def test_memory_dated_before_the_cutoff_is_history_and_unchecked(tmp_path: Path) -> None:
    day = spelling.MEMORY_CUTOFF
    old = f'.claude/memory/{day.year}/{day.month:02}/{day.day - 1:02}/entry.md'
    new = f'.claude/memory/{day.year}/{day.month:02}/{day.day:02}/entry.md'
    assert _check(_repo(tmp_path / 'old', {old: 'the colour\n'})) == spelling.CLEAN
    assert _check(_repo(tmp_path / 'new', {new: 'the colour\n'})) == spelling.FOUND
    assert spelling.checked((old, new, 'src/a.py')) == (new, 'src/a.py')


def test_a_marked_block_is_not_checked(tmp_path: Path) -> None:
    """The door for DATA that names a foreign spelling (a unit token, a retired-name registry)."""
    text = '# spelling-off\nbehaviour\n# spelling-on\ncolour = 1  # spelling-ignore-line\n'
    assert _check(_repo(tmp_path / 'r', {'a.py': text})) == spelling.CLEAN


# spelling-on


def test_the_cutoff_is_the_ruling_date() -> None:
    assert date(2026, 11, 24) == spelling.MEMORY_CUTOFF


def test_the_one_config_is_us_english() -> None:
    config = tomllib.loads(spelling.CONFIG.read_text(encoding='utf-8'))
    assert config['default']['locale'] == 'en-us'


def test_verify_runs_the_spelling_step() -> None:
    assert ('typos', ('dev_lab.dev.spelling',)) in verifysteps.LINT_STEPS


def test_a_missing_binary_names_its_door(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spelling, 'binary', lambda: None)
    handle = io.StringIO()
    assert spelling.check(_repo(tmp_path / 'r', {'a.md': 'x\n'}), handle=handle) == spelling.ERRORED
    assert 'dev_lab.dev.dep --sync' in handle.getvalue()
    assert read_lint('typos', spelling.ERRORED).truncated, 'an errored checker is not a clean tree'


# spelling-off
def test_a_binary_golden_survives_write_byte_identical(tmp_path: Path) -> None:
    """PLANTED CONTROL: --write never touches a binary; an .npz carrying a British word survives byte for byte."""
    root = _repo(tmp_path / 'r', {'notes.md': 'the colour\n'})
    golden = root / 'tests' / 'goldens' / 'behaviour.npz'
    golden.parent.mkdir(parents=True)
    np.savez(golden, colour=np.array(['behaviour colour']))
    before = golden.read_bytes()
    assert spelling.check(root, handle=io.StringIO(), write=True) != spelling.ERRORED
    assert golden.read_bytes() == before
    assert (root / 'notes.md').read_text(encoding='utf-8') == 'the color\n'


def test_a_binary_of_any_extension_is_never_handed_to_typos(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'r', {})
    blob = root / 'data.bin'
    blob.write_bytes(b'colour\0behaviour colour\n')
    before = blob.read_bytes()
    assert spelling.check(root, handle=io.StringIO(), write=True) == spelling.CLEAN
    assert blob.read_bytes() == before


@pytest.mark.parametrize('name', ['fixtures/cases.jsonl', '.claude/hooks/deny-rules.json'])
def test_declared_data_is_neither_checked_nor_written(tmp_path: Path, name: str) -> None:
    """The config's excludes hold for the explicit file list too: data and rendered machine data stay as written."""
    root = _repo(tmp_path / 'r', {name: '{"colour": "behaviour"}\n'})
    assert spelling.check(root, handle=io.StringIO(), write=True) == spelling.CLEAN
    assert (root / name).read_text(encoding='utf-8') == '{"colour": "behaviour"}\n'


def test_a_checked_path_beside_the_excluded_still_reds(tmp_path: Path) -> None:
    """PLANTED CONTROL: the excludes are paths, not a checker that stopped reading."""
    root = _repo(tmp_path / 'r', {'fixtures/cases.jsonl': 'colour\n', 'fixtures/cases.json': 'colour\n'})
    out = io.StringIO()
    assert spelling.check(root, handle=out) == spelling.FOUND
    assert 'cases.json:' in out.getvalue()
    assert 'cases.jsonl' not in out.getvalue()


# spelling-on


def test_a_cited_author_is_a_word() -> None:
    config = tomllib.loads(spelling.CONFIG.read_text(encoding='utf-8'))
    assert config['default']['extend-words']['Mak'] == 'Mak'


@pytest.mark.parametrize(
    'line',
    [
        'MOR: model order reduction keeps the slow modes',
        'commutated drives switch the phase current at each sector',
        'the rotor passes two criticals before the rated speed',
    ],
)
def test_a_domain_term_is_a_word(tmp_path: Path, line: str) -> None:
    """2026-11-26: typos read MOR as MORE, commutated as commuted, criticals as critical; each is a domain term.

    PLANTED CONTROL: the same note with a real misspelling still reds, so the pass is the word list, not a blind step.
    """
    assert _check(_repo(tmp_path / 'r', {'notes.md': f'{line}\n'})) == spelling.CLEAN
    misspelled = f'{line} and teh rest\n'  # spelling-ignore-line
    assert _check(_repo(tmp_path / 'n', {'notes.md': misspelled})) == spelling.FOUND
