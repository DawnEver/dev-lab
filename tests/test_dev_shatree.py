"""A local part's tree: detached AT the claimed sha, its own environment, removed after."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from _forge_fake import git_out, make_repo, run_git

from lab_commons.dev.platformparts import record_directory
from lab_commons.dev.shatree import TREE_PREFIX, TreeFailed, close_tree, open_tree, record_manifest, tree_path
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
    return subprocess.run(argv, check=bool(kwargs.pop('check', False)), **kwargs)


def test_the_tree_is_at_the_claimed_sha_whatever_the_checkout_holds(tmp_path: Path) -> None:
    """PLANTED (live 2026-10-12): the serving checkout sits at a LATER commit than the one claimed."""
    repo, claimed, later = _two_commits(tmp_path)
    assert git_out(repo, 'rev-parse', 'HEAD') == later
    tree = open_tree(repo, claimed, 'tests/base', run=_bootstrap_fakes)
    assert (
        tree.path
        == tree_path(repo, claimed, 'tests/base')
        == repo / '.claude' / 'worktrees' / f'{TREE_PREFIX}{claimed[:12]}-tests-base'
    )
    assert git_out(tree.path, 'rev-parse', 'HEAD') == claimed
    assert (tree.path / 'which').read_text(encoding='utf-8') == 'claimed'
    assert tree.python == tree.path / venv_interpreter(os_name=current_os_name())
    assert git_out(repo, 'rev-parse', 'HEAD') == later, 'the serving checkout is never moved'
    assert close_tree(repo, claimed, 'tests/base').startswith(f'tree {TREE_PREFIX}{claimed[:12]}-tests-base: removed; ')
    assert not tree.path.exists()
    assert close_tree(repo, claimed, 'tests/base').endswith('none to remove')


def test_a_step_that_refuses_is_named_and_a_missing_environment_too(tmp_path: Path) -> None:
    repo, claimed, _later = _two_commits(tmp_path)

    def refusing(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if '--bootstrap' in argv:
            return subprocess.CompletedProcess(argv, 1, 'resolving\n', 'no lock for extras\n')
        return subprocess.run(argv, check=bool(kwargs.pop('check', False)), **kwargs)

    with pytest.raises(TreeFailed, match=r'dep --bootstrap exited 1: resolving \| no lock for extras'):
        open_tree(repo, claimed, 'tests/base', run=refusing)

    def silent(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if '--bootstrap' in argv:
            return subprocess.CompletedProcess(argv, 0, '', '')
        return subprocess.run(argv, check=bool(kwargs.pop('check', False)), **kwargs)

    with pytest.raises(TreeFailed, match='no own environment'):
        open_tree(repo, claimed, 'tests/base', run=silent)
    close_tree(repo, claimed, 'tests/base')


def test_closing_keeps_the_run_record_and_the_log_in_the_serving_checkout(tmp_path: Path) -> None:
    """PLANTED (live 2026-10-12, dd30117): the windows record lived only in the tree, and went with it.

    The cluster keeps its record in the serving checkout's ``<output>/<yy>/<mm>/<dd>/parts/<sha>/``;
    a local producer must too, BEFORE the tree is removed.
    """
    repo, claimed, _later = _two_commits(tmp_path)
    (repo / 'pyproject.toml').write_text('[tool.lab_commons.parts]\noutput = "output/logs"\n', encoding='utf-8')
    run_git(repo, 'add', 'pyproject.toml')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'declare')
    claimed = git_out(repo, 'rev-parse', 'HEAD')
    tree = open_tree(repo, claimed, 'tests/base', run=_bootstrap_fakes)
    judged = record_directory(tree.path, claimed)
    judged.mkdir()
    (judged / 'run-x-windows.json.gz').write_bytes(b'\x1f\x8bpart')

    said = close_tree(repo, claimed, 'tests/base', log='collected 9\n1 failed\n')

    assert not tree.path.exists()
    kept = record_directory(repo, claimed)
    assert kept.relative_to(repo) == judged.relative_to(tree.path), 'the same place, in the serving checkout'
    assert (kept / 'run-x-windows.json.gz').read_bytes() == b'\x1f\x8bpart'
    (log,) = kept.glob('produce-*.log')
    assert log.read_text(encoding='utf-8') == 'collected 9\n1 failed\n'
    assert said.endswith(f'removed; record kept in {kept.relative_to(repo).as_posix()}')


def test_a_tree_declaring_no_record_home_is_still_removed_and_says_so(tmp_path: Path) -> None:
    repo, claimed, _later = _two_commits(tmp_path)
    tree = open_tree(repo, claimed, 'tests/base', run=_bootstrap_fakes)
    said = close_tree(repo, claimed, 'tests/base', log='x\n')
    assert not tree.path.exists()
    assert 'record NOT kept' in said
    assert 'tool.lab_commons.parts' in said


def test_a_record_manifest_names_where_it_is_kept_and_each_files_sha256(tmp_path: Path) -> None:
    repo, claimed, _later = _two_commits(tmp_path)
    (repo / 'pyproject.toml').write_text('[tool.lab_commons.parts]\noutput = "output/logs"\n', encoding='utf-8')
    run_git(repo, 'add', 'pyproject.toml')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'declare')
    claimed = git_out(repo, 'rev-parse', 'HEAD')
    tree = open_tree(repo, claimed, 'tests/base', run=_bootstrap_fakes)
    judged = record_directory(tree.path, claimed)
    judged.mkdir(parents=True)
    (judged / 'r.json').write_bytes(b'{}')
    kept, files = record_manifest(repo, claimed, 'tests/base')
    assert kept == judged.relative_to(tree.path).as_posix()
    assert files == (('r.json', hashlib.sha256(b'{}').hexdigest()),)
    close_tree(repo, claimed, 'tests/base')


def test_two_jobs_of_one_sha_each_own_a_tree(tmp_path: Path) -> None:
    """S4: a part and a request of one sha run side by side; removing one leaves the other."""
    repo, claimed, _later = _two_commits(tmp_path)
    part = open_tree(repo, claimed, 'tests/base', run=_bootstrap_fakes)
    request = open_tree(repo, claimed, 'request/9', run=_bootstrap_fakes)
    assert part.path != request.path
    assert request.path.name == f'{TREE_PREFIX}{claimed[:12]}-request-9'
    close_tree(repo, claimed, 'tests/base')
    assert request.path.exists()
    close_tree(repo, claimed, 'request/9')
