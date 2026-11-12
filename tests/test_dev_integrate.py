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
from dev_lab.dev.verdictenv import verdict_policy_at

GITEA = Forge('forge.example.org', 'o', 'r')
GAPI = '/api/v1/repos/o/r'
_INTEGRATOR = '[tool.dev_lab.integrator]\ntrunk = "main"\nintegration = "integrate/main"\n\n'
_RETIRED = '[tool.dev_lab.integrator]\nhost = "G"\n'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


_ENV = '0123abcd'


def _part(
    repo: Path,
    sha: str,
    scope: str = 'full',
    *,
    env: str = _ENV,
    policy: str | None = None,
    state: str = 'success',
    part: str = 'base',
    ident: int = 1,
    tail: str = '',
) -> dict[str, object]:
    """A settled ``tests/<part>`` as the forge lists it; its policy is the one *sha* declares unless named."""
    policy = verdict_policy_at(repo, sha) if policy is None else policy
    named = (f' env={env}' if env else '') + (f' policy={policy}' if policy else '')
    description = f'scope={scope} ran=3 hands=-{named}{tail}'
    return {'id': ident, 'context': f'tests/{part}', 'status': state, 'description': description}


def test_promote_moves_only_the_local_trunk_and_only_on_full_parts(server, tmp_path: Path) -> None:
    """PLANTED both ways: an incremental part refuses; a full PASS fast-forwards the LOCAL ref; nothing pushed."""
    bare, repo = clone_pair(tmp_path)
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    built = client(GITEA, Loopback(server))
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip, 'incremental')]))
    assert promote(repo, built, tip).action == 'refused'
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip)]))
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
    answer('GET', f'{GAPI}/statuses/{passed}', (200, [_part(repo, passed)]))
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip, 'incremental')]))
    assert promote(repo, built, tip).action == 'refused'
    assert promote(repo, built, passed).action == 'promote'
    assert git_out(repo, 'rev-parse', 'main') == passed


def test_promote_reads_the_promoted_sha_never_the_working_tree(server, tmp_path: Path) -> None:
    _, repo = clone_pair(tmp_path)
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    (repo / 'pyproject.toml').write_text('not [toml\n' + _RETIRED, encoding='utf-8')
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip)]))
    assert promote(repo, client(GITEA, Loopback(server)), tip).action == 'promote'


def _ready(tmp_path: Path, pyproject: str = '') -> tuple[Path, str]:
    _, repo = clone_pair(tmp_path)
    if pyproject:
        advance(repo, 'integrate/main', 'pyproject.toml', pyproject)
    tip = advance(repo, 'integrate/main', 'f.txt', 'f\n')
    run_git(repo, 'checkout', '-q', '--detach')
    run_git(repo, 'branch', '-f', 'main', 'origin/main')
    return repo, tip


def test_a_second_post_in_another_env_does_not_overwrite_the_first(server, tmp_path: Path) -> None:
    """CONTRACT 1: (part, env, policy) is the fact. A FAIL in env A stays a fact after a PASS in env B lands.

    PLANTED CONTROL: the same PASS re-posted in env A (replacing A's FAIL, its own key) promotes.
    """
    repo, tip = _ready(tmp_path)
    built = client(GITEA, Loopback(server))
    fail_a = _part(repo, tip, env='aaaaaaaa', state='failure', ident=1)
    pass_b = _part(repo, tip, env='bbbbbbbb', ident=2)
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [fail_a, pass_b]))
    found = promote(repo, built, tip)
    assert found.action == 'refused', 'the later PASS in env B overwrote the FAIL in env A'
    assert 'FAIL' in found.reasons[0]
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [fail_a, pass_b, _part(repo, tip, env='aaaaaaaa', ident=3)]))
    assert promote(repo, built, tip).action == 'promote'


def test_a_declared_required_part_never_posted_refuses_promotion(server, tmp_path: Path) -> None:
    """CONTRACT 2: the required set is DECLARED, not derived from what was posted.

    PLANTED CONTROL: posting the declared part promotes.
    """
    repo, tip = _ready(tmp_path, _INTEGRATOR + '[tool.dev_lab.parts]\nrequired = ["windows"]\n')
    built = client(GITEA, Loopback(server))
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip)]))
    found = promote(repo, built, tip)
    assert found.action == 'refused'
    assert any('missing the required windows part' in reason for reason in found.reasons), found.reasons
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip), _part(repo, tip, part='windows', ident=2)]))
    assert promote(repo, built, tip).action == 'promote'


def test_a_part_of_another_policy_or_naming_no_env_refuses_promotion(server, tmp_path: Path) -> None:
    """CONTRACT 2: a PASS counts only under the policy the promoted commit declares, and names its env.

    A carried PASS keeps its SOURCE run's env and policy, so one judged in another declared env (another
    lock, another policy) refuses. PLANTED CONTROL: the same carried PASS of this policy promotes.
    """
    repo, tip = _ready(tmp_path)
    built = client(GITEA, Loopback(server))
    carried = ' carried from 0123456789ab: docs-only'
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip, policy='ffffffff', tail=carried)]))
    found = promote(repo, built, tip)
    assert found.action == 'refused'
    assert any('missing the required base part of policy' in reason for reason in found.reasons), found.reasons
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip, env='', tail=carried)]))
    assert any('names no env' in reason for reason in promote(repo, built, tip).reasons)
    answer('GET', f'{GAPI}/statuses/{tip}', (200, [_part(repo, tip, tail=carried)]))
    assert promote(repo, built, tip).action == 'promote'


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
