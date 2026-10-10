"""REQUESTS AND CLAIMS: origin is the trigger, a pending status is the claim, a stale lease is retaken.

The race and the lease are decided from the forge's own post order, so they are tested on that order
(pure :func:`assess`) and end to end against a REAL loopback forge and a REAL git repository.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from lab_commons.dev import forgetick
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.forgetick import (
    CLAIMED,
    DONE,
    HELD,
    MINE,
    OPEN,
    STALE,
    Claim,
    Serving,
    assess,
    requests,
    serving,
    tick,
)
from lab_commons.dev.lanepolicy import Policy
from lab_commons.hpc.grants import Grant, workstation

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=6)
ME = Claim('G', 'alice', LATER)
API = '/api/v1/repos/o/r'
GRANT = Grant(user='alice', hosts=('login.ada',), slurm_account='acct42', cpus=4)


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


def _pending(claim: Claim, status_id: int, platform: str = 'windows') -> Status:
    return Status(f'tests/{platform}', 'pending', claim.description(), '', status_id, claim.login)


WINDOWS = Serving('windows')


def _assess(
    history: list[Status], serve: Serving = WINDOWS, hpc_ids: frozenset[str] = frozenset()
) -> tuple[str, Claim | None]:
    return assess(history, serve, me=ME, now=NOW, hpc_ids=hpc_ids)


def test_a_claim_round_trips_through_its_description() -> None:
    cluster = Claim('', 'bob', LATER, 'bob:acct42')
    assert cluster.description() == 'claim machine=- login=bob until=2026-10-10T18:00:00Z hpc=bob:acct42'
    assert Claim.parse(cluster.description()) == cluster
    assert Claim.parse('scope=full ran=1 hands=- nowhere=0') is None
    assert Claim.parse('claim machine=G login=a until=not-a-time hpc=-') is None


def test_no_post_is_open_a_settled_part_is_done_and_my_live_claim_is_mine() -> None:
    assert _assess([]) == (OPEN, None)
    assert _assess([Status('tests/linux', 'success', 'x', '', 1)]) == (OPEN, None), 'another platform is not mine'
    assert _assess([_pending(ME, 1), Status('tests/windows', 'failure', 'scope=full', '', 2)]) == (DONE, None)
    assert _assess([_pending(ME, 1)]) == (MINE, ME)


def test_the_earliest_live_claim_wins_the_race() -> None:
    """PLANTED CONTROL: two claims posted at once -- both claimants read the same order, one proceeds."""
    bob = Claim('H', 'bob', LATER)
    assert _assess([_pending(bob, 4), _pending(ME, 5)]) == (CLAIMED, bob)
    assert _assess([_pending(ME, 4), _pending(bob, 5)]) == (MINE, ME)
    same_login_other_machine = Claim('H', 'alice', LATER)
    assert _assess([_pending(same_login_other_machine, 4)])[0] == CLAIMED, 'one account, two machines: two claimants'


def test_a_stale_local_claim_is_retaken_by_anyone_serving_the_platform() -> None:
    """PLANTED CONTROL: the claimant died mid-run; its lease lapsed."""
    dead = Claim('H', 'bob', NOW - timedelta(minutes=1))
    assert _assess([_pending(dead, 3)]) == (STALE, dead)


def test_a_stale_cluster_claim_is_retaken_only_under_the_same_grant() -> None:
    """The jobs keep running under the claimant's account; only that grant's holder can gather them."""
    dead = Claim('H', 'alice', NOW - timedelta(minutes=1), 'alice:acct42')
    history = [_pending(dead, 3, 'linux')]
    linux = Serving('linux', 'alice:acct42')
    assert _assess(history, linux, frozenset({'alice:acct42'})) == (STALE, dead)
    assert _assess(history, linux, frozenset({'carol:acct7'})) == (HELD, dead)


def test_a_foreign_pending_status_is_not_a_claim() -> None:
    assert _assess([Status('tests/windows', 'pending', 'queued by some CI', '', 1)]) == (OPEN, None)


def test_a_box_serves_its_platform_and_linux_through_a_grant() -> None:
    assert serving('windows', ()) == (Serving('windows'),)
    assert serving('windows', (GRANT,)) == (Serving('windows'), Serving('linux', 'alice:acct42'))
    assert serving('linux', (GRANT,)) == (Serving('linux'),), 'a linux box runs linux itself'


def _origin(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    tips = {}
    for branch in ('integrate/main', 'feat/a', 'fix/b', 'other'):
        (repo / branch.replace('/', '_')).write_text(branch, encoding='utf-8')
        run_git(repo, 'add', '.')
        run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', branch)
        tips[branch] = git_out(repo, 'rev-parse', 'HEAD')
        run_git(repo, 'update-ref', f'refs/remotes/origin/{branch}', tips[branch])
    (repo / 'pyproject.toml').write_text(PRODUCE, encoding='utf-8')
    (repo / '.venv' / 'Scripts').mkdir(parents=True)
    (repo / '.venv' / 'Scripts' / 'python.exe').write_text('', encoding='utf-8')
    return repo, tips


PRODUCE = '[tool.lab_commons.parts.produce.windows]\nfull = ["-m", "lab_commons.dev.verify"]\n'


def _argv(repo: Path) -> list[str]:
    return [str(repo / '.venv' / 'Scripts' / 'python.exe'), '-m', 'lab_commons.dev.verify']


def test_the_mode_names_the_refs_it_serves(tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    policy = Policy()
    assert requests(repo, 'integrate', policy) == (('integrate/main', tips['integrate/main']),)
    assert set(requests(repo, 'develop', policy)) == {('fix/b', tips['fix/b']), ('feat/a', tips['feat/a'])}
    assert requests(repo, 'quiet', policy) == ()


def _tick(repo: Path, server: ThreadingHTTPServer, **kwargs: object) -> forgetick.TickReport:
    forge = Forge('forge.example.org', 'o', 'r')
    return tick(
        repo,
        kwargs.pop('mode', 'integrate'),
        client=lambda _root: client(forge, Loopback(server)),
        now=NOW,
        machine='G',
        grants=kwargs.pop('grants', ()),
        fetch=lambda _root: None,
        host='windows',
        os_name='nt',
        **kwargs,
    )


def test_a_tick_claims_an_open_request_and_names_the_command(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer(
        'GET',
        f'{API}/statuses/{sha}',
        (200, []),
        (200, [{'id': 1, 'context': 'tests/windows', 'status': 'pending', 'description': ME.description()}]),
    )
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/windows', 'status': 'pending'}))
    report = _tick(repo, server)
    assert [(w.ref, w.platform, w.state) for w in report.claimed] == [('integrate/main', 'windows', MINE)]
    posted = next(r for r in Recorder.received if r['method'] == 'POST')
    assert posted['body'] == {'state': 'pending', 'context': 'tests/windows', 'description': ME.description()}
    assert report.claimed[0].argv == tuple(_argv(repo)), 'the declared producer, run with the venv python'
    assert any(line.startswith('produce tests/windows:') for line in report.lines)


def test_a_part_the_repo_cannot_produce_is_never_claimed(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the claimable request of the test above, with the producer undeclared."""
    repo, tips = _origin(tmp_path)
    (repo / 'pyproject.toml').write_text('', encoding='utf-8')
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{tips["integrate/main"]}', (200, []))
    report = _tick(repo, server)
    assert report.claimed == ()
    assert not [r for r in Recorder.received if r['method'] == 'POST']
    assert 'tool.lab_commons.parts.produce.windows] full' in report.refused[0]


