"""THE HARNESS ENTRY: tick, produce or advance, publish -- a contract break fails loudly, a silent failure alarms."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_fake import git_out, run_git

from lab_commons.compute.ledger import Entry, Ledger
from lab_commons.compute.model import Candidate, Demand, For, Ranked, Reservation, Resources, Supply
from lab_commons.config import CONFIG_ENV
from lab_commons.dev import forgehosts, forgeproduce, forgerounds, forgerun, forgeserve, forgeship
from lab_commons.dev.forgealarm import AUTH, IDLE, RUN, STARVED
from lab_commons.dev.forgeclaim import OPEN, Claim, Work
from lab_commons.dev.forgetick import TickReport
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report
from lab_commons.dev.platformparts import ClusterPart
from lab_commons.dev.producer import PRODUCING_VAR, RETRYABLE, ProducerExit, release_reason
from lab_commons.dev.shatree import Tree, TreeFailed
from lab_commons.hpc.account import ClusterAccount
from lab_commons.hpc.shell import FULL
from lab_commons.resources import CPU, MEMORY, Holder, JobHandle

SHA = 'a' * 40
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
FORGE_NOW = NOW + timedelta(minutes=7)  # the forge's clock, deliberately not the host's
ME = Claim('G', 'alice', NOW + timedelta(hours=6))
SEAT = ClusterAccount('ada', 'alice')


class _Proc:
    """A fake producer: prints *lines*, outlives *beats* heartbeats, exits *code*."""

    def __init__(self, code: int, lines: tuple[str, ...] = (), beats: int = 0, pid: int | None = None) -> None:
        self.code, self.beats, self.pid = code, beats, pid
        self.stdout = iter(f'{line}\n' for line in lines)

    def wait(self, timeout: float | None = None) -> int:
        if self.beats:
            self.beats -= 1
            cmd = 'fake'
            raise subprocess.TimeoutExpired(cmd, timeout or 0)
        return self.code

    def kill(self) -> None:
        self.beats = 0


class _Forge:
    """Records every status post; a part's producer may post its own verdict."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str]] = []

    def post(self, _client, _sha, *, context, state, description) -> None:
        self.posts.append((context, state, description))

    def history(self, _client, _sha) -> tuple[SimpleNamespace, ...]:
        return tuple(SimpleNamespace(context=c, state=s, description=d) for c, s, d in self.posts)


class _Trees:
    """The producer's per-sha trees: which were opened and closed; *refuse* makes opening one fail."""

    def __init__(self, tmp_path: Path, refuse: str = '') -> None:
        self.base, self.refuse = tmp_path / 'trees', refuse
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.logs: list[str] = []

    def open(self, _root: Path, sha: str) -> Tree:
        self.opened.append(sha)
        if self.refuse:
            raise TreeFailed(self.refuse)
        return Tree(self.base / sha[:12], self.base / sha[:12] / 'python')

    def close(self, _root: Path, sha: str, *, log: str = '') -> str:
        self.closed.append(sha)
        self.logs.append(log)
        return f'tree {sha[:12]}: removed'


def _client(_root: Path) -> SimpleNamespace:
    return SimpleNamespace(answered=format_datetime(FORGE_NOW, usegmt=True), whoami=lambda: 'alice')


