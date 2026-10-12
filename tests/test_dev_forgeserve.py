"""THE HARNESS ENTRY: tick, produce or advance, publish -- a contract break fails loudly, a silent failure alarms."""

from __future__ import annotations

import dataclasses
import os
import subprocess
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_fake import git_out, run_git

from lab_commons.config import CONFIG_ENV
from lab_commons.dev import forgehosts, forgerun, forgeserve, forgeship
from lab_commons.dev.forgealarm import AUTH, IDLE, RUN, STARVED
from lab_commons.dev.forgeclaim import OPEN, Claim, Work
from lab_commons.dev.forgeschedule import Candidate, Headroom, Ranked
from lab_commons.dev.forgetick import TickReport
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report
from lab_commons.dev.platformparts import ClusterPart
from lab_commons.dev.producer import PRODUCING_VAR, RETRYABLE, ProducerExit, release_reason
from lab_commons.hpc.account import ClusterAccount

SHA = 'a' * 40
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
FORGE_NOW = NOW + timedelta(minutes=7)  # the forge's clock, deliberately not the host's
ME = Claim('G', 'alice', NOW + timedelta(hours=6))
SEAT = ClusterAccount('ada', 'alice')


class _Proc:
    """A fake producer: prints *lines*, outlives *beats* heartbeats, exits *code*."""

    def __init__(self, code: int, lines: tuple[str, ...] = (), beats: int = 0) -> None:
        self.code, self.beats = code, beats
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
) -> tuple[forgeserve.ServeReport, list[str], list]:
    said: list[str] = []
    alarms: list = []
    forge = forge or _Forge()
    seen: dict[str, object] = {}
    cards = cards if cards is not None else []

    def tick(*_a: object, **kwargs: object) -> TickReport:
        seen.update(kwargs)
        return ticked

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgeserve, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgehosts, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgeserve, 'flush', lambda _root, **_k: ['status: tests/windows=failure'])
    monkeypatch.setattr(forgeserve, 'status_post', forge.post)
    monkeypatch.setattr(forgeserve, 'status_history', forge.history)
    monkeypatch.setattr(forgehosts, 'publish', lambda _client, card: cards.append(card) or 'updated')
    monkeypatch.setattr(forgeship, 'tidy', tidy)
    report = forgeserve.serve(
        tmp_path,
        'integrate',
        client=_client,
        machine='G',
        seat=seat,
        cluster=cluster,
        spawn=lambda argv, **k: ((spawned if spawned is not None else []).append(k), (procs or {})[argv[0]])[1],
        clock=lambda: NOW,
        say=said.append,
        alarm=alarms.append,
        renew_s=0.01,
        box_room=lambda: Headroom(cores=4),
        table={},
        fetch=lambda _root: None,
        host=host,
    )
    said.append(f'in_flight={seen.get("in_flight")}')
    return report, said, alarms


class _Slurm:
    """The Slurm side as serve reads it before the tick: a standing, and jobs it may cancel."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def standing(self) -> forgerun.Standing:
        return forgerun.Standing(Headroom(cores=64, submits=10), {}, {'partitions': {'defq': 2880}})

    def cancel(self, run: forgerun.Run) -> list[str]:
        self.cancelled += run.job_ids
        return list(run.job_ids)


def _claimed(*work: Work) -> TickReport:
    return TickReport(work, work, ('tick: one line',))


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


def test_a_crashed_producer_releases_its_claim(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: the producer dies without posting; its pending claim must not be left to age out."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(-9)}, forge)
    assert forge.posts[-1] == ('tests/windows', 'error', 'released: producer crashed (exit -9)')


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
    work = Work('integrate/main', SHA, 'linux', 'mine', cluster_claim, cluster=part)
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
    assert 'in_flight=False' in said
    report, said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm)
    assert 'in_flight=True' in said, 'the next tick reads the run back from disk and claims nothing more'
    assert len(advanced) == 2


def test_a_run_with_no_cluster_to_advance_on_alarms_and_waits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    forgerun.start(Work('integrate/main', SHA, 'linux', 'mine', ME, cluster=part), ME)

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
    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=_Slurm, cards=cards, host='linux')
    assert cards[-1].alarms == ()
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    forgerun.start(Work('integrate/main', SHA, 'linux', 'mine', ME, cluster=part), ME)

    def no_grant() -> None:
        msg = 'no [[hpc.grant]] has user = "alice"'
        raise ValueError(msg)

    _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=no_grant, cards=cards, host='linux')
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

    monkeypatch.setattr(forgeserve, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    alarms: list = []
    with pytest.raises(ForgeCallFailed):
        forgeserve.serve(
            tmp_path, 'integrate', client=_client, machine='G', seat=None, cluster=lambda: None, alarm=alarms.append,
            box_room=lambda: Headroom(cores=4), table={},
        )  # fmt: skip
    assert [a.kind for a in alarms] == [AUTH]


def _waiting(kind: str, waited_h: float, blocked: str) -> Ranked:
    one = Candidate('o/r', 'feat/x', SHA, 'windows', kind, NOW - timedelta(hours=waited_h))
    return Ranked(one, 60.0, 4.0, 15.0, waited_h, blocked)


def test_a_candidate_waiting_past_its_bound_raises_a_starved_alarm_naming_why(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROLS: the same wait unblocked, and a blocked wait under the bound, raise nothing."""
    jammed = TickReport((), (), ('tick',), (), (_waiting('pr', 13, 'outranked by integrate/main@x'),))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, jammed)
    (alarm,) = alarms
    assert (alarm.kind, alarm.about) == (STARVED, f'feat/x@{SHA[:12]}:windows')
    assert 'waited 13.0 h, past its 12 h bound' in alarm.body
    assert 'outranked by integrate/main@x' in alarm.body
    calm = TickReport((), (), ('tick',), (), (_waiting('pr', 13, ''), _waiting('pr', 11, 'outranked by y')))
    assert _serve(monkeypatch, tmp_path, calm)[2] == []


def test_every_tick_publishes_the_host_card(monkeypatch, tmp_path: Path) -> None:
    """Who it is, what it serves, its headroom and facts, and why each candidate waits."""
    cards: list = []
    ticked = TickReport((), (), ('tick',), (), (_waiting('pr', 1, 'no headroom: no free core here'),))
    _serve(monkeypatch, tmp_path, ticked, seat=SEAT, cluster=_Slurm, cards=cards, host='linux')
    (card,) = cards
    assert (card.host, card.login, card.platform) == ('ada/alice', 'alice', 'linux')
    assert card.headroom == {'cores': 64, 'submits': 10}
    assert card.facts == {'partitions': {'defq': 2880}}
    assert card.ticked == FORGE_NOW.isoformat(), "the forge's clock, never the host's"
    assert card.waiting == {f'feat/x@{SHA[:12]}:windows': 'no headroom: no free core here'}


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
    assert forge.posts[-1] == ('tests/linux', 'error', f'superseded by {tip[:12]}')
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
