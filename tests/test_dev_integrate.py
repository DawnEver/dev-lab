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