def _serve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ticked: TickReport,
    procs: dict[str, _Proc] | None = None,
    forge: _Forge | None = None,
    *,
    seat: ClusterAccount | None = None,
    cluster=lambda: None,
    spawned: list[dict] | None = None,
    cards: list | None = None,
    host: str | None = None,
    tidy=lambda _root, _client, **_kw: (),
    trees: _Trees | None = None,
    seen: dict[str, object] | None = None,
    holders: tuple[Holder, ...] = (),
    book: Ledger | None = None,
    later: tuple[TickReport, ...] = (),
    ticks: list[dict] | None = None,
    table: dict | None = None,
) -> tuple[forgeserve.ServeReport, list[str], list]:
    """Serve once: the first round's tick answers *ticked*, each later one the next of *later*, then nothing.

    *seen* is what the FIRST tick was given; *ticks* collects what every tick was given.
    """
    said: list[str] = []
    alarms: list = []
    forge = forge or _Forge()
    seen = seen if seen is not None else {}
    cards = cards if cards is not None else []

    answers = iter((ticked, *later))
    given: list[dict] = ticks if ticks is not None else []

    def tick(*_a: object, **kwargs: object) -> TickReport:
        if not given:
            seen.update(kwargs)
        given.append(kwargs)
        return next(answers, TickReport((), (), ()))

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgerounds, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgehosts, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgeserve, 'flush', lambda _root, **_k: ['status: tests/windows=failure'])
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgehosts, 'publish', lambda _client, card: cards.append(card) or 'updated')
    monkeypatch.setattr(forgeship, 'tidy', tidy)
    trees = trees or _Trees(tmp_path)
    monkeypatch.setattr(forgeproduce, 'open_tree', trees.open)
    monkeypatch.setattr(forgeproduce, 'close_tree', trees.close)

    def spawn(argv: list[str], **kwargs: object) -> _Proc:
        (spawned if spawned is not None else []).append({'argv': argv, **kwargs})
        return (procs or {})[argv[1]]  # argv[0] is the tree's own interpreter

    report = forgeserve.serve(
        tmp_path,
        'integrate',
        client=_client,
        machine='G',
        seat=seat,
        cluster=cluster,
        spawn=spawn,
        clock=lambda: NOW,
        say=said.append,
        alarm=alarms.append,
        renew_s=0.01,
        box_room=lambda scope, **_: Supply(scope, Resources(cpu=4, mem_gb=32)),
        table=table or {},
        fetch=lambda _root: None,
        host=host,
        reserve=lambda: Resources(cpu=1, mem_gb=8),
        holders=lambda: holders,
        read_ledger=lambda _client: book or Ledger(None, {}, ()),
    )
    said.append(f'running={seen.get("running")}')
    return report, said, alarms


class _Slurm:
    """The Slurm side as serve reads it before the tick: a standing, and jobs it may cancel."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def standing(self) -> forgerun.Standing:
        return forgerun.Standing(
            Supply('slurm:alice', Resources(cpu=64, mem_gb=128, submits=10)), {}, {'partitions': {'defq': 2880}}
        )

    def cancel(self, run: forgerun.Run) -> list[str]:
        self.cancelled += run.job_ids
        return list(run.job_ids)


def _claimed(*work: Work) -> TickReport:
    return TickReport(work, work, ('tick: one line',))


def test_the_producers_streamed_output_reaches_the_tree_closer(monkeypatch, tmp_path: Path) -> None:
    """The run's log reaches :func:`close_tree`, which keeps it in the serving checkout before removing the tree."""
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    trees = _Trees(tmp_path)
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1, ('collected 9', '1 failed'))}, trees=trees)
    assert trees.closed == [SHA]
    assert trees.logs == ['collected 9\n1 failed\n']


def test_a_claimed_local_part_is_produced_inline_and_published(monkeypatch, tmp_path: Path) -> None:
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    report, said, _alarms = _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1, ('collected 9',))})
    assert [(p.platform, p.returncode) for p in report.produced] == [('windows', 1)], 'a red part is not a failure'
    assert report.published == ('status: tests/windows=failure',)
    assert report.broken == ()
    assert 'tick: one line' in said
    assert '[windows] collected 9' in said


def test_the_producer_is_spawned_holding_its_claim_and_nothing_else_is(monkeypatch, tmp_path: Path) -> None:
    """VERDICTS-FROM-THE-FORGE: serve is the one door to a full suite -- its producer carries the part it claimed."""
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    spawned: list[dict] = []
    monkeypatch.delenv(PRODUCING_VAR, raising=False)
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, spawned=spawned)
    assert [kwargs['env'][PRODUCING_VAR] for kwargs in spawned] == [f'tests/windows@{SHA}']
    assert PRODUCING_VAR not in os.environ, "the claim is the child's, never leaked into serve itself"


