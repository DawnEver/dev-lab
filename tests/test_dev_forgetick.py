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
from _box_fake import quiet
from _forge_fake import Loopback, Recorder, answer, client, credential_env, git_out, make_repo, run_git, serve

from lab_commons.box import GB, Capacity
from lab_commons.compute import probe as compute_probe
from lab_commons.compute.model import (
    FEATURE,
    INTEGRATION,
    PR,
    REQUEST,
    Candidate,
    Demand,
    Resources,
    Supply,
)
from lab_commons.compute.priority import Priority
from lab_commons.dev import forgetick
from lab_commons.dev.forge import Forge
from lab_commons.dev.forgeclaim import (
    CLAIMED,
    DEFAULT_LEASE,
    DONE,
    MINE,
    OPEN,
    REFUSED_AT_COMMIT,
    STALE,
    Claim,
    Serving,
    assess,
    serving,
)
from lab_commons.dev.forgeschedule import NOT_ADMITTED, OVER_BUDGET, candidates, load_schedule
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.forgetick import tick
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.lanepolicy import Policy
from lab_commons.dev.producer import ProducerExit, release_reason
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.grants import workstation
from lab_commons.hpc.needsets import BASE
from lab_commons.hpc.retired import RETIRED

SLURM = frozenset({'cpu', 'mem_gb', 'submits'})
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


def _pending(claim: Claim, status_id: int, platform: str = BASE) -> Status:
    return Status(f'tests/{platform}', 'pending', claim.description(), '', status_id, claim.login)


def _assess(history: list[Status], platform: str = BASE) -> tuple[str, Claim | None]:
    return assess(history, f'tests/{platform}', me=ME, now=NOW)


def test_a_claim_round_trips_through_its_description() -> None:
    cluster = Claim('', 'bob', LATER, 'ada/bob')
    assert cluster.description() == 'claim machine=- login=bob until=2026-10-10T18:00:00Z hpc=ada/bob'
    assert Claim.parse(cluster.description()) == cluster
    assert Claim.parse('scope=full ran=1 hands=-') is None
    assert Claim.parse('claim machine=G login=a until=not-a-time hpc=-') is None


def test_no_post_is_open_a_settled_part_is_done_and_my_live_claim_is_mine() -> None:
    assert _assess([]) == (OPEN, None)
    assert _assess([Status('tests/jmag', 'success', 'x', '', 1)]) == (OPEN, None), 'another part is not mine'
    assert _assess([_pending(ME, 1), Status('tests/base', 'failure', 'scope=full', '', 2)]) == (DONE, None)
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
    outage = Status('tests/base', 'error', release_reason(ProducerExit.UNREACHABLE), '', 2)
    inconclusive = Status('tests/base', 'error', release_reason(ProducerExit.INCONCLUSIVE), '', 2)
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
    assert assess(history, 'tests/linux', me=me, now=NOW) == (CLAIMED, other_host)


def test_my_holding_claim_is_my_latest_renewal() -> None:
    renewal = dataclasses.replace(ME, until=LATER + timedelta(hours=2))
    assert _assess([_pending(ME, 1), _pending(renewal, 2)]) == (MINE, renewal)


def test_a_foreign_pending_status_is_not_a_claim() -> None:
    assert _assess([Status('tests/base', 'pending', 'queued by some CI', '', 1)]) == (OPEN, None)


def test_a_box_serves_only_its_own_platform_and_never_a_cluster_over_ssh() -> None:
    assert serving('windows', None) == Serving('windows')
    assert serving('windows', SEAT) == Serving('windows'), 'a workstation never claims for a cluster'
    assert serving('linux', SEAT) == Serving('linux', 'ada/alice'), 'on a cluster: a cluster run'
    assert serving('linux', None) == Serving('linux'), 'a linux box off a cluster runs locally'


