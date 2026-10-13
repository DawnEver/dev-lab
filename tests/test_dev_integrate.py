"""``integrate merge`` / ``integrate promote``: integration by refs alone, over REAL repositories.

Every refusal has its planted control, and the working tree of the checkout running the verb is
asserted untouched -- integration needs none.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair, commit
from _forge_fake import Loopback, answer, client, git_out, run_git, serve

from lab_commons.dev import integrate
from lab_commons.dev.forge import Forge
from lab_commons.dev.integrate import IntegrateRefused, merge, promote
from lab_commons.dev.sessionbranch import merged_branch

GITEA = Forge('forge.example.org', 'o', 'r')
GAPI = '/api/v1/repos/o/r'
_TESTS = 'def test_a():\n    assert True\n\n\ndef test_b():\n    assert 1\n'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A clone with local ``integrate/main`` and a lane, both carrying a test file; HEAD on the lane."""
    _, repo = clone_pair(tmp_path)
    (repo / 'tests').mkdir()
    run_git(repo, 'checkout', '-q', '-B', 'integrate/main', 'origin/integrate/main')
    commit(repo, 'tests/test_a.py', _TESTS)
    run_git(repo, 'checkout', '-q', '-b', 'lane/x')
    return repo


def test_a_clean_merge_moves_the_integration_ref_and_touches_no_tree(work: Path) -> None:
    lane = commit(work, 'x.txt', 'x\n')
    old = git_out(work, 'rev-parse', 'integrate/main')
    sha = merge(work, 'lane/x')
    assert git_out(work, 'rev-parse', 'integrate/main') == sha
    assert git_out(work, 'rev-list', '--parents', '-n', '1', sha).split()[1:] == [old, lane]
    assert merged_branch(git_out(work, 'log', '-1', '--format=%B', sha)) == 'lane/x'
    assert git_out(work, 'status', '--porcelain') == ''
    assert git_out(work, 'symbolic-ref', '--short', 'HEAD') == 'lane/x'
    assert merge(work, 'lane/x') == sha, 'merging what is already merged changes nothing'


def test_a_conflict_is_refused_naming_the_file_and_moves_nothing(work: Path) -> None:
    commit(work, 'c.txt', 'lane\n')
    run_git(work, 'checkout', '-q', 'integrate/main')
    old = commit(work, 'c.txt', 'integration\n')
    run_git(work, 'checkout', '-q', 'lane/x')
    with pytest.raises(IntegrateRefused, match=r'conflicts in: c\.txt'):
        merge(work, 'lane/x')
    assert git_out(work, 'rev-parse', 'integrate/main') == old


def test_a_test_both_sides_changed_is_refused_until_named(work: Path) -> None:
    """Git merges the lines cleanly, but the test body is a human choice: the audit wants it named."""
    body = 'def test_d():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    assert a + b + c + d\n'
    commit(work, 'tests/test_d.py', body)
    run_git(work, 'checkout', '-q', 'integrate/main')
    run_git(work, 'merge', '-q', '--ff-only', 'lane/x')
    commit(work, 'tests/test_d.py', body.replace('a = 1', 'a = 10'))
    run_git(work, 'checkout', '-q', 'lane/x')
    commit(work, 'tests/test_d.py', body.replace('d = 4', 'd = 40'))
    with pytest.raises(IntegrateRefused, match='CONFLICTED test_d'):
        merge(work, 'lane/x')
    sha = merge(work, 'lane/x', audit=['CONFLICTED test_d -- both edits kept'])
    assert 'Merge-Audit: CONFLICTED test_d -- both edits kept' in git_out(work, 'log', '-1', '--format=%B', sha)


def test_a_merge_that_drops_nothing_needs_no_ledger_and_an_over_claim_is_refused(work: Path) -> None:
    commit(work, 'y.txt', 'y\n')
    with pytest.raises(IntegrateRefused, match='holds no such deviation'):
        merge(work, 'lane/x', audit=['LOST test_b -- claimed'])
    assert merge(work, 'lane/x')


def test_an_integration_branch_checked_out_somewhere_is_refused(work: Path) -> None:
    commit(work, 'x.txt', 'x\n')
    run_git(work, 'checkout', '-q', 'integrate/main')
    with pytest.raises(IntegrateRefused, match='checked out'):
        merge(work, 'lane/x')


def _part(scope: str = 'full') -> dict[str, object]:
    return {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': f'scope={scope} ran=3 hands=-'}


def test_promote_moves_only_the_local_trunk_and_only_on_full_parts(server, tmp_path: Path) -> None:
    """PLANTED both ways: an incremental part refuses; a full PASS fast-forwards the LOCAL ref; nothing pushed."""
    bare, repo = clone_pair(tmp_path)
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    built = client(GITEA, Loopback(server))
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part('incremental')]))
    assert promote(repo, built, tip).action == 'refused'
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part()]))
    assert promote(repo, built, tip).action == 'promote'
    assert git_out(repo, 'rev-parse', 'main') == tip
    assert git_out(bare, 'rev-parse', 'main') != tip, 'promote never pushes'
    assert promote(repo, built, tip).action == 'current'


def test_promote_refuses_a_sha_off_integration_and_a_trunk_that_cannot_fast_forward(server, tmp_path: Path) -> None:
    _, repo = clone_pair(tmp_path)
    advance(repo, 'main', 'hotfix.txt', 'h\n')
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    built = client(GITEA, Loopback(server))
    found = promote(repo, built, tip)
    assert found.action == 'refused'
    assert 'cannot fast-forward' in found.reasons[0]
    stray = git_out(repo, 'commit-tree', 'HEAD^{tree}', '-m', 'stray')
    assert 'not a commit of origin/integrate/main' in promote(repo, built, stray).reasons[0]


def test_the_cli_exits_two_on_a_refusal(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_git(work, 'checkout', '-q', 'integrate/main')
    assert integrate.main(['merge', 'lane/x'], cwd=work) == 2
    assert 'REFUSED' in capsys.readouterr().err


_RETIRED = '[tool.lab_commons.integrator]\nhost = "G"\n'


def test_merge_reads_the_merged_tree_never_the_working_tree(work: Path) -> None:
    """THE CUT-OVER INCIDENT (2026-10-14): a working tree on an old commit carried the retired ``host`` key.

    PLANTED CONTROL: the same retired key committed on the branch -- so the merged tree declares it -- refuses.
    """
    commit(work, 'x.txt', 'x\n')
    (work / 'pyproject.toml').write_text('not [toml\n' + _RETIRED, encoding='utf-8')
    assert merge(work, 'lane/x')
    commit(work, 'pyproject.toml', _RETIRED)
    with pytest.raises(IntegrateRefused, match='host is retired'):
        merge(work, 'lane/x')


def test_promote_reads_the_promoted_sha_never_the_working_tree(server, tmp_path: Path) -> None:
    _, repo = clone_pair(tmp_path)
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    (repo / 'pyproject.toml').write_text('not [toml\n' + _RETIRED, encoding='utf-8')
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part()]))
    assert promote(repo, client(GITEA, Loopback(server)), tip).action == 'promote'
