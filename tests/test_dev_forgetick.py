"""REQUESTS AND CLAIMS: origin is the trigger, a pending status is the claim, a stale lease is retaken.

The race and the lease are decided from the forge's own post order, so they are tested on that order
(pure :func:`assess`) and end to end against a REAL loopback forge and a REAL git repository.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from lab_commons.dev import forgetick
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgeclaim import (
    CLAIMED,
    DEFAULT_LEASE,
    DONE,
    MINE,
    OPEN,
    STALE,
    Claim,
    Serving,
    assess,
    serving,
)
from lab_commons.dev.forgeschedule import (
    INTEGRATION,
    OUTRANKED,
    OVER_BUDGET,
    PR,
    REQUEST,
    Headroom,
    candidates,
    load_schedule,
)
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.forgetick import tick
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.producer import ProducerExit, release_reason
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.grants import workstation

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=6)
ME = Claim('G', 'alice', LATER)
API = '/api/v1/repos/o/r'
SEAT = ClusterAccount('ada', 'alice')
#: NOW as the forge's Date header says it.
NOW_HTTP = 'Sat, 10 Oct 2026 12:00:00 GMT'


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    for httpd in serve():
        Recorder.date = NOW_HTTP  # the forge's clock; the host's is never read
        answer('GET', f'{API}/pulls', (200, []))  # no open PR and no request issue unless a test says so
        answer('GET', f'{API}/issues', (200, []))
        yield httpd


def _pending(claim: Claim, status_id: int, platform: str = 'windows') -> Status:
    return Status(f'tests/{platform}', 'pending', claim.description(), '', status_id, claim.login)


def _assess(history: list[Status], platform: str = 'windows') -> tuple[str, Claim | None]:
    return assess(history, platform, me=ME, now=NOW)


def test_a_claim_round_trips_through_its_description() -> None:
    cluster = Claim('', 'bob', LATER, 'ada/bob')
    assert cluster.description() == 'claim machine=- login=bob until=2026-10-10T18:00:00Z hpc=ada/bob'
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


def test_a_claim_released_for_unreachable_infrastructure_is_open_again() -> None:
    """PLANTED CONTROL: the same ``error`` state released for any other reason stays done."""
    outage = Status('tests/windows', 'error', release_reason(ProducerExit.UNREACHABLE), '', 2)
    inconclusive = Status('tests/windows', 'error', release_reason(ProducerExit.INCONCLUSIVE), '', 2)
    assert _assess([_pending(ME, 1), outage]) == (OPEN, None)
    assert _assess([_pending(ME, 1), inconclusive]) == (DONE, None)


def test_a_lapsed_cluster_claim_is_retaken_by_another_account_and_a_live_one_never() -> None:
    """Only the owner renews, so a lapsed lease means the owner is gone. PLANTED CONTROL: a minute earlier, held."""
    dead = Claim('hpclogin02', 'bob', NOW - timedelta(minutes=1), 'ada/bob')
    assert _assess([_pending(dead, 3, 'linux')], 'linux') == (STALE, dead)
    live = dataclasses.replace(dead, until=NOW + timedelta(minutes=1))
    assert _assess([_pending(live, 3, 'linux')], 'linux') == (CLAIMED, live)


def test_two_login_hosts_of_one_account_are_two_owners() -> None:
    """One account cannot win a race against itself: the earlier host holds, the later stands down."""
    me = Claim('hpclogin02', 'alice', LATER, 'ada/alice')
    other_host = dataclasses.replace(me, machine='hpclogin01')
    history = [_pending(other_host, 1, 'linux'), _pending(me, 2, 'linux')]
    assert assess(history, 'linux', me=me, now=NOW) == (CLAIMED, other_host)


def test_my_holding_claim_is_my_latest_renewal() -> None:
    renewal = dataclasses.replace(ME, until=LATER + timedelta(hours=2))
    assert _assess([_pending(ME, 1), _pending(renewal, 2)]) == (MINE, renewal)


def test_a_foreign_pending_status_is_not_a_claim() -> None:
    assert _assess([Status('tests/windows', 'pending', 'queued by some CI', '', 1)]) == (OPEN, None)


def test_a_box_serves_only_its_own_platform_and_never_a_cluster_over_ssh() -> None:
    assert serving('windows', None) == Serving('windows')
    assert serving('windows', SEAT) == Serving('windows'), 'a workstation never claims for a cluster'
    assert serving('linux', SEAT) == Serving('linux', 'ada/alice'), 'on a cluster: a cluster run'
    assert serving('linux', None) == Serving('linux'), 'a linux box off a cluster runs locally'


def _origin(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    (repo / 'pyproject.toml').write_text(PRODUCE, encoding='utf-8')  # committed: the producer is read AT the sha
    tips = {}
    for branch in ('integrate/main', 'feat/a', 'fix/b', 'other'):
        (repo / branch.replace('/', '_')).write_text(branch, encoding='utf-8')
        run_git(repo, 'add', '.')
        run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', branch)
        tips[branch] = git_out(repo, 'rev-parse', 'HEAD')
        run_git(repo, 'update-ref', f'refs/remotes/origin/{branch}', tips[branch])
    return repo, tips


def _declare(repo: Path, tips: dict[str, str], pyproject: str) -> str:
    """A new integration head whose OWN commit carries *pyproject*; the working tree is not what is read."""
    (repo / 'pyproject.toml').write_text(pyproject, encoding='utf-8')
    run_git(repo, 'add', 'pyproject.toml')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'declare')
    tips['integrate/main'] = git_out(repo, 'rev-parse', 'HEAD')
    run_git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', tips['integrate/main'])
    return tips['integrate/main']


PRODUCE = '[tool.lab_commons.parts.produce.windows]\nfull = ["-m", "lab_commons.dev.verify"]\n'


def _argv() -> list[str]:
    return ['-m', 'lab_commons.dev.verify']


def _tick(repo: Path, server: ThreadingHTTPServer, **kwargs: object) -> forgetick.TickReport:
    forge = Forge('forge.example.org', 'o', 'r')
    return tick(
        repo,
        kwargs.pop('mode', 'integrate'),
        client=lambda _root: client(forge, Loopback(server)),
        machine='G',
        seat=kwargs.pop('seat', None),
        fetch=lambda _root: None,
        host=kwargs.pop('host', 'windows'),
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
    assert report.claimed[0].argv == tuple(_argv()), 'the producer the claimed commit declares'
    assert any(line.startswith('produce tests/windows:') for line in report.lines)


def test_a_part_the_repo_cannot_produce_is_never_claimed(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the claimable request of the test above, with the producer undeclared."""
    repo, tips = _origin(tmp_path)
    _declare(repo, tips, '')
    (repo / 'pyproject.toml').write_text(PRODUCE, encoding='utf-8')  # the serving checkout's file decides nothing
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

    report = tick(repo, 'quiet', client=touched, machine='G', seat=None, fetch=touched, host='windows')
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
        seat_of=lambda: None,
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
    me = Claim(workstation() or '', 'alice', NOW + DEFAULT_LEASE)
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
        seat_of=lambda: None,
        host='windows',
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['claimed'] == [{'ref': 'integrate/main', 'sha': sha, 'platform': 'windows', 'argv': _argv()}]