def _origin(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    (repo / 'pyproject.toml').write_text(PRODUCE, encoding='utf-8')  # committed: the producer is read AT the sha
    tips = {}
    for branch in ('integrate/main', 'topic/a', 'wip/b', 'other'):
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


#: A retired table, read off the registry: its spelling lives there and nowhere else.
RETIRED_TABLE = min(key for key in RETIRED if key.startswith('[tool.lab_commons.'))

PRODUCE = '[tool.lab_commons.tests]\nproduce = ["-m", "lab_commons.dev.verify", "--part", "{part}"]\n'


def _argv(part: str = BASE) -> list[str]:
    return ['-m', 'lab_commons.dev.verify', '--part', part]


def _tick(repo: Path, server: ThreadingHTTPServer, **kwargs: object) -> forgetick.TickReport:
    """One tick against the loopback forge; a box tick given no supply has its whole capacity, read QUIET.

    The default box supply is MEASURED (D3): the live box's load would decide what a test claims.
    """
    forge = Forge('forge.example.org', 'o', 'r')
    if kwargs.get('seat') is None and 'supply' not in kwargs:
        capacity = Capacity.read()
        kwargs['supply'] = compute_probe.box('G', capacity=capacity, read=quiet(capacity))
    return tick(
        repo,
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
        (200, [{'id': 1, 'context': 'tests/base', 'status': 'pending', 'description': ME.description()}]),
    )
    answer('POST', f'{API}/statuses/{sha}', (201, {'context': 'tests/base', 'status': 'pending'}))
    report = _tick(repo, server)
    assert [(w.ref, w.platform, w.state) for w in report.claimed] == [('integrate/main', BASE, MINE)]
    posted = next(r for r in Recorder.received if r['method'] == 'POST')
    assert posted['body'] == {'state': 'pending', 'context': 'tests/base', 'description': ME.description()}
    assert report.claimed[0].argv == tuple(_argv()), 'the producer the claimed commit declares'
    assert any(line.startswith('produce tests/base:') for line in report.lines)


def test_a_part_the_repo_cannot_produce_is_never_claimed_and_is_refused_on_its_commit(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the claimable request of the test above, with the producer undeclared AT the sha.

    The defect is the commit's own, so it is routed ONCE to its owner -- an ``error`` on the part's context
    of that commit -- never claimed, never left waiting to be re-refused (and alarmed) every tick.
    """
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, '')
    (repo / 'pyproject.toml').write_text(PRODUCE, encoding='utf-8')  # the serving checkout's file decides nothing
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server)
    assert report.claimed == ()
    assert report.queue == ()
    assert report.refused == (), 'a commit-own refusal is no reason for this host to sit idle'
    (posted,) = [r for r in Recorder.received if r['method'] == 'POST']
    assert posted['body']['state'] == 'error'
    assert posted['body']['context'] == 'tests/base'
    assert posted['body']['description'].startswith(REFUSED_AT_COMMIT)
    assert 'tool.lab_commons.tests] produce' in posted['body']['description']
    assert [w.state for w in report.work] == [DONE]


def test_a_tick_that_loses_the_race_claims_nothing(server, tmp_path: Path) -> None:
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    bob = Claim('H', 'bob', LATER)
    raced = [
        {'id': 1, 'context': 'tests/base', 'status': 'pending', 'description': bob.description()},
        {'id': 2, 'context': 'tests/base', 'status': 'pending', 'description': ME.description()},
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
                    'context': 'tests/base',
                    'status': 'success',
                    'description': 'scope=full ran=1 hands=-',
                }
            ],
        ),
    )
    argv = ['--json']
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


def test_the_cli_json_carries_each_claimed_producer_argv(server, tmp_path: Path, capsys, monkeypatch) -> None:
    capacity = Capacity.read()  # the CLI's box supply is measured (D3): read it quiet, as `_tick` does
    monkeypatch.setattr(
        forgetick, '_whole', lambda scope, **_kw: compute_probe.box(scope, capacity=capacity, read=quiet(capacity))
    )
    repo, tips = _origin(tmp_path)
    sha = tips['integrate/main']
    me = Claim(workstation() or '', 'alice', NOW + DEFAULT_LEASE)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    mine = {'id': 1, 'context': 'tests/base', 'status': 'pending', 'description': me.description()}
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [mine]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    code = forgetick.main(
        ['--json'],
        cwd=repo,
        env=credential_env(tmp_path),
        transport=Loopback(server),
        fetch=lambda _root: None,
        seat_of=lambda: None,
        host='windows',
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['claimed'] == [{'ref': 'integrate/main', 'sha': sha, 'platform': BASE, 'argv': _argv()}]


def _post(status_id: int, claim: Claim, platform: str = BASE) -> dict[str, object]:
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
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [_post(1, me)]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, seat=SEAT, host='linux')
    (claimed,) = report.claimed
    assert (claimed.platform, claimed.state, claimed.holder, claimed.argv) == (BASE, MINE, me, ())
    assert claimed.cluster is not None
    assert claimed.cluster.repo_url == 'https://forge.example.org/o/r.git'
    assert any(line == 'produce tests/base: a cluster run as ada/alice' for line in report.lines)


BOX = Supply('G', Resources(cpu=4, mem_gb=32), frozenset({'cpu', 'mem_gb', 'windows'}))


def _sized(**by_ref: float) -> object:
    """A fake demand: a core and *by_ref* GB for the candidate of each ref (``integrate/main`` spelled ``head``).

    Memory is the one resource the tests built on it vary.
    """

    def size(wanted: Candidate, _needs: frozenset[str]) -> Demand:
        return Demand(cpu=1, mem_gb=by_ref['head' if wanted.ref == 'integrate/main' else wanted.ref.replace('/', '_')])

    return size


def _head_and_pr(tips: dict[str, str], *, claim_pr: bool = True, claim_head: bool = True) -> tuple[str, str]:
    """The head and a boosted PR (it ranks first), each answering a claim that holds when posted."""
    head, lane = tips['integrate/main'], tips['topic/a']
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', lane, 'priority:user')]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    for sha, claimed in ((head, claim_head), (lane, claim_pr)):
        answer('GET', f'{API}/statuses/{sha}', (200, []), *([(200, [_post(1, ME)])] if claimed else []))
        answer('POST', f'{API}/statuses/{sha}', (201, {}))
    return head, lane


def test_a_running_demand_keeps_what_it_holds(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: nothing running, the same head on the same box is claimed."""
    repo, tips = _origin(tmp_path)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{tips["integrate/main"]}', (200, []))
    report = _tick(repo, server, supply=BOX, demand=_sized(head=8), running=[Demand(mem_gb=30)])
    assert report.claimed == ()
    assert [(w.state, item.blocked) for w, item in zip(report.work, report.queue, strict=True)] == [
        (OPEN, f'{NOT_ADMITTED}: lacking mem_gb (8 asked, 2 free)')
    ]


def test_two_small_jobs_are_both_admitted_on_one_tick(server, tmp_path: Path) -> None:
    """No one-claim-per-tick rule: both fit the box, so both are claimed in rank order."""
    repo, tips = _origin(tmp_path)
    head, lane = _head_and_pr(tips)
    report = _tick(repo, server, supply=BOX, demand=_sized(head=8, topic_a=8))
    assert [w.sha for w in report.claimed] == [lane, head]
    assert [dict(w.demand) for w in report.claimed] == [{'cpu': 1, 'mem_gb': 8}] * 2, (
        'each carries what it was admitted at'
    )
    assert [item.blocked for item in report.queue] == []


def test_a_big_job_is_skipped_and_a_smaller_lower_ranked_one_is_claimed(server, tmp_path: Path) -> None:
    """The boosted PR ranks first and does not fit; the head behind it does. PLANTED CONTROL: 64 GB takes both."""
    repo, tips = _origin(tmp_path)
    head, lane = _head_and_pr(tips, claim_pr=False)
    report = _tick(repo, server, supply=BOX, demand=_sized(head=8, topic_a=40))
    assert [w.sha for w in report.claimed] == [head]
    (waiting,) = report.queue
    assert (waiting.candidate.sha, waiting.blocked) == (lane, f'{NOT_ADMITTED}: lacking mem_gb (40 asked, 32 free)')
    Recorder.received.clear()
    _head_and_pr(tips)
    roomy = Supply('G', Resources(cpu=4, mem_gb=64), BOX.listed)
    assert [w.sha for w in _tick(repo, server, supply=roomy, demand=_sized(head=8, topic_a=40)).claimed] == [lane, head]


def _claimed_as(tips: dict[str, str]) -> list[str]:
    """The claim descriptions this tick posted on the head."""
    path = f'{API}/statuses/{tips["integrate/main"]}'
    return [one['body']['description'] for one in Recorder.received if one['method'] == 'POST' and one['path'] == path]


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


_RULE = '[tool.lab_commons.schedule]\nclasses_by_ref = {"oth*" = "branch", "wip/*" = "feature"}\n'


def test_every_host_names_every_class_one_candidate_per_ref(server, tmp_path: Path) -> None:
    """One queue: the integration head, PRs into it, every branch the rule classes, requests."""
    repo, tips = _origin(tmp_path)
    (repo / 'pyproject.toml').write_text(PRODUCE + _RULE, 'utf-8')
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', tips['topic/a'], 'priority:user')]))
    request = {
        'number': 9,
        'body': 'producer = "femm_goldens"\n',
        'created_at': '2026-10-10T00:00:00Z',
        'labels': [{'name': 'forge:request'}],
    }
    answer('GET', f'{API}/issues', (200, [request]))
    forge = Forge('forge.example.org', 'o', 'r')
    built = client(forge, Loopback(server))
    found = candidates(
        repo, built, repo='o/r', parts=lambda _sha: (BASE,), schedule=load_schedule(repo),
        policy=Policy(), now=NOW,
    )  # fmt: skip
    got = {(c.ref, c.sha, c.kind, c.labels) for c in found}
    assert got == {
        ('integrate/main', tips['integrate/main'], INTEGRATION, ()),
        ('topic/a', tips['topic/a'], PR, ('priority:user',)),
        ('wip/b', tips['wip/b'], FEATURE, ()),
        ('other', tips['other'], 'branch', ()),
        ('issue/9', '', REQUEST, ('forge:request',)),
    }, 'topic/a is a PR head, so it is served once, as pr'


def test_a_feature_branch_sha_is_never_a_candidate_for_a_full_part_its_refs_exclude(server, tmp_path: Path) -> None:
    """HEAVY NEVER ON DEVELOPMENT BRANCHES (user ruling 2026-10-13): ``parts.refs.<part>.<scope>`` filters refs.

    The PR and the classed branches are all served and all excluded from ``tests/windows`` at ``full``;
    each exclusion is SAID. A request is no part, asked for by name at its sha: no part's filter excludes
    it. PLANTED CONTROL: the same refs with no filter are all candidates
    (:func:`test_every_host_names_every_class_one_candidate_per_ref`), and a part the filter does not name
    (``jmag``) keeps every ref.
    """
    repo, tips = _origin(tmp_path)
    refs = '[tool.lab_commons.parts.refs.windows]\nfull = ["integrate/main", "main"]\n'
    (repo / 'pyproject.toml').write_text(PRODUCE + refs + _RULE, 'utf-8')
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', tips['topic/a'])]))
    request = {'number': 9, 'body': 'producer = "femm_goldens"\n', 'labels': [{'name': 'forge:request'}]}
    answer('GET', f'{API}/issues', (200, [request]))
    notes: list[str] = []
    found = candidates(
        repo, client(Forge('forge.example.org', 'o', 'r'), Loopback(server)), repo='o/r',
        parts=lambda _sha: ('windows', 'jmag'), schedule=load_schedule(repo), policy=Policy(), now=NOW,
        say=notes.append,
    )  # fmt: skip
    assert {(c.ref, c.platform) for c in found} == {
        ('integrate/main', 'windows'),
        ('integrate/main', 'jmag'),
        ('topic/a', 'jmag'),
        ('wip/b', 'jmag'),
        ('other', 'jmag'),
        ('issue/9', ''),
    }
    assert sorted(note for note in notes if 'tests/windows' in note) == sorted(
        f'[serve] {ref} is not served tests/windows at full: [tool.lab_commons.parts.refs.windows] full '
        f"admits ['integrate/main', 'main']"
        for ref in ('topic/a', 'wip/b', 'other')
    )


def test_a_tick_claims_the_highest_score_and_names_why_the_rest_wait(server, tmp_path: Path, monkeypatch) -> None:
    """A user-boosted PR jumps the integration head. PLANTED CONTROL: the label removed, the head is claimed."""
    monkeypatch.setattr(forgetick.Capacity, 'read', staticmethod(lambda: Capacity(cpu=4.0, mem_bytes=8 * GB, seats={})))
    repo, tips = _origin(tmp_path)
    head, lane = tips['integrate/main'], tips['topic/a']
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', lane, 'priority:user')]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{head}', (200, []))
    answer('GET', f'{API}/statuses/{lane}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{lane}', (201, {}))
    report = _tick(repo, server)
    assert [w.ref for w in report.claimed] == ['topic/a']
    (waiting,) = report.queue
    assert waiting.candidate.ref == 'integrate/main'
    assert waiting.blocked == f'{NOT_ADMITTED}: lacking cpu (4 asked, 0 free), mem_gb (8 asked, 0 free)', (
        'a claimed box part, unmeasured, declares the whole box'
    )
    Recorder.received.clear()
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', lane)]))
    answer('GET', f'{API}/statuses/{head}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{head}', (201, {}))
    assert [w.ref for w in _tick(repo, server).claimed] == ['integrate/main']


def test_over_budget_or_not_admitted_is_not_claimed_and_says_so(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same open head under budget on a box that admits it is claimed (the first tick test)."""
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
    full = _tick(
        repo,
        server,
        supply=Supply('slurm:alice', Resources(cpu=8, mem_gb=64, submits=0), SLURM),
        demand=lambda *_: Demand(cpu=1),
    )
    assert full.claimed == ()
    assert full.queue[0].blocked == f'{NOT_ADMITTED}: lacking submits (1 asked, 0 free)'
    busy = _tick(
        repo,
        server,
        supply=Supply('ws', Resources(mem_gb=64), frozenset({'cpu', 'mem_gb'})),
        demand=lambda *_: Demand(cpu=1),
    )
    assert busy.queue[0].blocked == f'{NOT_ADMITTED}: lacking cpu (1 asked, 0 free)'
    assert not [r for r in Recorder.received if r['method'] == 'POST']


def _integrate(server, tmp_path: Path, notes: list[str]) -> set[tuple[str, str]]:
    tmp_path.mkdir(exist_ok=True)
    repo, _ = _origin(tmp_path)
    built = client(Forge('forge.example.org', 'o', 'r'), Loopback(server))
    found = candidates(
        repo, built, repo='o/r', parts=lambda _sha: (BASE,), schedule=load_schedule(repo),
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
    answer('GET', f'{API}/statuses/{sha}', (200, []), (200, [_post(1, me)]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    report = _tick(repo, server, seat=SEAT, host='linux', probe=lambda _root: problem)
    assert bool(report.claimed) is claims
    assert report.artefacts == problem, 'the host card states why'
    if not claims:
        assert not any(r['method'] == 'POST' for r in Recorder.received), 'no claim is posted'
        assert any('threshold_mb' in reason and _MISSING in reason for reason in report.refused)
        assert any(_MISSING in item.blocked for item in report.queue)


NEEDS = (
    '[tool.lab_commons.tests]\nresources = ["dev_checkout", "jmag", "linux"]\n'
    'produce = ["-m", "lab_commons.dev.verify", "--part", "{part}"]\n'
    '[tool.lab_commons.hpc]\ninstall = "uv sync"\n[tool.lab_commons.parts]\noutput = "output/logs"\n'
)


def _base(hands: str) -> dict[str, object]:
    """A settled base part handing ids to the parts *hands* names -- how a commit's other parts are discovered."""
    return {'id': 1, 'context': 'tests/base', 'status': 'success', 'description': f'scope=full ran=3 hands={hands}'}


def _one_core(*_: object) -> Demand:
    return Demand(cpu=1)


def test_a_part_base_hands_to_is_claimed_where_its_needs_are_present(server, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same host and head without jmag present waits, naming jmag."""
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, NEEDS)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, [_base('jmag:2')]))
    lacking = _tick(repo, server, dry_run=True, supply=BOX, demand=_one_core)
    assert [(w.platform, w.state) for w in lacking.work] == [(BASE, DONE), ('jmag', OPEN)]
    assert [item.blocked for item in lacking.queue] == [f'{NOT_ADMITTED}: lacking jmag']
    assert lacking.pending == (), 'a part needing a tool absent here is no work this host could serve'
    answer('GET', f'{API}/statuses/{sha}', (200, [_base('jmag:2')]), (200, [_base('jmag:2'), _post(2, ME, 'jmag')]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    with_jmag = Supply('G', Resources(cpu=4, mem_gb=32, jmag=4), frozenset({'cpu', 'mem_gb', 'windows', 'jmag'}))
    able = _tick(repo, server, supply=with_jmag, demand=_one_core)
    assert [(w.platform, w.state, w.argv) for w in able.claimed] == [('jmag', MINE, tuple(_argv('jmag')))]


def test_two_parts_of_one_sha_each_own_a_tree_and_are_claimed_in_one_tick(server, tmp_path: Path) -> None:
    """S4: a job's tree is keyed by sha AND context, so a second part of the sha no longer waits a tick."""
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, NEEDS)
    hands = 'dev_checkout:1,jmag:1'
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    claimed = [_base(hands), _post(2, ME, 'dev_checkout'), _post(3, ME, 'jmag')]
    answer('GET', f'{API}/statuses/{sha}', (200, claimed[:1]), (200, claimed[:2]), (200, claimed))
    answer('POST', f'{API}/statuses/{sha}', (201, {}), (201, {}))
    roomy = Supply('G', Resources(cpu=8, jmag=4, dev_checkout=1), frozenset({'cpu', 'jmag', 'dev_checkout'}))
    report = _tick(repo, server, supply=roomy, demand=_one_core)
    assert sorted(w.platform for w in report.claimed) == ['dev_checkout', 'jmag']


def test_a_cluster_claims_what_it_has_and_never_a_part_needing_dev_checkout(server, tmp_path: Path) -> None:
    """The cluster case (coordinator ruling 2026-10-12): a dev_checkout part never lands on its per-sha tree."""
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, NEEDS)
    me = Claim('G', 'alice', LATER, 'ada/alice')
    hands = 'dev_checkout:1,linux:2'
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, [_base(hands)]), (200, [_base(hands), _post(2, me, 'linux')]))
    answer('POST', f'{API}/statuses/{sha}', (201, {}))
    account = Supply('ada/alice', Resources(cpu=8, mem_gb=64, linux=8), frozenset({'cpu', 'mem_gb', 'linux'}))
    report = _tick(repo, server, seat=SEAT, host='linux', supply=account, demand=_one_core)
    assert [(w.platform, w.state) for w in report.claimed] == [('linux', MINE)]
    assert [item.blocked for item in report.queue] == [f'{NOT_ADMITTED}: lacking dev_checkout']