def test_a_producer_refusing_its_argv_is_a_broken_contract_not_a_skip(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: a renamed flag makes argparse exit 2; that must surface as a failure with the argv shown."""
    stale = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify', '--install', 'x'))
    report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(stale), {'verify': _Proc(ProducerExit.USAGE)})
    assert len(report.broken) == 1
    assert 'verify --install x' in report.broken[0]


def test_the_cli_exits_two_on_a_broken_contract(monkeypatch, tmp_path: Path, capsys) -> None:
    broken = forgeserve.ServeReport((), (), (), (), ('windows aaaa: the producer refused its argv: verify --x',))
    monkeypatch.setattr(forgeserve, 'serve', lambda *_a, **_k: broken)
    assert forgeserve.main(['--mode', 'integrate'], cwd=tmp_path, seat_of=lambda: None) == ProducerExit.USAGE
    assert 'CONTRACT BROKEN' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        forgeserve.main(['--mode', 'nonsense'], cwd=tmp_path)


def test_a_live_local_producer_renews_its_claim_on_the_forges_clock(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0, beats=2)}, forge)
    renewed = [d for c, s, d in forge.posts if c == 'tests/windows' and s == 'pending']
    assert len(renewed) == 2
    assert Claim.parse(renewed[0]) == dataclasses.replace(ME, until=FORGE_NOW + forgeserve.DEFAULT_LEASE)


def test_a_producing_host_keeps_publishing_its_card_while_the_producer_runs(monkeypatch, tmp_path: Path) -> None:
    """A part runs for hours inline; the card must tick at the tick period, holding the part, so STALE means down."""
    forge, cards = _Forge(), []
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0, beats=3)}, forge, cards=cards)
    during = cards[:-1]  # the last card is the one published after the tick
    assert len(during) == 3, 'one card per heartbeat while producing'
    assert all(card.holds[0].startswith(f'{SHA[:12]} windows producing') for card in during)
    assert len([d for c, s, d in forge.posts if s == 'pending']) == 3, 'every beat inside the renew interval renews'


def test_a_beat_shorter_than_the_renewal_renews_only_when_the_renewal_is_due(monkeypatch, tmp_path: Path) -> None:
    """The card beats at the tick period; the claim is still renewed on its own, longer, cadence."""
    forge, beats = _Forge(), []
    item = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgeproduce, 'open_tree', _Trees(tmp_path).open)
    monkeypatch.setattr(forgeproduce, 'close_tree', _Trees(tmp_path).close)
    monkeypatch.setattr(forgeproduce, 'tip_of', lambda _root, _ref: SHA)
    waits: list[float | None] = []
    proc = _Proc(0, beats=6)
    inner = proc.wait
    monkeypatch.setattr(proc, 'wait', lambda timeout=None: waits.append(timeout) or inner(timeout))
    forgeproduce.produce(
        tmp_path, item, client=_client, spawn=lambda *_a, **_k: proc, clock=lambda: NOW, say=lambda _l: None,
        lease=timedelta(hours=6), renew_s=30.0, beat_s=10.0, beat=beats.append, fetch=lambda _root: None,
    )  # fmt: skip
    assert waits[0] == 10.0, 'the loop wakes at the beat, not the lease third'
    assert len(beats) == 6
    assert len([d for c, s, d in forge.posts if s == 'pending']) == 2, 'renewed on beats 3 and 6 only'


def test_a_crashed_producer_releases_its_claim(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: the producer dies without posting; its pending claim must not be left to age out."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(-9)}, forge)
    assert forge.posts[-1] == ('tests/windows', 'error', 'released: producer crashed (exit -9)')


def test_a_local_part_is_judged_in_its_own_tree_at_the_claimed_sha(monkeypatch, tmp_path: Path) -> None:
    """PLANTED (live 2026-10-12, 4e394b6): the serving checkout sat at e9bc0d4 and verify judged THAT.

    The producer runs the declared argv with the interpreter of a tree AT the claimed sha, in that tree,
    and removes the tree afterwards -- the serving checkout (``tmp_path``) is never the cwd.
    """
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify', '--full'))
    trees, spawned = _Trees(tmp_path), []
    report, said, _alarms = _serve(
        monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, spawned=spawned, trees=trees
    )
    tree = tmp_path / 'trees' / SHA[:12]
    assert [(k['argv'], k['cwd']) for k in spawned] == [([str(tree / 'python'), 'verify', '--full'], tree)]
    assert (trees.opened, trees.closed) == ([SHA], [SHA])
    assert report.produced[0].argv == (str(tree / 'python'), 'verify', '--full')
    assert f'[windows] tree {SHA[:12]}: removed' in said


def test_a_tree_that_cannot_be_built_spawns_nothing_and_names_the_step(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    trees, spawned = _Trees(tmp_path, refuse='dep --bootstrap exited 1: no lock'), []
    report, _said, _alarms = _serve(
        monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0)}, forge, spawned=spawned, trees=trees
    )
    assert spawned == []
    assert report.produced[0].returncode == ProducerExit.INCONCLUSIVE
    assert forge.posts[-1] == (
        'tests/windows',
        'error',
        f'released: no tree at {SHA[:12]} -- dep --bootstrap exited 1: no lock',
    )
    assert trees.closed == [SHA], 'a half-built tree is removed too'


def test_a_producer_that_posted_its_part_is_left_alone(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='failure', description='FAIL')
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1)}, forge)
    assert forge.posts == [('tests/windows', 'failure', 'FAIL')]


def test_inconclusive_and_unreachable_producers_are_released_never_red(monkeypatch, tmp_path: Path) -> None:
    """PLANTED (live 2026-10-11): a runner over its wall said INCONCLUSIVE; serve said "refused its argv"."""
    for code, reason in (
        (ProducerExit.INCONCLUSIVE, release_reason(ProducerExit.INCONCLUSIVE)),
        (ProducerExit.UNREACHABLE, RETRYABLE),
    ):
        forge = _Forge()
        forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
        local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
        report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(code)}, forge)
        assert report.broken == ()
        assert forge.posts[-1][1] == 'error'
        assert forge.posts[-1][2].startswith(reason)


def test_a_claimed_cluster_part_starts_a_run_and_is_advanced_never_spawned(monkeypatch, tmp_path: Path) -> None:
    cluster_claim = dataclasses.replace(ME, hpc='ada/alice')
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    work = Work('integrate/main', SHA, 'base', 'mine', cluster_claim, cluster=part)
    advanced: list[tuple[str, str]] = []

    def advance(_root: Path, run: forgerun.Run, **kwargs: object) -> forgerun.Run:
        me = kwargs['me']
        assert isinstance(me, Claim)
        advanced.append((run.phase, me.hpc))
        return run

    monkeypatch.setattr(forgerun, 'advance', advance)
    report, said, _alarms = _serve(monkeypatch, tmp_path, _claimed(work), seat=SEAT, cluster=_Slurm)
    assert report.produced == (), 'a cluster part is never a blocking process'
    assert advanced == [(forgerun.CLAIMED_PHASE, 'ada/alice')]
    assert report.in_flight == (SHA,)
    assert 'running=[]' in said
    report, said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm)
    assert f'running={[Demand(cpu=1)]}' in said, 'the next tick reads the run back from disk as running demand'
    assert len(advanced) == 2


def test_a_run_with_no_cluster_to_advance_on_alarms_and_waits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    forgerun.start(Work('integrate/main', SHA, 'base', 'mine', ME, cluster=part), ME)

    def no_grant() -> None:
        msg = 'no [[hpc.grant]] has user = "alice"'
        raise ValueError(msg)

    report, _said, alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=no_grant)
    assert [a.kind for a in alarms] == [RUN]
    assert report.in_flight == (SHA,)
    assert len(forgerun.live('https://f/o/r.git')) == 1, 'the run is kept for the next tick'


def test_the_alarms_a_tick_raises_ride_on_its_host_card(monkeypatch, tmp_path: Path) -> None:
    """A stuck run is read from the forge, not from a cron log. PLANTED CONTROL: a calm tick's card is clean."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    cards: list = []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, cards=cards, host='base')
    assert cards[-1].alarms == ()
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    forgerun.start(Work('integrate/main', SHA, 'base', 'mine', ME, cluster=part), ME)

    def no_grant() -> None:
        msg = 'no [[hpc.grant]] has user = "alice"'
        raise ValueError(msg)

    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=no_grant, cards=cards, host='base')
    (raised,) = cards[-1].alarms
    assert raised['kind'] == RUN
    assert raised['subject'] == f'the cluster run of {SHA[:12]} cannot advance'
    assert 'no [[hpc.grant]]' in raised['body']