def _post(status_id: int, claim: Claim, platform: str = 'windows') -> dict[str, object]:
    return {'id': status_id, 'context': f'tests/{platform}', 'status': 'pending', 'description': claim.description()}


def test_two_claimants_interleaved_on_one_forge_exactly_one_produces(server, tmp_path: Path) -> None:
    """Both read "no claim", both post, then both re-read: the lowest status id holds, the other stands down."""
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    alice, bob = ME, Claim('G', 'bob', LATER)
    both = [_post(1, alice), _post(2, bob)]
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}), (200, {'login': 'bob'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, both), (200, []), (200, both))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    first, second = _tick(repo, server), _tick(repo, server)
    assert [(w.state, w.holder) for w in first.claimed] == [(MINE, alice)]
    assert second.claimed == (), 'the loser produces nothing'
    assert [(w.state, w.holder) for w in second.work] == [(CLAIMED, alice)]
    assert len([r for r in Recorder.received if r['method'] == 'POST']) == 2, 'both posted: a post is not a lock'


def test_a_lapsed_lease_by_the_forges_clock_lets_another_claim_whatever_the_hosts_clock(server, tmp_path: Path) -> None:
    """CLOCK SKEW: the lease is judged on the forge's Date. PLANTED CONTROL: a minute earlier it still holds."""
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    bob = Claim('H', 'bob', NOW + timedelta(minutes=1))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, [_post(1, bob)]))
    held = _tick(repo, server)
    assert held.claimed == ()
    assert [(w.state, w.holder) for w in held.work] == [(CLAIMED, bob)]
    Recorder.received.clear()
    Recorder.date = 'Sat, 10 Oct 2026 12:02:00 GMT'  # the forge is two minutes on; the bob lease has lapsed
    later = NOW + timedelta(minutes=2)
    mine = Claim('G', 'alice', later + DEFAULT_LEASE)
    answer('GET', f'{API}/statuses/{sha}', (200, [_post(1, bob)]), (200, [_post(1, bob), _post(2, mine)]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    taken = _tick(repo, server)
    assert [(w.state, w.holder) for w in taken.claimed] == [(MINE, mine)]
    posted = next(r for r in Recorder.received if r['method'] == 'POST')
    assert posted['body']['description'] == mine.description(), 'until = the forge time plus the lease'


def test_a_cluster_seat_claims_a_cluster_part_and_no_argv(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = _declare(
        repo, tips, '[tool.lab_commons.hpc]\ninstall = "uv sync"\n[tool.lab_commons.parts]\noutput = "output/logs"\n'
    )
    me = Claim('G', 'alice', LATER, 'ada/alice')
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [_post(1, me, 'linux')]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, seat=SEAT, host='linux')
    (claimed,) = report.claimed
    assert (claimed.platform, claimed.state, claimed.holder, claimed.argv) == ('linux', MINE, me, ())
    assert claimed.cluster is not None
    assert claimed.cluster.repo_url == 'https://forge.example.org/o/r.git'
    assert any(line == 'produce tests/linux: a cluster run as ada/alice' for line in report.lines)


def test_a_run_in_flight_claims_nothing_more(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the open request the first tick test claims."""
    repo, tips = _origin(tmp_path)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{tips["integrate/main"]}', (200, []))
    report = _tick(repo, server, in_flight=True)
    assert report.claimed == ()
    assert [w.state for w in report.work] == [OPEN]


def _pull(number: int, head: str, sha: str, *labels: str) -> dict[str, object]:
    return {
        'number': number,
        'title': head,
        'state': 'open',
        'body': '',
        'html_url': f'https://forge.example.org/o/r/pulls/{number}',
        'user': {'login': 'bob'},
        'head': {'ref': head, 'sha': sha},
        'base': {'ref': 'integrate/main'},
        'labels': [{'name': label} for label in labels],
    }


def test_the_mode_names_its_candidates_one_per_ref(server, tmp_path: Path) -> None:
    """Integrate: the integration head, PRs into it, opted-in branches, requests. Develop: the lanes."""
    repo, tips = _origin(tmp_path)
    (repo / 'pyproject.toml').write_text(PRODUCE + '[tool.lab_commons.schedule]\nbranches = ["oth*"]\n', 'utf-8')
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'feat/a', tips['feat/a'], 'priority:user')]))
    request = {
        'number': 9,
        'body': 'platform = "windows"\n',
        'created_at': '2026-10-10T00:00:00Z',
        'labels': [{'name': 'forge:request'}],
    }
    answer('GET', f'{API}/issues', (200, [request]))
    forge = Forge('forge.example.org', 'o', 'r')
    built = client(forge, Loopback(server))
    found = candidates(
        repo, 'integrate', built, repo='o/r', platforms=('windows',), schedule=load_schedule(repo),
        policy=Policy(), now=NOW,
    )  # fmt: skip
    got = {(c.ref, c.sha, c.kind, c.labels) for c in found}
    assert got == {
        ('integrate/main', tips['integrate/main'], INTEGRATION, ()),
        ('feat/a', tips['feat/a'], PR, ('priority:user',)),
        ('other', tips['other'], 'branch', ()),
        ('issue/9', '', REQUEST, ('forge:request',)),
    }
    develop = candidates(
        repo, 'develop', built, repo='o/r', platforms=('windows',), schedule=load_schedule(repo),
        policy=Policy(), now=NOW,
    )  # fmt: skip
    assert {c.ref for c in develop} == {'feat/a', 'fix/b'}


def test_a_tick_claims_the_highest_score_and_names_why_the_rest_wait(server, tmp_path: Path) -> None:
    """A user-boosted PR jumps the integration head. PLANTED CONTROL: the label removed, the head is claimed."""
    repo, tips = _origin(tmp_path)
    head, lane = tips['integrate/main'], tips['feat/a']
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'feat/a', lane, 'priority:user')]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{head}', (200, []))
    answer('GET', f'{API}/statuses/{lane}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{lane}', (201, {}))
    report = _tick(repo, server)
    assert [w.ref for w in report.claimed] == ['feat/a']
    (waiting,) = report.queue
    assert waiting.candidate.ref == 'integrate/main'
    assert waiting.blocked == f'{OUTRANKED} by feat/a@{lane[:12]}:windows'
    Recorder.received.clear()
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'feat/a', lane)]))
    answer('GET', f'{API}/statuses/{head}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{head}', (201, {}))
    assert [w.ref for w in _tick(repo, server).claimed] == ['integrate/main']


def test_over_budget_or_no_headroom_is_not_claimed_and_says_so(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same open head under budget with headroom is claimed (the first tick test)."""
    repo, tips = _origin(tmp_path)
    head = tips['integrate/main']
    (repo / 'pyproject.toml').write_text(
        PRODUCE + '[tool.lab_commons.schedule]\ndaily_budget_core_h = {integration = 10}\n', 'utf-8'
    )
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{head}', (200, []))
    over = _tick(repo, server, usage={head[:12]: 12.0})
    assert over.claimed == ()
    assert over.queue[0].blocked == f'{OVER_BUDGET}: integrate/main used 12.0 of 10 core-h in 24 h'
    full = _tick(repo, server, headroom=Headroom(cores=8, submits=0))
    assert full.claimed == ()
    assert 'QOS' in full.queue[0].blocked
    assert not [r for r in Recorder.received if r['method'] == 'POST']


def _integrate(server, tmp_path: Path, notes: list[str]) -> set[tuple[str, str]]:
    tmp_path.mkdir(exist_ok=True)
    repo, _ = _origin(tmp_path)
    built = client(Forge('forge.example.org', 'o', 'r'), Loopback(server))
    found = candidates(
        repo, 'integrate', built, repo='o/r', platforms=('windows',), schedule=load_schedule(repo),
        policy=Policy(), now=NOW, say=notes.append,
    )  # fmt: skip
    return {(c.ref, c.kind) for c in found}


_NOT_FOUND = (404, {'message': 'not found'})


def test_a_repo_with_pull_requests_disabled_has_no_pr_candidates(server, tmp_path: Path) -> None:
    """Gitea answers ``/pulls`` 404 when the repo disables PRs. PLANTED CONTROL: PRs enabled, the 404 is said."""
    answer('GET', f'{API}/pulls', _NOT_FOUND)
    answer('GET', API, (200, {'has_pull_requests': False}))
    notes: list[str] = []
    assert ('integrate/main', INTEGRATION) in _integrate(server, tmp_path / 'off', notes)
    assert notes == [], 'disabled PRs are no candidates, not a fault'
    answer('GET', f'{API}/pulls', _NOT_FOUND)
    answer('GET', API, (200, {'has_pull_requests': True}))
    assert ('integrate/main', INTEGRATION) in _integrate(server, tmp_path / 'on', notes)
    assert len(notes) == 1, notes
    assert 'pull requests' in notes[0]


def test_a_failed_optional_listing_never_hides_the_integration_head(server, tmp_path: Path) -> None:
    """The request issues fail with 500: said, and the head still a candidate."""
    answer('GET', f'{API}/issues', (500, 'boom'), (500, 'boom'), (500, 'boom'))
    notes: list[str] = []
    assert ('integrate/main', INTEGRATION) in _integrate(server, tmp_path, notes)
    assert len(notes) == 1, notes
    assert 'request issues' in notes[0]


def test_a_credential_refusal_on_an_optional_listing_still_raises(server, tmp_path: Path) -> None:
    """PLANTED CONTROL for the two above: a 401 is the auth alarm's, never a skipped listing."""
    answer('GET', f'{API}/pulls', (401, {'message': 'token is required'}))
    with pytest.raises(ForgeCallFailed):
        _integrate(server, tmp_path, [])


_MISSING = 'the rclone remote hpc-data: is missing or unusable'


@pytest.mark.parametrize(
    ('outputs', 'problem', 'claims'),
    [
        ('outputs = ["fields/*.h5"]\n', _MISSING, False),
        ('outputs = ["fields/*.h5"]\n', '', True),  # PLANTED CONTROL: a working remote claims it
        ('', _MISSING, True),  # PLANTED CONTROL: no declared outputs never need the remote
    ],
)
def test_no_working_remote_claims_no_part_whose_outputs_could_need_it(
    server, tmp_path: Path, outputs: str, problem: str, *, claims: bool
) -> None:
    repo, tips = _origin(tmp_path)
    sha = _declare(
        repo,
        tips,
        f'[tool.lab_commons.hpc]\ninstall = "uv sync"\n{outputs}[tool.lab_commons.parts]\noutput = "output/logs"\n',
    )
    me = Claim('G', 'alice', LATER, 'ada/alice')
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [_post(1, me, 'linux')]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, seat=SEAT, host='linux', probe=lambda _root: problem)
    assert bool(report.claimed) is claims
    assert report.artefacts == problem, 'the host card states why'
    if not claims:
        assert not any(r['method'] == 'POST' for r in Recorder.received), 'no claim is posted'
        assert any('threshold_mb' in reason and _MISSING in reason for reason in report.refused)
        assert any(_MISSING in item.blocked for item in report.queue)


CAPABLE = (
    PRODUCE
    + '[tool.lab_commons.parts.produce.jmag]\nfull = ["-m", "lab_commons.dev.verify", "-m", "jmag"]\n'
    + '[tool.lab_commons.hpc]\ninstall = "uv sync"\n[tool.lab_commons.parts]\noutput = "output/logs"\n'
    + '[tool.lab_commons.capabilities]\njmag = { engine = true }\ndev_checkout = { on = ["windows"] }\n'
)


def test_a_host_providing_an_engine_claims_its_part_and_one_lacking_it_is_never_offered(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same host, the same head, without ``[capabilities.jmag]``, serves windows alone."""
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, CAPABLE)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    lacking = _tick(repo, server, dry_run=True, provides={'dev_checkout': {}})
    assert [w.platform for w in lacking.work] == ['windows']
    able = _tick(repo, server, dry_run=True, provides={'dev_checkout': {}, 'jmag': {'seats': 4}})
    assert sorted(w.platform for w in able.work) == ['jmag', 'windows']


def test_a_part_needing_a_capability_this_host_lacks_waits_labelled(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, CAPABLE)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    report = _tick(repo, server, provides={})
    assert report.claimed == ()
    assert [item.blocked for item in report.queue] == ['no host provides dev_checkout']
    assert not [r for r in Recorder.received if r['method'] == 'POST']


def test_the_cluster_part_stays_claimable_by_a_host_lacking_dev_checkout(server, tmp_path: Path) -> None:
    """The cluster case (coordinator ruling 2026-10-12): ``dev_checkout`` never makes the linux part unclaimable."""
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, CAPABLE)
    me = Claim('G', 'alice', LATER, 'ada/alice')
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [_post(1, me, 'linux')]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, seat=SEAT, host='linux', provides={'jmag': {'seats': 4}})
    assert [(w.platform, w.state) for w in report.claimed] == [('linux', MINE)], 'and a cluster runs no engine part'


def test_a_refused_declaration_blocks_its_own_sha_and_the_good_head_is_claimed(server, tmp_path: Path) -> None:
    """One PR head declares a capability on the OS axis; the kit refuses it there and nowhere else.

    PLANTED CONTROL: the boosted PR outranks the head, so without the refusal it -- not the head -- is claimed.
    """
    repo, tips = _origin(tmp_path)
    bad = _declare(repo, tips, PRODUCE + '[tool.lab_commons.platforms]\njmag = ["windows"]\n')
    run_git(repo, 'update-ref', 'refs/remotes/origin/feat/a', bad)
    head = _declare(repo, tips, PRODUCE)
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'feat/a', bad, 'priority:user')]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{bad}', (200, []))
    answer('GET', f'{API}/statuses/{head}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{head}', (201, {}))
    report = _tick(repo, server)
    assert [w.ref for w in report.claimed] == ['integrate/main']
    (waiting,) = report.queue
    assert waiting.candidate.ref == 'feat/a'
    assert waiting.blocked.startswith(f'declaration at {bad[:12]} refused: [tool.lab_commons.platforms] jmag')
    assert not [r for r in Recorder.received if r['method'] == 'POST' and bad in r['path']]