def test_a_refused_declaration_blocks_its_own_sha_and_the_good_head_is_claimed(server, tmp_path: Path) -> None:
    """One PR head declares a table this kit does not know; the kit refuses it there and nowhere else.

    PLANTED CONTROL: the boosted PR outranks the head, so without the refusal it -- not the head -- is claimed.
    """
    repo, tips = _origin(tmp_path)
    bad = _declare(repo, tips, PRODUCE + '[tool.lab_commons.tomorrow]\nrows = 1\n')
    run_git(repo, 'update-ref', 'refs/remotes/origin/topic/a', bad)
    head = _declare(repo, tips, PRODUCE)
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', bad, 'priority:user')]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{bad}', (200, []))
    answer('GET', f'{API}/statuses/{head}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{head}', (201, {}))
    report = _tick(repo, server)
    assert [w.ref for w in report.claimed] == ['integrate/main']
    (waiting,) = report.queue
    assert waiting.candidate.ref == 'topic/a'
    assert waiting.blocked.startswith(f'declaration at {bad[:12]} refused: this lab-commons does not know')
    assert not [r for r in Recorder.received if r['method'] == 'POST' and bad in r['path']]


def test_a_retired_declaration_is_refused_once_on_its_own_commit_and_never_waits(server, tmp_path: Path) -> None:
    """A RETIRED table is the commit's own defect (older than its reader): routed to it once, never queued.

    PLANTED CONTROL: the test above -- a table this kit does not KNOW is the serving host's defect (its kit is
    older), so that sha waits, unposted, for a host that can read it.
    """
    repo, tips = _origin(tmp_path)
    bad = _declare(repo, tips, PRODUCE + f'{RETIRED_TABLE}\nrows = 1\n')
    run_git(repo, 'update-ref', 'refs/remotes/origin/topic/a', bad)
    head = _declare(repo, tips, PRODUCE)
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', bad, 'priority:user')]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{bad}', (200, []))
    answer('POST', f'{API}/statuses/{bad}', (201, {}))
    answer('GET', f'{API}/statuses/{head}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{head}', (201, {}))
    report = _tick(repo, server)
    assert [w.ref for w in report.claimed] == ['integrate/main']
    assert report.queue == ()
    (settled,) = [r for r in Recorder.received if r['method'] == 'POST' and bad in r['path']]
    assert settled['body']['state'] == 'error'
    assert settled['body']['description'].startswith(f'{REFUSED_AT_COMMIT} declaration at {bad[:12]} refused')
    refusal = {'id': 9, 'context': 'tests/base', 'status': 'error', 'description': settled['body']['description']}
    Recorder.received.clear()
    answer('GET', f'{API}/statuses/{bad}', (200, [refusal]))
    answer('GET', f'{API}/statuses/{head}', (200, [_post(1, ME)]))
    again = _tick(repo, server)
    assert not [r for r in Recorder.received if r['method'] == 'POST' and bad in r['path']], 'routed ONCE'
    assert [item.candidate.ref for item in again.queue] == []


