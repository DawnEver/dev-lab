"""The crate pin and the Python lock name ONE revision of a sibling built both ways: every arm planted."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from dev_lab.dev.famtests.cratepin import CratePinDrift, assert_the_crate_builds_the_locked_revision, pin_problems

if TYPE_CHECKING:
    from pathlib import Path

_SHA: Final = '842b9a0c7714dd206d9250352d030b6f00e148cb'
_OTHER: Final = '0123456789abcdef0123456789abcdef01234567'
_URL: Final = 'https://example.invalid/owner/numerics-lab.git'
_MANIFEST: Final = 'rust/Cargo.toml'
_KEYS: Final = {'manifest': _MANIFEST, 'crate': 'numerics', 'package': 'numerics-lab'}


def _lock(sha: str = _SHA, source: str | None = None) -> str:
    src = source if source is not None else f'{{ git = "{_URL}#{sha}" }}'
    return f'version = 1\n\n[[package]]\nname = "numerics-lab"\nversion = "0.1.0"\nsource = {src}\n'


def _cargo(entry: str, table: str = 'workspace.dependencies') -> str:
    return f'[workspace]\nmembers = []\n\n[{table}]\nnumerics = {entry}\n'


def _tree(root: Path, *, lock: str | None, cargo: str | None) -> Path:
    if lock is not None:
        (root / 'uv.lock').write_text(lock, encoding='utf-8')
    if cargo is not None:
        (root / 'rust').mkdir()
        (root / _MANIFEST).write_text(cargo, encoding='utf-8')
    return root


def test_one_revision_both_ways_passes(tmp_path: Path) -> None:
    """The control: the same commit in both locks is clean, from the workspace table or a crate's own."""
    root = _tree(tmp_path, lock=_lock(), cargo=_cargo(f'{{ git = "{_URL}", rev = "{_SHA}" }}'))
    assert pin_problems(root, **_KEYS) == ()
    assert_the_crate_builds_the_locked_revision(root, **_KEYS)
    (root / _MANIFEST).write_text(_cargo(f'{{ git = "{_URL}", rev = "{_SHA}" }}', 'dependencies'), encoding='utf-8')
    assert pin_problems(root, **_KEYS) == ()


def test_planted_a_cargo_rev_behind_the_lock_is_named_with_the_rev_to_set(tmp_path: Path) -> None:
    """THE PROPERTY: a relock moved uv.lock and left the crate on the old commit."""
    root = _tree(tmp_path, lock=_lock(), cargo=_cargo(f'{{ git = "{_URL}", rev = "{_OTHER}" }}'))
    (problem,) = pin_problems(root, **_KEYS)
    assert _OTHER in problem, problem
    assert f'rev = "{_SHA}"' in problem, 'the remedy names the revision to set'
    with pytest.raises(CratePinDrift, match=_SHA):
        assert_the_crate_builds_the_locked_revision(root, **_KEYS)


@pytest.mark.parametrize(
    ('entry', 'why'),
    [
        (f'{{ git = "{_URL}", branch = "main" }}', 'pins no rev'),
        (f'{{ git = "{_URL}", rev = "{_SHA[:12]}" }}', 'not a full 40-hex commit'),
        ('"0.1.0"', 'not a git dependency'),
    ],
)
def test_planted_a_crate_pin_that_names_no_commit_is_refused(tmp_path: Path, entry: str, why: str) -> None:
    """A branch moves, a short rev is ambiguous, a registry version is another source: none is one commit."""
    root = _tree(tmp_path, lock=_lock(), cargo=_cargo(entry))
    (problem,) = pin_problems(root, **_KEYS)
    assert why in problem, problem


def test_planted_the_crate_absent_from_the_manifest_is_named(tmp_path: Path) -> None:
    root = _tree(tmp_path, lock=_lock(), cargo='[workspace]\nmembers = []\n')
    (problem,) = pin_problems(root, **_KEYS)
    assert 'declares no numerics dependency' in problem, problem


def test_planted_the_package_not_git_locked_is_named(tmp_path: Path) -> None:
    """The lock half: no row, or a registry row, pins no commit for the crate to agree with."""
    registry = _tree(tmp_path, lock=_lock(source='{ registry = "https://pypi.org/simple" }'), cargo=_cargo('"0"'))
    assert any('uv.lock pins no numerics-lab commit' in p for p in pin_problems(registry, **_KEYS))


@pytest.mark.parametrize('missing', ['uv.lock', _MANIFEST])
def test_planted_a_missing_file_refuses_rather_than_passing(tmp_path: Path, missing: str) -> None:
    """An absent file is never agreement: the opt-in said both halves exist."""
    root = _tree(
        tmp_path,
        lock=None if missing == 'uv.lock' else _lock(),
        cargo=None if missing == _MANIFEST else _cargo(f'{{ git = "{_URL}", rev = "{_SHA}" }}'),
    )
    assert any(missing in problem for problem in pin_problems(root, **_KEYS)), pin_problems(root, **_KEYS)
