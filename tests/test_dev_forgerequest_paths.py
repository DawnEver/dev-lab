"""D5: a box that cannot admit a selection OFFERS it -- the repository's test producer over validated paths.

Only producer ``tests`` takes paths, and each must be a ``.py`` test file that exists at the sha under the
declared test roots. PLANTED CONTROLS: a path outside the roots, a missing file and an argv-looking string
are each refused BY NAME; a valid selection runs the declared door over exactly those files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev.forgerequest import (
    TESTS,
    UndeclaredRequest,
    declared_request,
    parse_body,
    parse_paths,
    request_body,
)

_PYPROJECT = """
[tool.lab_commons.tests]
produce = ["-m", "dev_lab.dev.verify", "--part", "{part}"]

[tool.pytest.ini_options]
testpaths = ["tests"]
"""


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    """A committed repository with one test file under its declared root, and one file outside it."""
    run_git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text(_PYPROJECT, encoding='utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_a.py').write_text('def test_a():\n    pass\n', encoding='utf-8')
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools' / 'test_b.py').write_text('', encoding='utf-8')
    run_git(tmp_path, 'add', '-A')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'init')
    return tmp_path, git_out(tmp_path, 'rev-parse', 'HEAD')


def test_a_valid_selection_runs_the_declared_door_over_exactly_its_files(repo: tuple[Path, str]) -> None:
    root, sha = repo
    declared = declared_request(root, sha, TESTS, ('tests/test_a.py',))
    assert declared.argv == ('-m', 'dev_lab.dev.verify', '--', 'tests/test_a.py')
    assert declared.cpu > 0
    assert declared.mem_gb > 0
    assert declared.wall_h > 0


@pytest.mark.parametrize(
    ('path', 'named'),
    [
        ('tools/test_b.py', 'outside the declared test roots'),
        ('tests/test_missing.py', 'does not exist'),
        ('--deselect=x', 'looks like an option'),
        ('tests/*.py', 'glob'),
        ('../tests/test_a.py', 'leaves the repository'),
        ('tests/conftest.txt', 'not a test file'),
    ],
)
def test_each_bad_path_is_refused_by_name(repo: tuple[Path, str], path: str, named: str) -> None:
    root, sha = repo
    with pytest.raises(UndeclaredRequest, match=named):
        declared_request(root, sha, TESTS, ('tests/test_a.py', path))


def test_only_the_test_producer_takes_paths_and_it_needs_some(repo: tuple[Path, str]) -> None:
    root, sha = repo
    with pytest.raises(UndeclaredRequest, match='only producer'):
        declared_request(root, sha, 'femm_goldens', ('tests/test_a.py',))
    with pytest.raises(UndeclaredRequest, match='runs named test files'):
        declared_request(root, sha, TESTS)


def test_the_body_carries_the_paths_and_reads_them_back() -> None:
    body = request_body(TESTS, 'a' * 40, ('tests/test_a.py', 'tests/u/test_b.py'))
    assert parse_body(body) == (TESTS, 'a' * 40)
    assert parse_paths(body) == ('tests/test_a.py', 'tests/u/test_b.py')
    assert parse_paths(request_body('femm', 'a' * 40)) == (), 'a producer row request names no paths'


def test_a_request_at_a_sha_whose_manifest_the_kit_retires_is_refused_by_name(repo: tuple[Path, str]) -> None:
    """PLANTED (live 2026-10-28, Ada): a request pinned to a pre-A3 sha spells a moved table.

    The kit's RetiredTable escaped the serve on every tick, so no motronics part was claimed; it is refused
    per request instead.
    """
    root, _sha = repo
    (root / 'pyproject.toml').write_text(_PYPROJECT + '\n[tool.lab_commons.hooks]\n', encoding='utf-8')
    run_git(root, 'add', 'pyproject.toml')
    run_git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'old spelling')
    old = git_out(root, 'rev-parse', 'HEAD')
    with pytest.raises(UndeclaredRequest, match=r'retired'):
        declared_request(root, old, TESTS, ('tests/test_a.py',))