def test_a_dry_run_routes_no_refusal(server, tmp_path: Path) -> None:
    """A dry run posts nothing: the commit-own refusal is shown waiting, with its reason."""
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, '')
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    report = _tick(repo, server, dry_run=True)
    assert not [r for r in Recorder.received if r['method'] == 'POST']
    (waiting,) = report.queue
    assert waiting.blocked.startswith(REFUSED_AT_COMMIT)


def test_a_box_job_is_admitted_at_the_cores_it_measured_never_capped_to_the_box(server, tmp_path: Path) -> None:
    """A box job's cpu demand is what its run MEASURED (cpu-seconds over wall): eight busy cores do not fit in four.

    PLANTED CONTROL: the same head measuring four cores fits the same box and is claimed.
    """
    repo, tips = _origin(tmp_path)
    head = tips['integrate/main']
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{head}', (200, []))
    wide = _tick(repo, server, supply=BOX, demand=lambda _wanted, _needs: Demand(cpu=8))
    assert wide.claimed == ()
    assert wide.queue[0].blocked == f'{NOT_ADMITTED}: lacking cpu (8 asked, 4 free)'
    answer('GET', f'{API}/statuses/{head}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{head}', (201, {}))
    fits = _tick(repo, server, supply=BOX, demand=lambda _wanted, _needs: Demand(cpu=4))
    assert [w.ref for w in fits.claimed] == ['integrate/main']