def test_a_tick_that_loses_the_race_claims_nothing(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    bob = Claim('H', 'bob', LATER)
    raced = [
        {'id': 1, 'context': 'tests/windows', 'status': 'pending', 'description': bob.description()},
        {'id': 2, 'context': 'tests/windows', 'status': 'pending', 'description': ME.description()},
    ]
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, raced))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server)
    assert report.claimed == ()
    assert [(w.state, w.holder) for w in report.work] == [(CLAIMED, bob)]


def test_a_dry_run_lists_and_posts_nothing(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{tips["integrate/main"]}', (200, []))
    report = _tick(repo, server, dry_run=True)
    assert [w.state for w in report.work] == [OPEN]
    assert not [r for r in Recorder.received if r['method'] == 'POST']


def test_a_quiet_checkout_never_fetches_and_never_claims(tmp_path: Path) -> None:
    """PLANTED CONTROL: quiet with a fetch and a forge that fail if touched."""
    repo, _tips = _origin(tmp_path)

    def touched(_root: Path) -> None:
        pytest.fail('a quiet checkout touched origin')

    report = tick(repo, 'quiet', client=touched, now=NOW, machine='G', grants=(), fetch=touched, host='windows')
    assert report.work == ()
    assert 'quiet' in report.lines[-1]


def test_the_cli_prints_work_and_claims_as_json(server, tmp_path: Path, capsys) -> None:
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer(
        'GET',
        f'{API}/statuses/{sha}',
        (
            200,
            [
                {
                    'id': 1,
                    'context': 'tests/windows',
                    'status': 'success',
                    'description': 'scope=full ran=1 hands=- nowhere=0',
                }
            ],
        ),
    )
    argv = ['--mode', 'integrate', '--json']
    code = forgetick.main(
        argv,
        cwd=repo,
        env=credential_env(tmp_path),
        transport=Loopback(server),
        fetch=lambda _root: None,
        now=NOW,
        grants=(),
        host='windows',
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['work'][0]['state'] == DONE
    assert printed['claimed'] == []
    assert printed['refused'] == []


def test_the_cli_json_carries_each_claimed_part_argv(server, tmp_path: Path, capsys) -> None:
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    me = Claim(workstation() or '', 'alice', NOW + forgetick.DEFAULT_LEASE)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    mine = {'id': 1, 'context': 'tests/windows', 'status': 'pending', 'description': me.description()}
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [mine]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    code = forgetick.main(
        ['--mode', 'integrate', '--json'],
        cwd=repo,
        env=credential_env(tmp_path),
        transport=Loopback(server),
        fetch=lambda _root: None,
        now=NOW,
        grants=(),
        host='windows',
        os_name='nt',
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['claimed'] == [{'ref': 'integrate/main', 'sha': sha, 'platform': 'windows', 'argv': _argv(repo)}]