def test_an_account_idle_with_work_pending_alarms(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same pending request, claimed, raises nothing."""
    pending = Work('integrate/main', SHA, 'windows', OPEN)
    idle = TickReport((pending,), (), ('tick',), ('tests/windows: not claimed -- no produce declared',))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, idle)
    assert [a.kind for a in alarms] == [IDLE]
    assert 'not claimed' in alarms[0].body
    claimed = dataclasses.replace(pending, state='mine', holder=ME, argv=('verify',))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, _claimed(claimed), {'verify': _Proc(0)})
    assert alarms == []


def test_a_refused_credential_alarms_and_still_fails(monkeypatch, tmp_path: Path) -> None:
    refused = Report(('GET', '/api/v1/user'), (Attempt(1, 401, 'unauthorized', Diagnosis.FORGE_REFUSED),), 3)

    def tick(*_a: object, **_k: object) -> TickReport:
        raise ForgeCallFailed(refused)

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))  # never this box's own machine file
    monkeypatch.setattr(forgerounds, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    alarms: list = []
    with pytest.raises(ForgeCallFailed):
        forgeserve.serve(
            tmp_path, 'integrate', client=_client, machine='G', seat=None, cluster=lambda: None, alarm=alarms.append,
            box_room=lambda scope, **_: Supply(scope, Resources(cpu=4)), table={},
            reserve=Resources, holders=tuple, read_ledger=lambda _client: Ledger(None, {}, ()),
        )  # fmt: skip
    assert [a.kind for a in alarms] == [AUTH]


def _waiting(kind: str, waited_h: float, blocked: str) -> Ranked:
    one = Candidate('o/r', 'feat/x', SHA, 'windows', kind, NOW - timedelta(hours=waited_h), FULL)
    return Ranked(one, 60.0, 4.0, 15.0, waited_h, blocked)


def test_a_candidate_waiting_past_its_bound_raises_a_starved_alarm_naming_why(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROLS: the same wait unblocked, and a blocked wait under the bound, raise nothing."""
    jammed = TickReport((), (), ('tick',), (), (_waiting('pr', 13, 'not admitted: lacking cpu, mem_gb'),))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, jammed)
    (alarm,) = alarms
    assert (alarm.kind, alarm.about) == (STARVED, f'feat/x@{SHA[:12]}:windows')
    assert 'waited 13.0 h, past its 12 h bound' in alarm.body
    assert 'not admitted: lacking cpu, mem_gb' in alarm.body, 'the starved alarm names the resources it lacks'
    calm = TickReport((), (), ('tick',), (), (_waiting('pr', 13, ''), _waiting('pr', 11, 'not admitted: lacking cpu')))
    assert _serve(monkeypatch, tmp_path, calm)[2] == []