def _stamped_lane(repo: Path, tips: dict[str, str], host: str) -> str:
    """``topic/a``'s tip re-made carrying the ``Forge-Host`` trailer the commit-msg hook writes."""
    run_git(repo, 'checkout', '-q', tips['topic/a'])
    message = f'lane work\n\nForge-Host: {host}'
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', message)
    tips['topic/a'] = git_out(repo, 'rev-parse', 'HEAD')
    run_git(repo, 'update-ref', 'refs/remotes/origin/topic/a', tips['topic/a'])
    return tips['topic/a']


@pytest.mark.parametrize(
    ('favoured', 'owners', 'first'),
    [
        ({'sessions': ['topic/a']}, {}, 'topic/a'),
        ({'hosts': ['B']}, {'B': ('bob',)}, 'topic/a'),  # bob authored the PR and publishes B: the trailer stands
        ({'hosts': ['B']}, {'B': ('carol',)}, 'integrate/main'),  # CONTROL: B is carol's, bob cannot vouch for it
        ({'sessions': ['fix/b']}, {}, 'integrate/main'),  # CONTROL: another session
    ],
)
def test_a_job_this_hosts_priority_names_ranks_first(server, tmp_path: Path, favoured: dict, owners, first) -> None:
    """The PR (class pr) outscores nothing against the head (class integration) -- unless this host favours it."""
    repo, tips = _origin(tmp_path)
    lane = _stamped_lane(repo, tips, 'B')
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', lane)]))
    for sha in (lane, tips['integrate/main']):
        answer('GET', f'{API}/statuses/{sha}', (200, []))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    priority = Priority.of(favoured)
    report = _tick(repo, server, dry_run=True, priority=priority, owners=owners, demand=lambda *_: Demand(cpu=1))
    assert report.queue[0].candidate.ref == first


