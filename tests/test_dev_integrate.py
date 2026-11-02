"""``integrate promote``: the trunk moves by refs alone, over REAL repositories.

The INTEGRATION branch is not moved from a client at all: the forge merges a green pull request server side
(:mod:`dev_lab.dev.forgemerge`). So this module holds the one verb a client still has -- the trunk's
fast-forward -- and the refusal of the verb that used to merge.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import Loopback, answer, client, git_out, run_git, serve

from dev_lab.dev import integrate
from dev_lab.dev.forge import Forge
from dev_lab.dev.integrate import promote

GITEA = Forge('forge.example.org', 'o', 'r')
GAPI = '/api/v1/repos/o/r'
_RETIRED = '[tool.dev_lab.integrator]\nhost = "G"\n'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


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


def test_promote_takes_a_full_pass_ancestor_of_integration_not_only_its_tip(server, tmp_path: Path) -> None:
    """D111: integration moves faster than a run finishes, so the newest full-PASS sha is usually an ANCESTOR.

    Promote fast-forwards the trunk to it while the tip still has no verdict. PLANTED CONTROL: the tip, with
    no full part, is refused.
    """
    _, repo = clone_pair(tmp_path)
    passed = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    tip = advance(repo, 'integrate/main', 'g.txt', 'g\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    built = client(GITEA, Loopback(server))
    answer('GET', f'{GAPI}/statuses/{passed}', (200, [_part()]))
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part('incremental')]))
    assert promote(repo, built, tip).action == 'refused'
    assert promote(repo, built, passed).action == 'promote'
    assert git_out(repo, 'rev-parse', 'main') == passed


def test_promote_reads_the_promoted_sha_never_the_working_tree(server, tmp_path: Path) -> None:
    _, repo = clone_pair(tmp_path)
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    (repo / 'pyproject.toml').write_text('not [toml\n' + _RETIRED, encoding='utf-8')
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part()]))
    assert promote(repo, client(GITEA, Loopback(server)), tip).action == 'promote'


def test_the_client_has_no_verb_that_moves_the_integration_branch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """INTEGRATION-TAKES-ONLY-FORGE-MERGES: the forge merges a PR; a client that asks to merge is refused argv."""
    with pytest.raises(SystemExit) as left:
        integrate.main(['merge', 'lane/x'], cwd=tmp_path)
    assert left.value.code == 2
    assert 'invalid choice' in capsys.readouterr().err


def test_pending_says_whether_the_trunk_still_lacks_the_sha_so_a_promoted_tip_runs_no_nightly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D48-1A: the nightly run tests and promotes integration's tip only while the trunk lacks it.

    PLANTED both ways: a tip ahead of main is pending; once main is fast-forwarded onto it, it is not.
    """
    _, repo = clone_pair(tmp_path)
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    assert integrate.main(['pending', tip], cwd=repo, fetch=lambda _: None) == 0
    assert capsys.readouterr().out.strip() == 'pending=true'
    run_git(repo, 'branch', '-f', 'main', tip)
    assert integrate.main(['pending', tip], cwd=repo, fetch=lambda _: None) == 0
    assert capsys.readouterr().out.strip() == 'pending=false'