def test_every_tick_publishes_the_host_card(monkeypatch, tmp_path: Path) -> None:
    """Who it is, what it serves, its supply and facts, its live reservations, and why each candidate waits."""
    cards: list = []
    ticked = TickReport((), (), ('tick',), (), (_waiting('pr', 1, 'not admitted: lacking cpu'),))
    mine = _lease(1, 'ada/alice')
    book = Ledger(1, {}, (mine, _lease(2, 'ada/bob'), _lease(3, 'ada/alice', until=NOW)))
    _serve(monkeypatch, tmp_path, ticked, seat=SEAT, cluster=_Slurm, cards=cards, host='base', book=book)
    (card,) = cards
    assert (card.host, card.login, card.platform) == ('ada/alice', 'alice', 'base')
    assert card.supply == {'cpu': 64.0, 'mem_gb': 128.0, 'submits': 10.0}
    assert card.facts == {'partitions': {'defq': 2880}}
    assert card.ticked == FORGE_NOW.isoformat(), "the forge's clock, never the host's"
    assert card.waiting == {f'feat/x@{SHA[:12]}:windows': 'not admitted: lacking cpu'}
    assert card.reservations == (mine.row(),), 'the live leases on THIS host: not another, not an expired one'


def _lease(lease_id: int, scope: str, *, until: datetime = NOW + timedelta(days=1), refused: str = '') -> Entry:
    return Entry(lease_id, Reservation(scope, Resources(cpu=2), For(login='bob'), until, 'alice'), refused)


def _holder(what: str, **demands: int) -> Holder:
    return Holder('lab-commons-cpu', JobHandle('pid', '1'), what, demands)


def test_a_box_admits_against_its_probe_less_its_own_reserve(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seen=seen)
    supply = seen['supply']
    assert isinstance(supply, Supply)
    assert (supply.scope, dict(supply.resources)) == ('G', {'cpu': 3.0, 'mem_gb': 24.0}), 'probe 4/32 less 1/8'


def test_an_interactive_run_holding_the_box_seat_counts_as_running(monkeypatch, tmp_path: Path) -> None:
    """At what it declared; the whole box when it declared nothing. PLANTED CONTROL: no holder, nothing runs."""
    seen: dict[str, object] = {}
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seen=seen)
    assert seen['running'] == []
    declared = _holder('gate measure', **{CPU.name: 2, MEMORY.name: 4 * 1024**3})
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seen=seen, holders=(declared, _holder('verify:x')))
    assert seen['running'] == [Demand(cpu=2, mem_gb=4), Demand(cpu=os.cpu_count() or 1)]


def test_every_authorised_lease_reaches_the_admission_and_a_refused_one_never(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    held, refused = _lease(1, 'G'), _lease(2, 'G', refused='bob may not reserve G')
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seen=seen, book=Ledger(1, {}, (held, refused)))
    assert seen['reservations'] == (held.reservation,)


