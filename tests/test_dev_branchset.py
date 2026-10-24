"""ONE-BRANCH-PER-SESSION, driven on REAL repositories with a REAL bare origin.

The declaration, the census, the merge-and-delete candidates and the famtest are each driven against
a planted repository, clean side first, so a guard that refuses everything cannot pass here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.branchset import (
    BranchSet,
    BranchSetNotDeclared,
    branchset_from,
    census,
    declared_branchset,
    main,
    merge_candidates,
)
from dev_lab.dev.famtests.branchset import (
    BranchSetViolation,
    assert_local_branches_declared,
    assert_origin_branches_declared,
    assert_the_planted_branchset_is_policed,
)
from dev_lab.dev.famtests.visibility import commit, plant_checkout

_GIT = shutil.which('git') or 'git'
_DECLARED = BranchSet(trunk='main', sessions=frozenset({'feat/session'}))


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _manifest(root: Path, body: str) -> Path:
    (root / 'pyproject.toml').write_text(body, encoding='utf-8')
    return root


def test_the_declaration_is_read_from_the_manifest(tmp_path: Path) -> None:
    root = _manifest(tmp_path, "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['feat/a']\n")
    assert declared_branchset(root) == BranchSet('main', frozenset({'feat/a'}), ephemeral=('pr/*',))
    assert declared_branchset(root).declared == frozenset({'main', 'feat/a'})


@pytest.mark.parametrize(
    'body',
    [
        '',
        '[tool.lab_commons.branchset]\nsessions = []\n',
        "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = 'x'\n",
    ],
)
def test_an_undeclared_or_malformed_set_is_refused(tmp_path: Path, body: str) -> None:
    with pytest.raises(BranchSetNotDeclared):
        declared_branchset(_manifest(tmp_path, body))


def test_a_clean_checkout_reads_clean_and_planted_debris_is_named(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    clean = census(work, _DECLARED)
    assert clean is not None
    assert (clean.undeclared_origin, clean.local_debt, clean.unpushed) == ((), (), ())

    _run(work, 'switch', '-q', '-c', 'feat/session')
    _run(work, 'push', '-q', 'origin', 'feat/session')
    _run(work, 'switch', '-q', '-c', 'feat/stray')
    commit(work, 'stray.txt')
    _run(work, 'push', '-q', 'origin', 'feat/stray')
    _run(work, 'switch', '-q', 'main')
    _run(work, 'branch', 'merged')
    _run(work, 'switch', '-q', '-c', 'wip')
    commit(work, 'wip.txt')
    _run(work, 'switch', '-q', 'main')

    found = census(work, _DECLARED)
    assert found is not None
    assert found.undeclared_origin == ('feat/stray',)
    assert found.local_debt == ('feat/stray', 'merged')
    assert found.unpushed == ('wip',)
    with pytest.raises(BranchSetViolation, match='feat/stray'):
        assert_origin_branches_declared(root=work, branchset=_DECLARED)
    with pytest.raises(BranchSetViolation, match='feat/stray'):
        assert_local_branches_declared(root=work, branchset=_DECLARED)


def test_unpushed_work_is_reported_and_never_a_red(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'switch', '-q', '-c', 'wip')
    commit(work, 'wip.txt')
    assert assert_local_branches_declared(root=work, branchset=_DECLARED) == ('wip',)


def test_a_candidate_is_deletable_only_when_the_trunk_or_a_session_branch_holds_its_tip(tmp_path: Path) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'switch', '-q', '-c', 'feat/session')
    _run(work, 'switch', '-q', '-c', 'folded')
    commit(work, 'folded.txt')
    _run(work, 'switch', '-q', 'feat/session')
    _run(work, 'merge', '-q', '--ff-only', 'folded')
    _run(work, 'switch', '-q', '-c', 'open', 'main')
    commit(work, 'open.txt')
    _run(work, 'switch', '-q', 'main')
    _run(work, 'branch', 'landed')

    rows = {(row.name, row.where): row.deletable for row in merge_candidates(work, _DECLARED) or ()}
    assert rows == {('folded', 'local'): True, ('landed', 'local'): True, ('open', 'local'): False}


def test_the_cli_lists_the_candidates_from_the_declaration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work = plant_checkout(tmp_path, trunk='main').work
    _manifest(work, "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = []\n")
    _run(work, 'branch', 'landed')
    assert main(['--root', str(work)]) == 0
    assert 'delete  local   landed' in capsys.readouterr().out


def test_the_shipped_planted_control_passes(tmp_path: Path) -> None:
    assert_the_planted_branchset_is_policed(tmp_path, trunk='main')


@pytest.mark.workstation
def test_this_repo_carries_only_its_declared_branches() -> None:
    """lab-commons adopts its own rule: origin carries exactly its declared set, ephemeral namespaces included."""
    root = Path(__file__).resolve().parents[1]
    declared = declared_branchset(root)
    assert_origin_branches_declared(root=root, branchset=declared)
    found = census(root, declared)
    assert found is not None
    assert found.undeclared_origin == ()


def test_two_open_ephemeral_heads_pass_and_an_undeclared_branch_still_reds(tmp_path: Path) -> None:
    """Two open ``pr/*`` heads are declared by the namespace; PLANTED control: an unmerged ``feat/*`` reds."""
    work = plant_checkout(tmp_path, trunk='main').work
    for name in ('pr/one', 'pr/two', 'feat/stray'):
        _run(work, 'switch', '-q', '-c', name, 'main')
        commit(work, f'{name.replace("/", "-")}.txt')
        _run(work, 'push', '-q', 'origin', name)
    _run(work, 'switch', '-q', 'main')
    with_stray = BranchSet('main', _DECLARED.sessions | {'feat/stray'}, ephemeral=('pr/*',))
    assert assert_origin_branches_declared(root=work, branchset=with_stray) == ()
    without_stray = BranchSet('main', _DECLARED.sessions, ephemeral=('pr/*',))
    with pytest.raises(BranchSetViolation, match='feat/stray'):
        assert_origin_branches_declared(root=work, branchset=without_stray)


def test_an_omitted_ephemeral_is_the_family_pr_namespace_and_an_empty_list_opts_out() -> None:
    """``pr/*`` is the family's PR-head namespace, ruled once here rather than repeated in every manifest."""
    head = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\n"
    assert branchset_from(head, 'p').ephemeral == ('pr/*',)
    assert branchset_from(head + 'ephemeral = []\n', 'p').ephemeral == ()


def test_an_ephemeral_glob_is_declared_and_a_malformed_one_refused(tmp_path: Path) -> None:
    """The census reads an ephemeral-namespace branch as declared; a non-list is refused by name.

    PLANTED control: the same origin branch is debt to a set declaring no namespace.
    """
    head = "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\n"
    found = branchset_from(head + "ephemeral = ['pr/*']\n", 'p')
    assert found.ephemeral == ('pr/*',)
    assert found.admits('pr/fix-3')
    assert not found.admits('feat/x')
    assert not found.is_ephemeral('integrate/main')
    with pytest.raises(BranchSetNotDeclared, match='ephemeral'):
        branchset_from(head + "ephemeral = 'pr/*'\n", 'p')
    work = plant_checkout(tmp_path, trunk='main').work
    _run(work, 'switch', '-q', '-c', 'pr/topic')
    commit(work, 'topic.txt')
    _run(work, 'push', '-q', 'origin', 'pr/topic')
    _run(work, 'switch', '-q', 'main')
    with_ns = BranchSet('main', _DECLARED.sessions, ephemeral=('pr/*',))
    read = census(work, with_ns)
    assert read is not None
    assert (read.undeclared_origin, read.local_debt) == ((), ())
    control = census(work, _DECLARED)
    assert control is not None
    assert control.undeclared_origin == ('pr/topic',)