def test_a_sha_that_cannot_be_produced_blocks_itself_and_the_good_head_is_claimed(server, tmp_path: Path) -> None:
    """A stale PR head declares no producer; it is refused there and nowhere else -- never the whole repo.

    PLANTED CONTROL: the boosted PR outranks the head, so it is assessed first; a repo-wide refusal would
    then block the head too (a downstream repo, 2026-10-13: one 13-day-old branch idled every Ada account).
    """
    repo, tips = _origin(tmp_path)
    stale = _declare(repo, tips, '')
    run_git(repo, 'update-ref', 'refs/remotes/origin/topic/a', stale)
    head = _declare(repo, tips, PRODUCE)
    answer('GET', f'{API}/pulls', (200, [_pull(7, 'topic/a', stale, 'priority:user')]))
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{stale}', (200, []))
    answer('POST', f'{API}/statuses/{stale}', (201, {}))
    answer('GET', f'{API}/statuses/{head}', (200, []), (200, [_post(1, ME)]))
    answer('POST', f'{API}/statuses/{head}', (201, {}))
    report = _tick(repo, server)
    assert [w.ref for w in report.claimed] == ['integrate/main']
    assert report.queue == (), 'refused on its own commit, never left waiting'


CLUSTER_ONLY = '[tool.lab_commons.hpc]\ninstall = "uv sync"\n[tool.lab_commons.parts]\noutput = "output/logs"\n'


@pytest.mark.parametrize(
    ('declared', 'kind', 'missing'),
    [(CLUSTER_ONLY, {}, 'tool.lab_commons.tests] produce'), (PRODUCE, {'seat': SEAT, 'host': 'linux'}, 'install')],
    ids=['box-lacks-produce', 'cluster-lacks-install'],
)
def test_a_producer_only_the_other_host_kind_can_build_is_never_refused_on_the_commit(
    server, tmp_path: Path, declared: str, kind: dict, missing: str
) -> None:
    """A box needs ``produce``, a cluster ``hpc install``: one kind lacking its own is no defect of the commit.

    The part waits here, named, and is no work this host could serve. PLANTED CONTROL: a commit declaring
    neither is refused on it (``test_a_part_the_repo_cannot_produce_is_never_claimed_and_is_refused_on_its_commit``).
    """
    repo, tips = _origin(tmp_path)
    sha = _declare(repo, tips, declared)
    answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    answer('GET', f'{API}/statuses/{sha}', (200, []))
    report = _tick(repo, server, **kind)
    assert not [r for r in Recorder.received if r['method'] == 'POST']
    (waiting,) = report.queue
    assert missing in waiting.blocked
    assert report.pending == ()