def test_two_admitted_local_parts_are_produced_at_once(monkeypatch, tmp_path: Path) -> None:
    """Each part runs in its own thread with its own claim: the first producer waits until the second started.

    Sequential production would deadlock the first on that wait (bounded: it then fails the assertion).
    """
    other = 'b' * 40
    first = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('first',))
    second = Work('feat/a', other, 'windows', 'mine', ME, argv=('second',))
    started = threading.Event()

    class _Waits(_Proc):
        def wait(self, timeout: float | None = None) -> int:
            assert started.wait(timeout=10), 'the second producer never started while the first ran'
            return super().wait(timeout)

    class _Starts(_Proc):
        def wait(self, timeout: float | None = None) -> int:
            started.set()
            return super().wait(timeout)

    procs = {'first': _Waits(0), 'second': _Starts(1)}
    spawned: list[dict] = []
    trees = _Trees(tmp_path)
    report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(first, second), procs, spawned=spawned, trees=trees)
    assert [(p.sha, p.returncode) for p in report.produced] == [(SHA, 0), (other, 1)], 'reported in claim order'
    assert sorted(trees.closed) == sorted([SHA, other]), 'each part in its own tree'


def _moved_on(tmp_path: Path) -> str:
    """*tmp_path* as a checkout whose origin integrate/main moved past :data:`SHA`; the new tip."""
    run_git(tmp_path, 'init', '-q')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x')
    tip = git_out(tmp_path, 'rev-parse', 'HEAD')
    run_git(tmp_path, 'update-ref', 'refs/remotes/origin/integrate/main', tip)
    return tip


def test_a_superseded_cluster_run_is_cancelled_and_released(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: the ref still at the run's sha -- the run is kept and advanced."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    forge = _Forge()
    monkeypatch.setattr(forgerun, 'status_post', forge.post)
    monkeypatch.setattr(forgerun, 'advance', lambda _root, run, **_k: run)
    run = forgerun.Run('https://f/o/r.git', SHA, 'integrate/main', 'tests', str(tmp_path), ME.description(),
                       phase=forgerun.SUBMITTED, job_ids=('77',))  # fmt: skip
    forgerun.save(run)
    kept, _said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm)
    assert kept.in_flight == (SHA,)
    tip = _moved_on(tmp_path)
    slurm = _Slurm()
    report, said, _alarms = _serve(
        monkeypatch, tmp_path, TickReport((), (), ()), forge, seat=SEAT, cluster=lambda: slurm
    )
    assert report.in_flight == ()
    assert slurm.cancelled == ['77']
    assert forge.posts[-1] == ('tests/base', 'error', f'superseded by {tip[:12]}')
    assert forgerun.live('https://f/o/r.git') == ()
    assert any('superseded' in line for line in said)


def test_a_superseded_local_producer_is_stopped_and_released(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: a heartbeat on an unmoved ref only renews (the renewal test above)."""
    tip = _moved_on(tmp_path)
    forge = _Forge()
    item = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    proc = _Proc(0, beats=5)
    report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(item), {'verify': proc}, forge)
    assert report.produced[0].returncode == 0
    assert proc.beats == 0, 'killed at the first heartbeat'
    assert forge.posts[-1] == ('tests/windows', 'error', f'superseded by {tip[:12]}')


def test_only_a_cluster_host_cleans_the_artefact_stores_and_a_failed_cleanup_alarms(
    monkeypatch, tmp_path: Path
) -> None:
    """PLANTED CONTROL: the same serve off a cluster (no seat) never cleans -- a workstation only reads."""
    cleaned: list[tuple[Path, str]] = []

    def tidy(root: Path, _client: object, *, account: str, say: object) -> tuple[str, ...]:
        del say
        cleaned.append((root, account))
        return ()

    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=None, tidy=tidy)
    assert cleaned == []
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, tidy=tidy)
    assert cleaned == [(tmp_path, SEAT.account)], "it cleans its own account's runs only"

    def broken(_root: Path, _client: object, **_kw: object) -> tuple[str, ...]:
        msg = 'rclone lsjson exited 1'
        raise OSError(msg)

    _report, _said, alarms = _serve(
        monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, tidy=broken
    )
    assert [a.kind for a in alarms] == [RUN]


def test_every_tick_offers_the_branch_prune_its_host_card_name(monkeypatch, tmp_path: Path) -> None:
    """The prune decides ownership itself (``[tool.lab_commons.integrator] host``); serve hands it who this is."""
    offered: list[dict] = []

    def prune(root: Path, _client: object, **kwargs: object) -> tuple[()]:
        offered.append({'root': root, 'host': kwargs['host']})
        return ()

    monkeypatch.setattr(forgeserve, 'serve_prune', prune)
    _serve(monkeypatch, tmp_path, TickReport((), (), ()))
    assert offered == [{'root': tmp_path, 'host': forgeserve.card_host('G', None)}]


def test_a_producer_stopped_on_purpose_releases_its_claim_as_stopped(monkeypatch, tmp_path: Path) -> None:
    """A stop door notes a serve's producer before it kills it; the serve names the release ``stopped``, not a crash."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    proc = _Proc(1, pid=77)
    monkeypatch.setattr(forgeproduce, 'was_stopped', lambda pid: pid == 77)
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': proc}, forge)
    assert forge.posts[-1] == ('tests/windows', 'error', 'stopped')


def _produce_one(monkeypatch, tmp_path: Path, proc: _Proc, **kwargs: object) -> forgeproduce.Produced:
    """One local part through :func:`forgeproduce.produce`, every forge and tree seam faked."""
    forge = _Forge()
    item = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgeproduce, 'open_tree', _Trees(tmp_path).open)
    monkeypatch.setattr(forgeproduce, 'close_tree', _Trees(tmp_path).close)
    monkeypatch.setattr(forgeproduce, 'tip_of', lambda _root, _ref: SHA)
    monkeypatch.setattr(forgeproduce, 'was_stopped', lambda _pid: False)
    return forgeproduce.produce(
        tmp_path, item, client=_client, spawn=lambda *_a, **_k: proc, say=lambda _l: None,
        lease=timedelta(hours=6), renew_s=30.0, fetch=lambda _root: None, **kwargs,
    )  # fmt: skip


