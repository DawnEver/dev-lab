"""A data dependency is pinned: declared once, synced to exactly its rev, a stale copy refused, relocked to its line."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import datadeps
from dev_lab.dev.gitenv import unlocated

if TYPE_CHECKING:
    from pathlib import Path


_GIT_EXE = shutil.which('git') or 'git'


def _git(cwd: Path, *argv: str) -> str:
    done = subprocess.run(
        [_GIT_EXE, '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@t', *argv],
        capture_output=True, text=True, encoding='utf-8', check=True, env=unlocated(),
    )  # fmt: skip
    return done.stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text, encoding='utf-8')
    _git(repo, 'add', name)
    _git(repo, 'commit', '-q', '-m', f'data: {name}')
    return _git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def library(tmp_path: Path) -> tuple[Path, str, str]:
    """A data repo on line ``integrate/main`` with two commits; (repo, first, second)."""
    repo = tmp_path / 'library'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'integrate/main')
    first = _commit(repo, 'a.toml', 'a = 1\n')
    second = _commit(repo, 'b.toml', 'b = 2\n')
    return repo, first, second


def _consumer(tmp_path: Path, url: str, rev: str) -> Path:
    root = tmp_path / 'consumer'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        f'[project]\nname = "consumer"\n\n# the pin\n[tool.dev_lab.data.recipes]\n'
        f'url = "{url}"\nline = "integrate/main"\nrev = "{rev}"\npath = "recipes"\n',
        encoding='utf-8',
    )
    return root


def test_sync_checks_out_exactly_the_pin_and_check_then_passes(tmp_path, library) -> None:
    repo, first, _ = library
    root = _consumer(tmp_path, repo.as_uri(), first)
    (dep,) = datadeps.declared(root)
    assert datadeps.stale(root, dep) is not None
    datadeps.sync(root, dep)
    assert _git(root / 'recipes', 'rev-parse', 'HEAD') == first
    assert not (root / 'recipes' / 'b.toml').exists()
    assert datadeps.stale(root, dep) is None
    assert datadeps.main(['check', '--root', str(root)]) == 0


def test_a_copy_at_another_commit_is_stale_and_named(tmp_path, library) -> None:
    """PLANTED: the copy here is the line head, the pin is the first commit -- the reader must refuse it."""
    repo, first, second = library
    root = _consumer(tmp_path, repo.as_uri(), first)
    _git(tmp_path, 'clone', '-q', repo.as_uri(), str(root / 'recipes'))
    (dep,) = datadeps.declared(root)
    reason = datadeps.stale(root, dep)
    assert reason is not None
    assert second in reason
    assert first in reason
    assert datadeps.SYNC in reason
    assert datadeps.main(['check', '--root', str(root)]) == 1


def test_a_copy_with_local_edits_is_refused_never_overwritten(tmp_path, library) -> None:
    repo, first, second = library
    root = _consumer(tmp_path, repo.as_uri(), first)
    _git(tmp_path, 'clone', '-q', repo.as_uri(), str(root / 'recipes'))
    (root / 'recipes' / 'b.toml').write_text('edited\n', encoding='utf-8')
    (dep,) = datadeps.declared(root)
    with pytest.raises(datadeps.DataRefused, match='local changes'):
        datadeps.sync(root, dep)
    assert (root / 'recipes' / 'b.toml').read_text(encoding='utf-8') == 'edited\n'
    assert _git(root / 'recipes', 'rev-parse', 'HEAD') == second


def test_relock_moves_the_pin_to_the_line_head_and_keeps_the_rest_of_the_file(tmp_path, library) -> None:
    repo, first, second = library
    root = _consumer(tmp_path, repo.as_uri(), first)
    assert datadeps.relock(root) == ('recipes',)
    text = (root / 'pyproject.toml').read_text(encoding='utf-8')
    assert f'rev = "{second}"' in text
    assert '# the pin' in text
    assert datadeps.relock(root) == ()


@pytest.mark.parametrize(
    ('row', 'refusal'),
    [
        ('url = "u"\nline = "l"\npath = "p"\n', 'lacks rev'),
        ('url = "u"\nline = "l"\nrev = "abc"\npath = "p"\n', 'not a full 40-hex'),
        (f'url = "u"\nline = "l"\nrev = "{"0" * 40}"\npath = "../out"\n', 'inside the repo'),
    ],
)
def test_a_malformed_declaration_is_refused(tmp_path, row, refusal) -> None:
    (tmp_path / 'pyproject.toml').write_text(f'[tool.dev_lab.data.x]\n{row}', encoding='utf-8')
    with pytest.raises(datadeps.DataRefused, match=refusal):
        datadeps.declared(tmp_path)


def test_a_repo_declaring_no_data_has_nothing_to_sync(tmp_path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    assert datadeps.declared(tmp_path) == ()
    assert datadeps.main(['check', '--root', str(tmp_path)]) == 0
