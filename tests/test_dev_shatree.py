"""A local part's tree: detached AT the claimed sha, its own environment, removed after."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _forge_fake import git_out, make_repo, run_git

from lab_commons.dev.shatree import TREE_PREFIX, TreeFailed, close_tree, open_tree, tree_path
from lab_commons.dev.venvpath import current_os_name, venv_interpreter


def _two_commits(tmp_path: Path) -> tuple[Path, str, str]:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    shas = []
    for text in ('claimed', 'later'):
        (repo / 'which').write_text(text, encoding='utf-8')
        run_git(repo, 'add', 'which')
        run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', text)
        shas.append(git_out(repo, 'rev-parse', 'HEAD'))
    return repo, shas[0], shas[1]


def _bootstrap_fakes(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Real git; the dependency door is faked by creating the interpreter it would build."""
    if '--bootstrap' in argv:
        python = Path(argv[-1]) / venv_interpreter(os_name=current_os_name())
        python.parent.mkdir(parents=True)
        python.write_text('', encoding='utf-8')
        return subprocess.CompletedProcess(argv, 0, '', '')
    return subprocess.run(argv, **kwargs)  # noqa: PLW1510 -- the caller passes check


def test_the_tree_is_at_the_claimed_sha_whatever_the_checkout_holds(tmp_path: Path) -> None:
    """PLANTED (live 2026-10-12): the serving checkout sits at a LATER commit than the one claimed."""
    repo, claimed, later = _two_commits(tmp_path)
    assert git_out(repo, 'rev-parse', 'HEAD') == later
    tree = open_tree(repo, claimed, run=_bootstrap_fakes)
    assert tree.path == tree_path(repo, claimed) == repo / '.claude' / 'worktrees' / f'{TREE_PREFIX}{claimed[:12]}'
    assert git_out(tree.path, 'rev-parse', 'HEAD') == claimed
    assert (tree.path / 'which').read_text(encoding='utf-8') == 'claimed'
    assert tree.python == tree.path / venv_interpreter(os_name=current_os_name())
    assert git_out(repo, 'rev-parse', 'HEAD') == later, 'the serving checkout is never moved'
    assert close_tree(repo, claimed) == f'tree {TREE_PREFIX}{claimed[:12]}: removed'
    assert not tree.path.exists()
    assert close_tree(repo, claimed).endswith('none to remove')


def test_a_step_that_refuses_is_named_and_a_missing_environment_too(tmp_path: Path) -> None:
    repo, claimed, _later = _two_commits(tmp_path)

    def refusing(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if '--bootstrap' in argv:
            return subprocess.CompletedProcess(argv, 1, 'resolving\n', 'no lock for extras\n')
        return subprocess.run(argv, **kwargs)  # noqa: PLW1510 -- the caller passes check

    with pytest.raises(TreeFailed, match=r'dep --bootstrap exited 1: resolving \| no lock for extras'):
        open_tree(repo, claimed, run=refusing)

    def silent(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if '--bootstrap' in argv:
            return subprocess.CompletedProcess(argv, 0, '', '')
        return subprocess.run(argv, **kwargs)  # noqa: PLW1510 -- the caller passes check

    with pytest.raises(TreeFailed, match='no own environment'):
        open_tree(repo, claimed, run=silent)
    close_tree(repo, claimed)