def test_a_finished_box_run_learns_its_peak_wall_and_measured_cpu(monkeypatch, tmp_path: Path) -> None:
    """The box half of the one demand table: the tree's peak and its MEASURED cpu-seconds, never wall x cores."""
    learnt: list = []
    gb, cpu = iter([2.0, None, 3.5, 1.0]), iter([10.0, None, 30.0, 45.0])
    ticks = iter(NOW + timedelta(seconds=s) for s in range(0, 1000, 10))
    _produce_one(
        monkeypatch, tmp_path, _Proc(0, beats=4, pid=4242), clock=lambda: next(ticks),
        sample=lambda _pid: next(gb), meter=lambda _pid: lambda: next(cpu),
        learn=lambda *a, **k: learnt.append((a, k)),
    )  # fmt: skip
    ((root, done, run), how) = learnt[0]
    assert (root, done.platform, run.peak_mem_gb, run.cpu_s, how) == (tmp_path, 'windows', 3.5, 45.0, {'killed': False})
    assert run.wall_s > 0


def test_a_run_never_sampled_learns_nothing(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: no wake, no reading -- nothing is learned."""
    learnt: list = []
    _produce_one(
        monkeypatch, tmp_path, _Proc(0, beats=0, pid=4242), clock=lambda: NOW,
        sample=lambda _pid: 1.0, meter=lambda _pid: lambda: 5.0, learn=lambda *a, **_k: learnt.append(a),
    )  # fmt: skip
    assert learnt == []


def test_a_run_with_no_cpu_reading_learns_nothing(monkeypatch, tmp_path: Path) -> None:
    """A tree whose cpu cannot be read records no demand: an unmeasured cpu is never invented."""
    learnt: list = []
    _produce_one(
        monkeypatch, tmp_path, _Proc(0, beats=2, pid=4242), clock=lambda: NOW,
        sample=lambda _pid: 1.0, meter=lambda _pid: lambda: None, learn=lambda *a, **_k: learnt.append(a),
    )  # fmt: skip
    assert learnt == []


def test_each_wake_hands_watch_the_cores_busy_since_the_last(monkeypatch, tmp_path: Path) -> None:
    """What the producer's tree uses NOW, for a serve that keeps claiming while it runs."""
    watched: list[Resources] = []
    clock = {'now': NOW}
    readings = iter([20.0, 50.0])

    def cpu() -> float:  # ten seconds pass between two readings of the tree
        clock['now'] += timedelta(seconds=10)
        return next(readings)

    _produce_one(
        monkeypatch, tmp_path, _Proc(0, beats=2, pid=4242), clock=lambda: clock['now'],
        sample=lambda _pid: 2.0, meter=lambda _pid: cpu, learn=lambda *_a, **_k: None, watch=watched.append,
    )  # fmt: skip
    assert [(one['cpu'], one['mem_gb']) for one in watched] == [(2.0, 2.0), (3.0, 2.0)]


class _Until(_Proc):
    """A producer that lives, beating, until *event* is set."""

    def __init__(self, event: threading.Event, code: int = 0, pid: int | None = None) -> None:
        super().__init__(code, pid=pid)
        self.event = event

    def wait(self, timeout: float | None = None) -> int:
        if self.event.wait(timeout=timeout):
            return self.code
        cmd = 'fake'
        raise subprocess.TimeoutExpired(cmd, timeout or 0)


class _Sets(_Proc):
    """A producer that beats *beats* times (a little apart), then sets *event* and exits."""

    def __init__(self, event: threading.Event, code: int = 0, beats: int = 0, pid: int | None = None) -> None:
        super().__init__(code, beats=beats, pid=pid)
        self.event = event

    def wait(self, timeout: float | None = None) -> int:
        if self.beats:
            self.event.wait(timeout=0.02)
        code = super().wait(timeout)
        self.event.set()
        return code


#: A tick period short enough that a second round comes while a producer runs.
QUICK = {'tick_minutes': 0.001}


def test_a_host_producing_one_part_claims_another_that_fits_while_it_runs(monkeypatch, tmp_path: Path) -> None:
    """Serve keeps ticking while a producer lives: the next round sees it RUNNING and its sha BUSY, and claims more.

    The first producer lives until the second ends, so the second can only have been claimed while it ran.
    """
    other = 'b' * 40
    first = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('first',))
    second = Work('feat/a', other, 'windows', 'mine', ME, argv=('second',))
    second_done = threading.Event()
    procs = {'first': _Until(second_done), 'second': _Sets(second_done, code=1, beats=3)}
    ticks: list[dict] = []
    cards: list = []
    report, _said, _alarms = _serve(
        monkeypatch, tmp_path, _claimed(first), procs, ticks=ticks, later=(_claimed(second),), table=QUICK, cards=cards,
    )  # fmt: skip
    assert [(p.sha, p.returncode) for p in report.produced] == [(SHA, 0), (other, 1)], 'in start order'
    assert ticks[0]['busy'] == frozenset()
    assert ticks[1]['busy'] == frozenset({SHA}), 'the tree of a part being produced is taken'
    assert len(ticks[1]['running']) == len(ticks[0]['running']) + 1, 'the live producer runs at its demand'
    assert any(len(card.holds) == 2 for card in cards), 'a card while both run names both'
    assert report.tick == ('tick: one line', 'tick: one line'), 'every round says what it claimed'


def test_a_producer_stopped_on_purpose_ends_the_claiming(monkeypatch, tmp_path: Path) -> None:
    """A stop (stoprun) means serve exits: no round after it, the live producer is waited for, nothing new starts.

    PLANTED CONTROL: the same two producers, neither stopped, and a later round runs.
    """
    other, third = 'b' * 40, 'c' * 40
    claims = (
        Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('stopped',)),
        Work('feat/a', other, 'windows', 'mine', ME, argv=('lives',)),
    )
    later = (_claimed(Work('feat/b', third, 'windows', 'mine', ME, argv=('never',))),)

    def run(stopped_pid: int) -> tuple[list[dict], list[dict]]:
        ended = threading.Event()
        procs = {
            'stopped': _Sets(ended, code=-9, pid=77),
            'lives': _Sets(threading.Event(), beats=10),
            'never': _Proc(0),
        }
        monkeypatch.setattr(forgeproduce, 'was_stopped', lambda pid: pid == stopped_pid)
        ticks: list[dict] = []
        spawned: list[dict] = []
        _serve(
            monkeypatch, tmp_path, _claimed(*claims), procs, ticks=ticks, later=later, table=QUICK, spawned=spawned,
        )  # fmt: skip
        return ticks, spawned

    ticks, spawned = run(77)
    assert len(ticks) == 1
    assert [one['argv'][1] for one in spawned] == ['stopped', 'lives']
    ticks, _spawned = run(0)
    assert len(ticks) >= 2, 'PLANTED CONTROL: a crash is not a stop; the host claims on'


def test_a_round_that_raises_joins_every_producer_first(monkeypatch, tmp_path: Path) -> None:
    """No producer thread outlives serve: a later round failing waits for the live producer before it raises."""
    ended = threading.Event()
    first = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('first',))
    procs = {'first': _Sets(ended, beats=20)}
    failed = ForgeCallFailed(Report(('GET', '/x'), (Attempt(1, 128, 'boom', Diagnosis.TRANSIENT),), 3))
    calls: list[int] = []

    def tick(*_a: object, **_k: object) -> TickReport:
        calls.append(1)
        if len(calls) > 1:
            raise failed
        return _claimed(first)

    monkeypatch.setattr(forgerounds, '_tick', lambda *_a, **kw: tick(**kw))
    with pytest.raises(ForgeCallFailed):
        _serve(monkeypatch, tmp_path, _claimed(first), procs, table=QUICK)
    assert ended.is_set(), 'the producer ended before serve raised'
    assert not [t for t in threading.enumerate() if t.name.startswith('produce-')]
